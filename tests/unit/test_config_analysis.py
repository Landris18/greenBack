import pytest

from app.config_analysis import parse_compose, parse_dockerfile
from app.config_analysis.parsers import (
    apt_without_cleanup,
    installs_build_tooling,
    is_light_image,
    parse_memory_value,
)
from app.config_analysis.patch import (
    find_key_line,
    find_service_block,
    remove_service,
    set_service_key,
)
from app.config_analysis.rules import ConfigContext, ServiceObservation, evaluate_config
from app.core.enums import RuleCode
from app.recommendation.rules.base import RuleThresholds

MB = 1024**2

THRESHOLDS = RuleThresholds(
    cpu_high_percent=80.0,
    memory_high_percent=85.0,
    cpu_underuse_percent=30.0,
    memory_underuse_percent=40.0,
    idle_cpu_percent=1.0,
    idle_network_bps=1024.0,
    idle_hours=1,
    image_size_bytes=1024**3,
    exited_days=3,
    restart_count=5,
    emission_factor_g_per_kwh=52.0,
)

HEAVY_DOCKERFILE = """FROM python:3.12

WORKDIR /srv

RUN apt-get update \\
    && apt-get install -y --no-install-recommends \\
        build-essential \\
        git

RUN pip install --no-cache-dir numpy pandas

COPY app/ /srv/

CMD ["python", "server.py"]
"""

LIGHT_DOCKERFILE = """FROM python:3.12-slim AS builder
WORKDIR /build
COPY app/ /build/
RUN python -m compileall -q /build

FROM python:3.12-slim AS runtime
WORKDIR /srv
RUN addgroup --system demo && adduser --system --ingroup demo demo
COPY --from=builder --chown=demo:demo /build/ /srv/
USER demo
CMD ["python", "server.py"]
"""

COMPOSE_BEFORE = """name: demo

services:
  api:
    build:
      context: ./demo
      dockerfile: Dockerfile.before
    restart: unless-stopped
    environment:
      VARIANT: avant

  cache:
    image: redis:7
    restart: unless-stopped

  db:
    image: postgres:16
    mem_limit: 8g

networks:
  demo:
"""


def observation(name: str, **overrides) -> ServiceObservation:
    defaults = dict(
        service_name=name,
        container_id=1,
        cpu_cores_p95=0.4,
        memory_working_set_p95=300 * MB,
        is_idle=False,
        sample_count=600,
        energy_wh_total=120.0,
        window_hours=2.0,
    )
    defaults.update(overrides)
    return ServiceObservation(**defaults)


def codes(findings) -> set[RuleCode]:
    return {finding.rule_code for finding in findings}


def find(findings, code: RuleCode):
    return next(item for item in findings if item.rule_code is code)


class TestMemoryParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("8g", 8 * 1024**3),
            ("512m", 512 * MB),
            ("2048k", 2048 * 1024),
            ("1024", 1024),
            ("2G", 2 * 1024**3),
            (536870912, 536870912),
        ],
    )
    def test_units(self, raw, expected):
        assert parse_memory_value(raw) == expected

    def test_invalid_value(self):
        assert parse_memory_value("beaucoup") is None

    def test_absent_value(self):
        assert parse_memory_value(None) is None


class TestDockerfileParser:
    def test_counts_stages(self):
        assert parse_dockerfile(HEAVY_DOCKERFILE).stage_count == 1
        assert parse_dockerfile(LIGHT_DOCKERFILE).stage_count == 2

    def test_joins_line_continuations(self):
        parsed = parse_dockerfile(HEAVY_DOCKERFILE)
        run_lines = parsed.by_keyword("RUN")
        assert any("build-essential" in item.value for item in run_lines)
        assert run_lines[0].line_number == 5

    def test_detects_user_instruction(self):
        assert parse_dockerfile(LIGHT_DOCKERFILE).has_user is True
        assert parse_dockerfile(HEAVY_DOCKERFILE).has_user is False

    def test_ignores_comments_and_blanks(self):
        parsed = parse_dockerfile("# commentaire\n\nFROM alpine\n")
        assert [item.keyword for item in parsed.instructions] == ["FROM"]

    def test_build_tooling_detection(self):
        assert installs_build_tooling(parse_dockerfile(HEAVY_DOCKERFILE))
        assert not installs_build_tooling(parse_dockerfile(LIGHT_DOCKERFILE))

    def test_apt_cleanup_detection(self):
        assert apt_without_cleanup(parse_dockerfile(HEAVY_DOCKERFILE))
        cleaned = HEAVY_DOCKERFILE.replace(
            "        git", "        git \\\n    && rm -rf /var/lib/apt/lists/*"
        )
        assert not apt_without_cleanup(parse_dockerfile(cleaned))


class TestLightImage:
    @pytest.mark.parametrize(
        ("image", "expected"),
        [
            ("python:3.12", False),
            ("python:3.12-slim", True),
            ("postgres:16-alpine", True),
            ("redis:7", False),
        ],
    )
    def test_detection(self, image, expected):
        assert is_light_image(image) is expected


class TestComposeParser:
    def test_reads_services_and_limits(self):
        parsed = parse_compose(COMPOSE_BEFORE)
        assert set(parsed.services) == {"api", "cache", "db"}
        assert parsed.services["db"].memory_limit_bytes == 8 * 1024**3
        assert parsed.services["cache"].memory_limit_bytes is None
        assert parsed.services["api"].dockerfile == "Dockerfile.before"

    def test_reads_deploy_style_limits(self):
        content = (
            "services:\n"
            "  api:\n"
            "    image: demo\n"
            "    deploy:\n"
            "      resources:\n"
            "        limits:\n"
            "          memory: 512m\n"
            "          cpus: 0.5\n"
        )
        service = parse_compose(content).services["api"]
        assert service.memory_limit_bytes == 512 * MB
        assert service.cpus == 0.5


class TestPatchHelpers:
    def test_locates_service_block(self):
        block = find_service_block(COMPOSE_BEFORE, "cache")
        assert block is not None
        start, end, indent = block
        assert COMPOSE_BEFORE.splitlines()[start].strip() == "cache:"
        assert indent == "  "
        assert end > start

    def test_unknown_service(self):
        assert find_service_block(COMPOSE_BEFORE, "absent") is None

    def test_replaces_existing_key(self):
        updated = set_service_key(COMPOSE_BEFORE, "db", "mem_limit", "512m")
        assert "mem_limit: 512m" in updated
        assert "mem_limit: 8g" not in updated
        assert parse_compose(updated).services["db"].memory_limit_bytes == 512 * MB

    def test_inserts_missing_key(self):
        updated = set_service_key(COMPOSE_BEFORE, "cache", "mem_limit", "64m")
        assert parse_compose(updated).services["cache"].memory_limit_bytes == 64 * MB
        assert parse_compose(updated).services["db"].memory_limit_bytes == 8 * 1024**3

    def test_key_line_lookup(self):
        assert find_key_line(COMPOSE_BEFORE, "db", "mem_limit") is not None
        assert find_key_line(COMPOSE_BEFORE, "db", "cpus") is None

    def test_remove_service_keeps_the_rest_valid(self):
        updated = remove_service(COMPOSE_BEFORE, "cache")
        parsed = parse_compose(updated)
        assert set(parsed.services) == {"api", "db"}


class TestConfigRules:
    def _context(self, **overrides) -> ConfigContext:
        defaults = dict(
            compose=parse_compose(COMPOSE_BEFORE, "docker-compose.yml"),
            dockerfiles={"api": parse_dockerfile(HEAVY_DOCKERFILE, "Dockerfile.before")},
            observations={
                "api": observation("api"),
                "cache": observation("cache", memory_working_set_p95=8 * MB, cpu_cores_p95=0.001),
                "db": observation("db", memory_working_set_p95=120 * MB),
            },
        )
        defaults.update(overrides)
        return ConfigContext(**defaults)

    def test_detects_the_expected_set_on_a_realistic_project(self):
        findings = evaluate_config(self._context(), THRESHOLDS)
        assert {
            RuleCode.HEAVY_BASE_IMAGE,
            RuleCode.NO_MULTISTAGE_BUILD,
            RuleCode.APT_CACHE_NOT_CLEANED,
            RuleCode.RUNS_AS_ROOT,
            RuleCode.COMPOSE_NO_LIMITS,
            RuleCode.COMPOSE_LIMIT_TOO_HIGH,
        } <= codes(findings)

    def test_stays_silent_on_an_already_optimised_project(self):
        context = ConfigContext(
            compose=parse_compose(
                "services:\n  api:\n    image: demo\n    cpus: 0.5\n    mem_limit: 256m\n"
            ),
            dockerfiles={"api": parse_dockerfile(LIGHT_DOCKERFILE)},
            observations={"api": observation("api", memory_working_set_p95=150 * MB)},
        )
        findings = evaluate_config(context, THRESHOLDS)
        assert codes(findings) == set()

    def test_heavy_base_image_patch_is_applicable(self):
        finding = find(evaluate_config(self._context(), THRESHOLDS), RuleCode.HEAVY_BASE_IMAGE)
        assert finding.patch is not None
        assert "python:3.12-slim" in finding.patch["after"]
        assert finding.patch["unified_diff"].startswith("---")
        assert "-FROM python:3.12" in finding.patch["unified_diff"]
        assert "+FROM python:3.12-slim" in finding.patch["unified_diff"]

    def test_compose_limit_patch_produces_valid_yaml(self):
        finding = find(
            evaluate_config(self._context(), THRESHOLDS), RuleCode.COMPOSE_LIMIT_TOO_HIGH
        )
        assert finding.patch is not None
        assert "mem_limit" in finding.patch["after"]
        assert finding.suggested_value["mem_limit"] == "180m"

    def test_no_limits_patch_sets_both_keys(self):
        finding = find(evaluate_config(self._context(), THRESHOLDS), RuleCode.COMPOSE_NO_LIMITS)
        assert "cpus" in finding.patch["after"]
        assert "mem_limit" in finding.patch["after"]

    def test_unused_service_is_the_only_computed_gain(self):
        context = self._context(
            observations={
                "api": observation("api"),
                "cache": observation("cache", is_idle=True, energy_wh_total=2.0, window_hours=2.0),
                "db": observation("db", memory_working_set_p95=120 * MB),
            }
        )
        findings = evaluate_config(context, THRESHOLDS)
        computed = {item.rule_code for item in findings if item.saving_is_computed}
        assert computed == {RuleCode.UNUSED_SERVICE}

        unused = find(findings, RuleCode.UNUSED_SERVICE)
        assert unused.energy_saving_kwh == pytest.approx(0.72)
        assert "cache:" not in unused.patch["after"]

    def test_every_non_computed_finding_carries_an_explanation(self):
        for finding in evaluate_config(self._context(), THRESHOLDS):
            if not finding.saving_is_computed:
                assert finding.energy_saving_kwh is None
                assert finding.saving_note

    def test_no_compose_yields_only_dockerfile_findings(self):
        context = self._context(compose=None)
        for finding in evaluate_config(context, THRESHOLDS):
            assert finding.rule_code not in {
                RuleCode.COMPOSE_NO_LIMITS,
                RuleCode.COMPOSE_LIMIT_TOO_HIGH,
                RuleCode.UNUSED_SERVICE,
            }
