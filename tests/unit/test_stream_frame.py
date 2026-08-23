import json
from datetime import UTC, datetime, timedelta

import pytest

from app.collector.frame import is_stale, parse_stats_frame, percent_of_limit
from app.collector.stream import base_url_from_docker_host

NOW = datetime(2026, 8, 14, 10, 0, 0, tzinfo=UTC)


def frame_payload(**overrides) -> dict:
    payload = {
        "read": "2026-08-14T10:00:00.123456789Z",
        "cpu_stats": {
            "cpu_usage": {"total_usage": 5_000_000_000},
            "system_cpu_usage": 400_000_000_000,
            "online_cpus": 4,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 4_000_000_000},
            "system_cpu_usage": 396_000_000_000,
            "online_cpus": 4,
        },
        "memory_stats": {
            "usage": 500_000_000,
            "limit": 1_073_741_824,
            "stats": {"inactive_file": 100_000_000},
        },
        "networks": {"eth0": {"rx_bytes": 1_000, "tx_bytes": 2_000}},
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "Read", "value": 300},
                {"op": "Write", "value": 400},
            ]
        },
        "pids_stats": {"current": 7},
    }
    payload.update(overrides)
    return payload


class TestParseStatsFrame:
    def test_nominal_frame(self):
        frame = parse_stats_frame(json.dumps(frame_payload()), "abc123", 8)
        assert frame is not None
        assert frame.docker_id == "abc123"
        assert frame.counters.cpu_total_usage_ns == 5_000_000_000
        assert frame.previous_counters is not None
        assert frame.memory_working_set_bytes == 400_000_000
        assert frame.memory_limit_bytes == 1_073_741_824
        assert frame.net_rx_bytes == 1_000
        assert frame.blk_write_bytes == 400
        assert frame.pids == 7

    def test_nanosecond_timestamp_is_truncated(self):
        frame = parse_stats_frame(json.dumps(frame_payload()), "abc", 8)
        assert frame.read_at.microsecond == 123456

    def test_missing_precpu_is_tolerated(self):
        payload = frame_payload()
        payload.pop("precpu_stats")
        frame = parse_stats_frame(json.dumps(payload), "abc", 8)
        assert frame is not None
        assert frame.previous_counters is None

    def test_empty_precpu_block_yields_no_previous(self):
        frame = parse_stats_frame(json.dumps(frame_payload(precpu_stats={})), "abc", 8)
        assert frame.previous_counters is None

    def test_frame_without_cpu_stats_is_rejected(self):
        payload = frame_payload()
        payload.pop("cpu_stats")
        assert parse_stats_frame(json.dumps(payload), "abc", 8) is None

    def test_truncated_json_is_rejected(self):
        assert parse_stats_frame('{"cpu_stats": {"cpu_us', "abc", 8) is None

    def test_blank_line_is_rejected(self):
        assert parse_stats_frame("   \n", "abc", 8) is None

    def test_non_object_payload_is_rejected(self):
        assert parse_stats_frame("[1, 2, 3]", "abc", 8) is None

    def test_online_cpus_falls_back_to_host(self):
        payload = frame_payload()
        payload["cpu_stats"].pop("online_cpus")
        frame = parse_stats_frame(json.dumps(payload), "abc", 12)
        assert frame.counters.online_cpus == 12

    def test_accepts_a_dict_payload(self):
        assert parse_stats_frame(frame_payload(), "abc", 8) is not None


class TestStaleness:
    def _frame(self, seconds_ago: float):
        payload = frame_payload(
            read=(NOW - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")
        )
        return parse_stats_frame(json.dumps(payload), "abc", 8)

    def test_fresh_frame_is_kept(self):
        assert is_stale(self._frame(0.5), NOW) is False

    def test_frame_at_the_tolerance_is_kept(self):
        assert is_stale(self._frame(3.0), NOW) is False

    def test_older_frame_is_dropped(self):
        assert is_stale(self._frame(5.0), NOW) is True


class TestPercentOfLimit:
    def test_computes_ratio(self):
        assert percent_of_limit(0.42, 0.5) == pytest.approx(84.0)

    def test_no_limit_yields_none(self):
        assert percent_of_limit(0.42, None) is None

    def test_zero_limit_yields_none(self):
        assert percent_of_limit(0.42, 0) is None


class TestBaseUrl:
    def test_tcp_becomes_http(self):
        assert base_url_from_docker_host("tcp://proxy:2375") == "http://proxy:2375"

    def test_http_is_kept(self):
        assert base_url_from_docker_host("http://proxy:2375") == "http://proxy:2375"

    def test_unix_socket_is_refused(self):
        with pytest.raises(ValueError, match="TCP"):
            base_url_from_docker_host("unix:///var/run/docker.sock")
