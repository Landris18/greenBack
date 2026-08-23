from app.collector.snapshot import (
    build_snapshot,
    parse_blkio,
    parse_cpu_limit,
    parse_memory_limit,
    parse_networks,
    parse_online_cpus,
    parse_started_at,
)

CONTAINER_ATTRS = {
    "Id": "id-api",
    "Name": "/api",
    "Image": "sha256:image-demo",
    "RestartCount": 2,
    "State": {"Status": "running", "StartedAt": "2026-08-01T10:00:00.000000000Z"},
    "Config": {"Image": "demo:latest", "Labels": {"com.docker.compose.project": "demo"}},
    "HostConfig": {"NanoCpus": 2_000_000_000, "Memory": 1_073_741_824},
}


class TestParseCpuLimit:
    def test_nano_cpus(self):
        assert parse_cpu_limit({"NanoCpus": 1_500_000_000}) == 1.5

    def test_quota_and_period(self):
        assert parse_cpu_limit({"CpuQuota": 50_000, "CpuPeriod": 100_000}) == 0.5

    def test_no_limit(self):
        assert parse_cpu_limit({"NanoCpus": 0, "CpuQuota": 0}) is None

    def test_empty_host_config(self):
        assert parse_cpu_limit({}) is None


class TestParseMemoryLimit:
    def test_limit_set(self):
        assert parse_memory_limit({"Memory": 536_870_912}) == 536_870_912

    def test_zero_means_unlimited(self):
        assert parse_memory_limit({"Memory": 0}) is None


class TestParseCounters:
    def test_blkio_sums_read_and_write(self):
        stats = {
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "Read", "value": 100},
                    {"op": "read", "value": 50},
                    {"op": "Write", "value": 400},
                    {"op": "Sync", "value": 999},
                ]
            }
        }
        assert parse_blkio(stats) == (150, 400)

    def test_blkio_missing_on_cgroup_v2(self):
        assert parse_blkio({"blkio_stats": {"io_service_bytes_recursive": None}}) == (0, 0)

    def test_networks_sum_all_interfaces(self):
        stats = {
            "networks": {
                "eth0": {"rx_bytes": 10, "tx_bytes": 20},
                "eth1": {"rx_bytes": 5, "tx_bytes": 7},
            }
        }
        assert parse_networks(stats) == (15, 27)

    def test_networks_absent(self):
        assert parse_networks({}) == (0, 0)

    def test_online_cpus_falls_back_to_percpu_length(self):
        stats = {"cpu_stats": {"cpu_usage": {"percpu_usage": [1, 2, 3]}}}
        assert parse_online_cpus(stats, fallback=8) == 3

    def test_online_cpus_falls_back_to_host(self):
        assert parse_online_cpus({}, fallback=8) == 8


class TestParseStartedAt:
    def test_nanosecond_precision_is_truncated(self):
        parsed = parse_started_at("2026-08-01T10:00:00.123456789Z")
        assert parsed is not None
        assert parsed.microsecond == 123456

    def test_zero_value_means_never_started(self):
        assert parse_started_at("0001-01-01T00:00:00Z") is None

    def test_empty_value(self):
        assert parse_started_at(None) is None


class TestBuildSnapshot:
    def test_full_snapshot(self):
        snapshot = build_snapshot(CONTAINER_ATTRS, image_size_bytes=123)

        assert snapshot.name == "api"
        assert snapshot.cpu_limit_cores == 2.0
        assert snapshot.memory_limit_bytes == 1_073_741_824
        assert snapshot.restart_count == 2
        assert snapshot.image_size_bytes == 123
        assert snapshot.labels == {"com.docker.compose.project": "demo"}
        assert snapshot.status == "running"

    def test_strips_the_leading_slash_from_the_name(self):
        assert build_snapshot({"Name": "/mon-api"}, None).name == "mon-api"

    def test_tolerates_a_minimal_payload(self):
        snapshot = build_snapshot({}, None)
        assert snapshot.status == "unknown"
        assert snapshot.cpu_limit_cores is None
