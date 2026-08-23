from collections.abc import Iterable
from dataclasses import dataclass, field

from app.core.enums import IdleAttributionPolicy

SECONDS_PER_HOUR = 3600.0
BYTES_PER_GB = 1024**3
DEFAULT_RAPL_MAX_RANGE_UJ = 262_143_328_850
MICROWATTS_PER_WATT = 1_000_000.0
PICOWATTS_PER_WATT = 1_000_000_000_000.0
DEFAULT_MAX_IDLE_RATIO = 0.7
BATTERY_DISCHARGING = "discharging"
RAPL_PLATFORM_PREFIX = "psys"
RAPL_ADDITIVE_PREFIXES = ("package-", "dram")


@dataclass(frozen=True)
class CpuCounters:
    cpu_total_usage_ns: int
    system_cpu_usage_ns: int
    online_cpus: int


@dataclass(frozen=True)
class CpuUsage:
    cores_used: float
    percent_of_host: float


@dataclass(frozen=True)
class AttributionWeights:
    cpu: float = 0.70
    memory: float = 0.20
    io: float = 0.06
    network: float = 0.04


@dataclass(frozen=True)
class PowerModelParams:
    p_idle_watts: float
    p_max_watts: float
    mem_power_w_per_gb: float
    non_cpu_overhead_ratio: float


@dataclass(frozen=True)
class ContainerLoad:
    key: int
    cpu_cores_used: float
    memory_bytes: float
    io_rate_bps: float
    net_rate_bps: float


@dataclass(frozen=True)
class HostLoad:
    cpu_cores_used: float
    memory_used_bytes: float
    io_rate_bps: float
    net_rate_bps: float


@dataclass(frozen=True)
class PowerSplit:
    total_watts: float
    idle_watts: float
    dynamic_watts: float


@dataclass(frozen=True)
class Attribution:
    shares: dict[int, float] = field(default_factory=dict)
    container_watts: dict[int, float] = field(default_factory=dict)
    overhead_watts: float = 0.0
    total_watts: float = 0.0


def compute_cpu_usage(
    current: CpuCounters, previous: CpuCounters | None, host_cpu_cores: int
) -> CpuUsage:
    if previous is None:
        return CpuUsage(cores_used=0.0, percent_of_host=0.0)

    cpu_delta = current.cpu_total_usage_ns - previous.cpu_total_usage_ns
    system_delta = current.system_cpu_usage_ns - previous.system_cpu_usage_ns
    if cpu_delta <= 0 or system_delta <= 0:
        return CpuUsage(cores_used=0.0, percent_of_host=0.0)

    online_cpus = current.online_cpus or host_cpu_cores or 1
    cores_used = (cpu_delta / system_delta) * online_cpus
    cores_used = max(0.0, min(cores_used, float(online_cpus)))

    denominator = host_cpu_cores or online_cpus
    percent = (cores_used / denominator) * 100.0 if denominator else 0.0
    return CpuUsage(cores_used=cores_used, percent_of_host=percent)


def compute_memory_working_set(usage_bytes: int, stats: dict[str, int] | None) -> int:
    inactive_file = 0
    if stats:
        inactive_file = int(stats.get("inactive_file") or stats.get("total_inactive_file") or 0)
    return max(0, int(usage_bytes) - inactive_file)


def compute_rate(current: int, previous: int | None, interval_seconds: float) -> float:
    if previous is None or interval_seconds <= 0:
        return 0.0
    delta = current - previous
    if delta < 0:
        return 0.0
    return delta / interval_seconds


def rapl_delta_uj(
    current_uj: int, previous_uj: int | None, max_range_uj: int = DEFAULT_RAPL_MAX_RANGE_UJ
) -> int | None:
    if previous_uj is None:
        return None
    if max_range_uj <= 0:
        return None
    return (current_uj - previous_uj) % max_range_uj


def host_power_from_rapl(
    delta_uj: int, interval_seconds: float, non_cpu_overhead_ratio: float
) -> float:
    if interval_seconds <= 0:
        return 0.0
    package_watts = (delta_uj / 1_000_000.0) / interval_seconds
    return package_watts * (1.0 + max(0.0, non_cpu_overhead_ratio))


def select_rapl_zones(names: Iterable[str]) -> list[str]:
    inventaire = sorted({name.strip() for name in names if name and name.strip()})
    plateforme = [name for name in inventaire if name.lower().startswith(RAPL_PLATFORM_PREFIX)]
    if plateforme:
        return plateforme
    return [name for name in inventaire if name.lower().startswith(RAPL_ADDITIVE_PREFIXES)]


def host_power_from_battery(
    power_now_uw: int | None,
    status: str,
    current_now_ua: int | None = None,
    voltage_now_uv: int | None = None,
) -> float | None:
    if status.strip().lower() != BATTERY_DISCHARGING:
        return None
    if power_now_uw is not None and power_now_uw > 0:
        return power_now_uw / MICROWATTS_PER_WATT
    if current_now_ua and voltage_now_uv and current_now_ua > 0 and voltage_now_uv > 0:
        return (current_now_ua * voltage_now_uv) / PICOWATTS_PER_WATT
    return None


def host_power_from_hwmon(power_input_uw: int | None) -> float | None:
    if power_input_uw is None or power_input_uw <= 0:
        return None
    return power_input_uw / MICROWATTS_PER_WATT


def host_power_from_model(
    cpu_utilization: float, memory_used_bytes: float, params: PowerModelParams
) -> float:
    utilization = max(0.0, min(1.0, cpu_utilization))
    dynamic = (params.p_max_watts - params.p_idle_watts) * utilization
    memory_term = params.mem_power_w_per_gb * (memory_used_bytes / BYTES_PER_GB)
    return params.p_idle_watts + max(0.0, dynamic) + max(0.0, memory_term)


def split_power(
    total_watts: float, p_idle_watts: float, max_idle_ratio: float = DEFAULT_MAX_IDLE_RATIO
) -> PowerSplit:
    total = max(0.0, total_watts)
    plafond = total * max(0.0, min(1.0, max_idle_ratio))
    idle = max(0.0, min(p_idle_watts, plafond))
    return PowerSplit(total_watts=total, idle_watts=idle, dynamic_watts=total - idle)


def resource_share(load: ContainerLoad, host: HostLoad, weights: AttributionWeights) -> float:
    terms: list[tuple[float, float]] = []
    if host.cpu_cores_used > 0:
        terms.append((weights.cpu, load.cpu_cores_used / host.cpu_cores_used))
    if host.memory_used_bytes > 0:
        terms.append((weights.memory, load.memory_bytes / host.memory_used_bytes))
    if host.io_rate_bps > 0:
        terms.append((weights.io, load.io_rate_bps / host.io_rate_bps))
    if host.net_rate_bps > 0:
        terms.append((weights.network, load.net_rate_bps / host.net_rate_bps))

    total_weight = sum(weight for weight, _ in terms)
    if total_weight <= 0:
        return 0.0
    weighted = sum(weight * ratio for weight, ratio in terms)
    return max(0.0, weighted / total_weight)


def attribute_power(
    loads: list[ContainerLoad],
    host: HostLoad,
    split: PowerSplit,
    weights: AttributionWeights,
    policy: IdleAttributionPolicy = IdleAttributionPolicy.OVERHEAD,
) -> Attribution:
    if not loads:
        return Attribution(overhead_watts=split.total_watts, total_watts=split.total_watts)

    shares = {load.key: resource_share(load, host, weights) for load in loads}
    total_share = sum(shares.values())
    if total_share > 1.0:
        shares = {key: value / total_share for key, value in shares.items()}

    attributable = (
        split.total_watts if policy is IdleAttributionPolicy.PRORATA else split.dynamic_watts
    )
    container_watts = {key: attributable * share for key, share in shares.items()}
    overhead = split.total_watts - sum(container_watts.values())

    return Attribution(
        shares=shares,
        container_watts=container_watts,
        overhead_watts=max(0.0, overhead),
        total_watts=split.total_watts,
    )


def watts_to_wh(watts: float, interval_seconds: float) -> float:
    if interval_seconds <= 0:
        return 0.0
    return watts * interval_seconds / SECONDS_PER_HOUR


def wh_to_kwh(wh: float) -> float:
    return wh / 1000.0


def kwh_to_co2_g(kwh: float, emission_factor_g_per_kwh: float) -> float:
    return kwh * emission_factor_g_per_kwh


def wh_to_co2_g(wh: float, emission_factor_g_per_kwh: float) -> float:
    return kwh_to_co2_g(wh_to_kwh(wh), emission_factor_g_per_kwh)


def gain_percent(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return (before - after) / before * 100.0
