import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.collector.snapshot import parse_blkio, parse_networks, parse_online_cpus
from app.energy.model import CpuCounters, compute_memory_working_set

STALE_FRAME_SECONDS = 3.0


@dataclass(frozen=True)
class StatsFrame:
    docker_id: str
    read_at: datetime
    counters: CpuCounters
    previous_counters: CpuCounters | None
    memory_working_set_bytes: int
    memory_limit_bytes: int | None
    net_rx_bytes: int
    net_tx_bytes: int
    blk_read_bytes: int
    blk_write_bytes: int
    pids: int
    raw_memory_stats: dict[str, int] = field(default_factory=dict)


def _parse_read_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    cleaned = value.replace("Z", "+00:00")
    if "." in cleaned:
        head, _, tail = cleaned.partition(".")
        fraction, sign, offset = tail.partition("+")
        cleaned = f"{head}.{fraction[:6]}+{offset}" if sign else f"{head}.{fraction[:6]}"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _counters(block: dict[str, Any], host_cpu_cores: int) -> CpuCounters | None:
    usage = (block or {}).get("cpu_usage") or {}
    total = usage.get("total_usage")
    system = (block or {}).get("system_cpu_usage")
    if total is None or system is None:
        return None
    return CpuCounters(
        cpu_total_usage_ns=int(total),
        system_cpu_usage_ns=int(system),
        online_cpus=parse_online_cpus({"cpu_stats": block}, host_cpu_cores),
    )


def parse_stats_frame(
    payload: str | dict[str, Any], docker_id: str, host_cpu_cores: int
) -> StatsFrame | None:
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    else:
        data = payload

    if not isinstance(data, dict):
        return None

    counters = _counters(data.get("cpu_stats") or {}, host_cpu_cores)
    if counters is None:
        return None

    memory_stats = data.get("memory_stats") or {}
    inner = {
        str(key): int(value)
        for key, value in (memory_stats.get("stats") or {}).items()
        if isinstance(value, int | float)
    }
    memory_limit = memory_stats.get("limit")
    net_rx, net_tx = parse_networks(data)
    blk_read, blk_write = parse_blkio(data)

    return StatsFrame(
        docker_id=docker_id,
        read_at=_parse_read_at(data.get("read")),
        counters=counters,
        previous_counters=_counters(data.get("precpu_stats") or {}, host_cpu_cores),
        memory_working_set_bytes=compute_memory_working_set(
            int(memory_stats.get("usage") or 0), inner
        ),
        memory_limit_bytes=int(memory_limit) if memory_limit else None,
        net_rx_bytes=net_rx,
        net_tx_bytes=net_tx,
        blk_read_bytes=blk_read,
        blk_write_bytes=blk_write,
        pids=int((data.get("pids_stats") or {}).get("current") or 0),
        raw_memory_stats=inner,
    )


def is_stale(frame: StatsFrame, now: datetime, tolerance: float = STALE_FRAME_SECONDS) -> bool:
    return (now - frame.read_at).total_seconds() > tolerance


def percent_of_limit(used: float, limit: float | None) -> float | None:
    if not limit or limit <= 0:
        return None
    return used / limit * 100.0
