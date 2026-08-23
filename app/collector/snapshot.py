from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

NANO_PER_CORE = 1_000_000_000


@dataclass(frozen=True)
class ContainerSnapshot:
    docker_id: str
    name: str
    image_ref: str
    image_id: str | None
    image_size_bytes: int | None
    status: str
    restart_count: int
    started_at: datetime | None
    labels: dict[str, str]
    cpu_limit_cores: float | None
    memory_limit_bytes: int | None


@dataclass(frozen=True)
class HostInfo:
    cpu_cores: int
    total_memory_bytes: int
    os_info: str


def parse_started_at(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    if "." in cleaned:
        head, _, tail = cleaned.partition(".")
        fraction, sign, offset = tail.partition("+")
        cleaned = f"{head}.{fraction[:6]}{sign}{offset}" if sign else f"{head}.{fraction[:6]}"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.year < 1971:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_cpu_limit(host_config: dict[str, Any]) -> float | None:
    nano_cpus = host_config.get("NanoCpus") or 0
    if nano_cpus:
        return round(nano_cpus / NANO_PER_CORE, 4)

    quota = host_config.get("CpuQuota") or 0
    period = host_config.get("CpuPeriod") or 0
    if quota > 0 and period > 0:
        return round(quota / period, 4)
    return None


def parse_memory_limit(host_config: dict[str, Any]) -> int | None:
    memory = host_config.get("Memory") or 0
    return int(memory) if memory > 0 else None


def parse_blkio(stats: dict[str, Any]) -> tuple[int, int]:
    blkio = stats.get("blkio_stats") or {}
    entries = blkio.get("io_service_bytes_recursive") or []
    read_bytes = 0
    write_bytes = 0
    for entry in entries:
        operation = str(entry.get("op", "")).lower()
        value = int(entry.get("value") or 0)
        if operation == "read":
            read_bytes += value
        elif operation == "write":
            write_bytes += value
    return read_bytes, write_bytes


def parse_networks(stats: dict[str, Any]) -> tuple[int, int]:
    networks = stats.get("networks") or {}
    rx = sum(int(iface.get("rx_bytes") or 0) for iface in networks.values())
    tx = sum(int(iface.get("tx_bytes") or 0) for iface in networks.values())
    return rx, tx


def parse_online_cpus(stats: dict[str, Any], fallback: int) -> int:
    cpu_stats = stats.get("cpu_stats") or {}
    online = cpu_stats.get("online_cpus")
    if online:
        return int(online)
    percpu = (cpu_stats.get("cpu_usage") or {}).get("percpu_usage") or []
    return len(percpu) or fallback or 1


def build_snapshot(attrs: dict[str, Any], image_size_bytes: int | None) -> ContainerSnapshot:
    state = attrs.get("State") or {}
    config = attrs.get("Config") or {}
    host_config = attrs.get("HostConfig") or {}

    return ContainerSnapshot(
        docker_id=attrs.get("Id", ""),
        name=str(attrs.get("Name", "")).lstrip("/"),
        image_ref=config.get("Image") or attrs.get("Image") or "",
        image_id=attrs.get("Image"),
        image_size_bytes=image_size_bytes,
        status=state.get("Status") or "unknown",
        restart_count=int(attrs.get("RestartCount") or 0),
        started_at=parse_started_at(state.get("StartedAt")),
        labels={str(k): str(v) for k, v in (config.get("Labels") or {}).items()},
        cpu_limit_cores=parse_cpu_limit(host_config),
        memory_limit_bytes=parse_memory_limit(host_config),
    )
