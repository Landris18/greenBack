from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.enums import ContainerStatus, Difficulty, RecommendationSource, RuleCode, Severity

NON_QUANTIFIABLE_NOTE = (
    "Gain non quantifiable en kWh : réduire une limite de ressource ne diminue pas la "
    "consommation d'un conteneur qui n'atteignait jamais cette limite. Le gain porte sur la "
    "densité d'hébergement et la maitrise de la capacité."
)
STORAGE_ONLY_NOTE = (
    "Gain non quantifiable en kWh à l'exécution : l'économie porte sur le stockage, la bande "
    "passante de transfert et la durée des déploiements."
)
RELIABILITY_NOTE = (
    "Gain non quantifiable en kWh : l'impact porte sur la fiabilité du service et le gaspillage "
    "de cycles CPU liés aux redémarrages répétés."
)


@dataclass(frozen=True)
class RuleThresholds:
    cpu_high_percent: float
    memory_high_percent: float
    cpu_underuse_percent: float
    memory_underuse_percent: float
    idle_cpu_percent: float
    idle_network_bps: float
    idle_hours: int
    image_size_bytes: int
    exited_days: int
    restart_count: int
    emission_factor_g_per_kwh: float


@dataclass(frozen=True)
class ContainerAnalysis:
    container_id: int
    name: str
    image_ref: str
    image_size_bytes: int | None
    status: ContainerStatus
    restart_count: int
    cpu_limit_cores: float | None
    memory_limit_bytes: int | None
    cpu_cores_p95: float
    cpu_percent_p95: float
    memory_working_set_p95: float
    cpu_percent_of_limit_p95: float | None
    memory_percent_of_limit_p95: float | None
    net_rate_p95: float
    energy_wh_total: float
    window_hours: float
    sample_count: int
    last_seen_at: datetime
    exited_days: float | None


@dataclass(frozen=True)
class RuleFinding:
    rule_code: RuleCode
    severity: Severity
    difficulty: Difficulty
    title: str
    description: str
    current_value: dict[str, Any] = field(default_factory=dict)
    suggested_value: dict[str, Any] = field(default_factory=dict)
    energy_saving_kwh: float | None = None
    co2_saving_kg: float | None = None
    saving_is_computed: bool = False
    saving_note: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    source: RecommendationSource = RecommendationSource.RUNTIME
    patch: dict[str, Any] | None = None


Rule = Callable[[ContainerAnalysis, RuleThresholds], RuleFinding | None]

RULES: list[Rule] = []


def register(rule: Rule) -> Rule:
    RULES.append(rule)
    return rule


def base_evidence(analysis: ContainerAnalysis) -> dict[str, Any]:
    return {
        "window_hours": round(analysis.window_hours, 2),
        "sample_count": analysis.sample_count,
        "container_name": analysis.name,
    }


def monthly_saving_kwh(analysis: ContainerAnalysis) -> float:
    if analysis.window_hours <= 0:
        return 0.0
    hourly_wh = analysis.energy_wh_total / analysis.window_hours
    return hourly_wh * 720.0 / 1000.0
