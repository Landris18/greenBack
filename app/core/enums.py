from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    TECH = "TECH"


class ResourceStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class PowerSource(StrEnum):
    BMC = "BMC"
    BATTERY = "BATTERY"
    HWMON = "HWMON"
    RAPL = "RAPL"
    MODEL = "MODEL"


MEASURED_POWER_SOURCES: frozenset[PowerSource] = frozenset(
    {PowerSource.BMC, PowerSource.BATTERY, PowerSource.HWMON, PowerSource.RAPL}
)


class IdleAttributionPolicy(StrEnum):
    OVERHEAD = "OVERHEAD"
    PRORATA = "PRORATA"


class ContainerStatus(StrEnum):
    RUNNING = "running"
    EXITED = "exited"
    PAUSED = "paused"
    RESTARTING = "restarting"
    CREATED = "created"
    DEAD = "dead"
    REMOVING = "removing"
    UNKNOWN = "unknown"
    ABSENT = "absent"


class RuleCode(StrEnum):
    CPU_OVERPROVISIONED = "CPU_OVERPROVISIONED"
    MEMORY_OVERPROVISIONED = "MEMORY_OVERPROVISIONED"
    NO_LIMITS_SET = "NO_LIMITS_SET"
    IDLE_CONTAINER = "IDLE_CONTAINER"
    OVERSIZED_IMAGE = "OVERSIZED_IMAGE"
    EXITED_CONTAINER_PRESENT = "EXITED_CONTAINER_PRESENT"
    RESTART_LOOP = "RESTART_LOOP"
    CPU_HIGH = "CPU_HIGH"
    MEMORY_HIGH = "MEMORY_HIGH"
    HEAVY_BASE_IMAGE = "HEAVY_BASE_IMAGE"
    NO_MULTISTAGE_BUILD = "NO_MULTISTAGE_BUILD"
    APT_CACHE_NOT_CLEANED = "APT_CACHE_NOT_CLEANED"
    RUNS_AS_ROOT = "RUNS_AS_ROOT"
    COMPOSE_NO_LIMITS = "COMPOSE_NO_LIMITS"
    COMPOSE_LIMIT_TOO_HIGH = "COMPOSE_LIMIT_TOO_HIGH"
    UNUSED_SERVICE = "UNUSED_SERVICE"


class RecommendationSource(StrEnum):
    RUNTIME = "RUNTIME"
    CONFIG = "CONFIG"


class ConfigFileKind(StrEnum):
    COMPOSE = "COMPOSE"
    DOCKERFILE = "DOCKERFILE"


class ConfigFileSource(StrEnum):
    AUTO = "AUTO"
    UPLOAD = "UPLOAD"


class LiveMetric(StrEnum):
    ENERGY_CUMULATIVE = "energy_cumulative"
    CO2_CUMULATIVE = "co2_cumulative"
    POWER = "power"
    CPU = "cpu"
    MEMORY = "memory"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Difficulty(StrEnum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class RecommendationStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    APPLIED = "APPLIED"
    DISMISSED = "DISMISSED"


class Granularity(StrEnum):
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


class MetricKind(StrEnum):
    CPU = "cpu"
    MEMORY = "memory"
    NETWORK = "network"
    STORAGE = "storage"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}
