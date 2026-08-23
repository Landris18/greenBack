from app.core.enums import ContainerStatus, Difficulty, RuleCode, Severity
from app.recommendation.rules.base import (
    ContainerAnalysis,
    RuleFinding,
    RuleThresholds,
    base_evidence,
    register,
)

SATURATION_NOTE = (
    "Gain non quantifiable en kWh : il ne s'agit pas d'un gaspillage mais d'un risque. "
    "Un conteneur au plafond de sa limite subit un étranglement CPU ou un arrêt par le noyau."
)


@register
def cpu_high(analysis: ContainerAnalysis, thresholds: RuleThresholds) -> RuleFinding | None:
    if analysis.status is not ContainerStatus.RUNNING:
        return None
    if analysis.cpu_percent_of_limit_p95 is None or analysis.sample_count < 10:
        return None
    if analysis.cpu_percent_of_limit_p95 < thresholds.cpu_high_percent:
        return None

    suggested = round((analysis.cpu_limit_cores or 0) * 1.5, 2)
    return RuleFinding(
        rule_code=RuleCode.CPU_HIGH,
        severity=Severity.CRITICAL,
        difficulty=Difficulty.EASY,
        title=f"Saturation CPU sur {analysis.name}",
        description=(
            f"Le conteneur atteint {analysis.cpu_percent_of_limit_p95:.1f} % de sa limite CPU au "
            f"95e percentile ({analysis.cpu_limit_cores} cœur alloue). Au-delà, le noyau "
            "étranglé le processus et les temps de réponse se dégradent."
        ),
        current_value={
            "cpu_limit_cores": analysis.cpu_limit_cores,
            "cpu_percent_of_limit_p95": round(analysis.cpu_percent_of_limit_p95, 2),
        },
        suggested_value={"cpu_limit_cores": suggested},
        saving_is_computed=False,
        saving_note=SATURATION_NOTE,
        evidence=base_evidence(analysis),
    )


@register
def memory_high(analysis: ContainerAnalysis, thresholds: RuleThresholds) -> RuleFinding | None:
    if analysis.status is not ContainerStatus.RUNNING:
        return None
    if analysis.memory_percent_of_limit_p95 is None or analysis.sample_count < 10:
        return None
    if analysis.memory_percent_of_limit_p95 < thresholds.memory_high_percent:
        return None

    limit_mb = (analysis.memory_limit_bytes or 0) / (1024**2)
    return RuleFinding(
        rule_code=RuleCode.MEMORY_HIGH,
        severity=Severity.CRITICAL,
        difficulty=Difficulty.EASY,
        title=f"Saturation mémoire sur {analysis.name}",
        description=(
            f"Le conteneur occupe {analysis.memory_percent_of_limit_p95:.1f} % de sa limite "
            f"mémoire au 95e percentile ({limit_mb:.0f} Mo alloués). Au-delà de la limite, le "
            "conteneur est arrêté par le noyau."
        ),
        current_value={
            "memory_limit_mb": round(limit_mb),
            "memory_percent_of_limit_p95": round(analysis.memory_percent_of_limit_p95, 2),
        },
        suggested_value={"memory_limit_mb": round(limit_mb * 1.5)},
        saving_is_computed=False,
        saving_note=SATURATION_NOTE,
        evidence=base_evidence(analysis),
    )
