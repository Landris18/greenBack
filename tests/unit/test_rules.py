from datetime import UTC, datetime

import pytest

from app.core.enums import ContainerStatus, RuleCode
from app.recommendation.rules import RuleThresholds, evaluate
from app.recommendation.rules.base import ContainerAnalysis

THRESHOLDS = RuleThresholds(
    cpu_high_percent=80.0,
    memory_high_percent=85.0,
    cpu_underuse_percent=30.0,
    memory_underuse_percent=40.0,
    idle_cpu_percent=1.0,
    idle_network_bps=1024.0,
    idle_hours=24,
    image_size_bytes=1024**3,
    exited_days=3,
    restart_count=5,
    emission_factor_g_per_kwh=52.0,
)


def analysis(**overrides) -> ContainerAnalysis:
    defaults = dict(
        container_id=1,
        name="api",
        image_ref="demo:latest",
        image_size_bytes=200 * 1024**2,
        status=ContainerStatus.RUNNING,
        restart_count=0,
        cpu_limit_cores=None,
        memory_limit_bytes=None,
        cpu_cores_p95=0.5,
        cpu_percent_p95=12.5,
        memory_working_set_p95=400 * 1024**2,
        cpu_percent_of_limit_p95=None,
        memory_percent_of_limit_p95=None,
        net_rate_p95=50_000.0,
        energy_wh_total=100.0,
        window_hours=168.0,
        sample_count=1000,
        last_seen_at=datetime.now(UTC),
        exited_days=None,
    )
    defaults.update(overrides)
    return ContainerAnalysis(**defaults)


def codes(findings) -> set[RuleCode]:
    return {finding.rule_code for finding in findings}


def find(findings, code: RuleCode):
    return next(finding for finding in findings if finding.rule_code is code)


class TestCpuOverprovisioned:
    def test_triggers_when_usage_is_far_below_the_limit(self):
        findings = evaluate(analysis(cpu_limit_cores=4.0, cpu_cores_p95=0.5), THRESHOLDS)
        assert RuleCode.CPU_OVERPROVISIONED in codes(findings)

    def test_silent_when_usage_matches_the_limit(self):
        findings = evaluate(analysis(cpu_limit_cores=1.0, cpu_cores_p95=0.8), THRESHOLDS)
        assert RuleCode.CPU_OVERPROVISIONED not in codes(findings)

    def test_silent_without_a_limit(self):
        findings = evaluate(analysis(cpu_limit_cores=None), THRESHOLDS)
        assert RuleCode.CPU_OVERPROVISIONED not in codes(findings)

    def test_silent_with_too_few_samples(self):
        findings = evaluate(
            analysis(cpu_limit_cores=4.0, cpu_cores_p95=0.5, sample_count=3), THRESHOLDS
        )
        assert RuleCode.CPU_OVERPROVISIONED not in codes(findings)

    def test_gain_is_declared_non_quantifiable(self):
        findings = evaluate(analysis(cpu_limit_cores=4.0, cpu_cores_p95=0.5), THRESHOLDS)
        finding = find(findings, RuleCode.CPU_OVERPROVISIONED)
        assert finding.saving_is_computed is False
        assert finding.energy_saving_kwh is None
        assert "non quantifiable" in finding.saving_note


class TestMemoryOverprovisioned:
    def test_triggers_when_far_below_the_limit(self):
        findings = evaluate(
            analysis(memory_limit_bytes=4 * 1024**3, memory_working_set_p95=200 * 1024**2),
            THRESHOLDS,
        )
        assert RuleCode.MEMORY_OVERPROVISIONED in codes(findings)

    def test_silent_when_close_to_the_limit(self):
        findings = evaluate(
            analysis(memory_limit_bytes=512 * 1024**2, memory_working_set_p95=400 * 1024**2),
            THRESHOLDS,
        )
        assert RuleCode.MEMORY_OVERPROVISIONED not in codes(findings)


class TestNoLimitsSet:
    def test_triggers_when_neither_limit_is_set(self):
        findings = evaluate(analysis(), THRESHOLDS)
        assert RuleCode.NO_LIMITS_SET in codes(findings)

    def test_silent_when_one_limit_exists(self):
        findings = evaluate(analysis(cpu_limit_cores=1.0), THRESHOLDS)
        assert RuleCode.NO_LIMITS_SET not in codes(findings)


class TestIdleContainer:
    def _idle(self, **overrides):
        defaults = {"cpu_percent_p95": 0.2, "net_rate_p95": 100.0}
        defaults.update(overrides)
        return analysis(**defaults)

    def test_triggers_on_a_quiet_container(self):
        findings = evaluate(self._idle(), THRESHOLDS)
        assert RuleCode.IDLE_CONTAINER in codes(findings)

    def test_silent_when_the_window_is_too_short(self):
        findings = evaluate(self._idle(window_hours=3.0), THRESHOLDS)
        assert RuleCode.IDLE_CONTAINER not in codes(findings)

    def test_silent_when_network_traffic_is_significant(self):
        findings = evaluate(self._idle(net_rate_p95=50_000.0), THRESHOLDS)
        assert RuleCode.IDLE_CONTAINER not in codes(findings)

    def test_silent_when_the_container_is_stopped(self):
        findings = evaluate(self._idle(status=ContainerStatus.EXITED), THRESHOLDS)
        assert RuleCode.IDLE_CONTAINER not in codes(findings)

    def test_gain_is_computed_and_extrapolated_over_thirty_days(self):
        findings = evaluate(self._idle(energy_wh_total=168.0, window_hours=168.0), THRESHOLDS)
        finding = find(findings, RuleCode.IDLE_CONTAINER)
        assert finding.saving_is_computed is True
        assert finding.energy_saving_kwh == pytest.approx(0.72)
        assert finding.co2_saving_kg == pytest.approx(0.72 * 52.0 / 1000.0, abs=1e-4)

    def test_gain_is_zero_without_an_observation_window(self):
        findings = evaluate(self._idle(window_hours=0.0), THRESHOLDS)
        assert RuleCode.IDLE_CONTAINER not in codes(findings)


class TestOversizedImage:
    def test_triggers_above_the_threshold(self):
        findings = evaluate(analysis(image_size_bytes=4 * 1024**3), THRESHOLDS)
        assert RuleCode.OVERSIZED_IMAGE in codes(findings)

    def test_gain_is_expressed_in_storage_not_energy(self):
        findings = evaluate(analysis(image_size_bytes=4 * 1024**3), THRESHOLDS)
        finding = find(findings, RuleCode.OVERSIZED_IMAGE)
        assert finding.saving_is_computed is False
        assert finding.energy_saving_kwh is None

    def test_silent_below_the_threshold(self):
        findings = evaluate(analysis(image_size_bytes=100 * 1024**2), THRESHOLDS)
        assert RuleCode.OVERSIZED_IMAGE not in codes(findings)


class TestExitedContainer:
    def test_triggers_after_the_grace_period(self):
        findings = evaluate(analysis(status=ContainerStatus.EXITED, exited_days=10.0), THRESHOLDS)
        assert RuleCode.EXITED_CONTAINER_PRESENT in codes(findings)

    def test_silent_within_the_grace_period(self):
        findings = evaluate(analysis(status=ContainerStatus.EXITED, exited_days=1.0), THRESHOLDS)
        assert RuleCode.EXITED_CONTAINER_PRESENT not in codes(findings)


class TestRestartLoop:
    def test_triggers_above_the_threshold(self):
        findings = evaluate(analysis(restart_count=12), THRESHOLDS)
        assert RuleCode.RESTART_LOOP in codes(findings)

    def test_silent_below_the_threshold(self):
        findings = evaluate(analysis(restart_count=1), THRESHOLDS)
        assert RuleCode.RESTART_LOOP not in codes(findings)


class TestHonestyInvariant:
    def test_only_the_idle_rule_reports_a_computed_energy_gain(self):
        every_finding = []
        every_finding += evaluate(analysis(cpu_limit_cores=4.0, cpu_cores_p95=0.1), THRESHOLDS)
        every_finding += evaluate(
            analysis(memory_limit_bytes=4 * 1024**3, memory_working_set_p95=1024), THRESHOLDS
        )
        every_finding += evaluate(analysis(image_size_bytes=4 * 1024**3), THRESHOLDS)
        every_finding += evaluate(analysis(restart_count=99), THRESHOLDS)
        every_finding += evaluate(
            analysis(status=ContainerStatus.EXITED, exited_days=30.0), THRESHOLDS
        )
        every_finding += evaluate(analysis(cpu_percent_p95=0.1, net_rate_p95=10.0), THRESHOLDS)

        computed = {f.rule_code for f in every_finding if f.saving_is_computed}
        assert computed == {RuleCode.IDLE_CONTAINER}

        for finding in every_finding:
            if not finding.saving_is_computed:
                assert finding.energy_saving_kwh is None
                assert finding.saving_note
