from app.core.enums import ContainerStatus, Difficulty, RuleCode, Severity
from app.recommendation.rules.base import (
    NON_QUANTIFIABLE_NOTE,
    ContainerAnalysis,
    RuleFinding,
    RuleThresholds,
    base_evidence,
    register,
)

BYTES_PER_MB = 1024**2


@register
def cpu_overprovisioned(
    analysis: ContainerAnalysis, thresholds: RuleThresholds
) -> RuleFinding | None:
    if analysis.status is not ContainerStatus.RUNNING:
        return None
    if not analysis.cpu_limit_cores or analysis.sample_count < 10:
        return None

    usage_ratio = analysis.cpu_percent_of_limit_p95 or (
        analysis.cpu_cores_p95 / analysis.cpu_limit_cores * 100.0
    )
    if usage_ratio >= thresholds.cpu_underuse_percent:
        return None

    suggested = max(0.1, round(analysis.cpu_cores_p95 * 1.3, 2))
    return RuleFinding(
        rule_code=RuleCode.CPU_OVERPROVISIONED,
        severity=Severity.HIGH,
        difficulty=Difficulty.EASY,
        title=f"CPU surdimensionné sur {analysis.name}",
        description=(
            f"Le conteneur reserve {analysis.cpu_limit_cores} cœur(s) mais n'en utilise que "
            f"{analysis.cpu_cores_p95:.2f} au 95e percentile, soit {usage_ratio:.1f} % de sa "
            "limite. Abaisser la limite libère de la capacité pour d'autres charges."
        ),
        current_value={
            "cpu_limit_cores": analysis.cpu_limit_cores,
            "cpu_p95_cores": round(analysis.cpu_cores_p95, 3),
        },
        suggested_value={"cpu_limit_cores": suggested},
        saving_is_computed=False,
        saving_note=NON_QUANTIFIABLE_NOTE,
        evidence={**base_evidence(analysis), "usage_ratio_percent": round(usage_ratio, 2)},
    )


@register
def memory_overprovisioned(
    analysis: ContainerAnalysis, thresholds: RuleThresholds
) -> RuleFinding | None:
    if analysis.status is not ContainerStatus.RUNNING:
        return None
    if not analysis.memory_limit_bytes or analysis.sample_count < 10:
        return None

    usage_ratio = analysis.memory_percent_of_limit_p95 or (
        analysis.memory_working_set_p95 / analysis.memory_limit_bytes * 100.0
    )
    if usage_ratio >= thresholds.memory_underuse_percent:
        return None

    suggested_mb = max(64, int(analysis.memory_working_set_p95 * 1.3 / BYTES_PER_MB))
    return RuleFinding(
        rule_code=RuleCode.MEMORY_OVERPROVISIONED,
        severity=Severity.HIGH,
        difficulty=Difficulty.EASY,
        title=f"Mémoire surdimensionnée sur {analysis.name}",
        description=(
            f"La limite mémoire est de {analysis.memory_limit_bytes / BYTES_PER_MB:.0f} Mo alors "
            f"que le conteneur n'en utilise que "
            f"{analysis.memory_working_set_p95 / BYTES_PER_MB:.0f} Mo au 95e percentile "
            f"({usage_ratio:.1f} % de la limite)."
        ),
        current_value={
            "memory_limit_mb": round(analysis.memory_limit_bytes / BYTES_PER_MB),
            "memory_p95_mb": round(analysis.memory_working_set_p95 / BYTES_PER_MB),
        },
        suggested_value={"memory_limit_mb": suggested_mb},
        saving_is_computed=False,
        saving_note=NON_QUANTIFIABLE_NOTE,
        evidence={**base_evidence(analysis), "usage_ratio_percent": round(usage_ratio, 2)},
    )


@register
def no_limits_set(analysis: ContainerAnalysis, thresholds: RuleThresholds) -> RuleFinding | None:
    if analysis.status is not ContainerStatus.RUNNING:
        return None
    if analysis.cpu_limit_cores or analysis.memory_limit_bytes:
        return None

    return RuleFinding(
        rule_code=RuleCode.NO_LIMITS_SET,
        severity=Severity.MEDIUM,
        difficulty=Difficulty.EASY,
        title=f"Aucune limite de ressource sur {analysis.name}",
        description=(
            "Le conteneur peut consommer sans plafond le CPU et la mémoire de l'hôte. Définir "
            "des limites rend la consommation prévisible et évite qu'un incident sur ce service "
            "dégrade toute l'infrastructure."
        ),
        current_value={"cpu_limit_cores": None, "memory_limit_bytes": None},
        suggested_value={
            "cpu_limit_cores": max(0.1, round(analysis.cpu_cores_p95 * 1.5, 2)),
            "memory_limit_mb": max(64, int(analysis.memory_working_set_p95 * 1.5 / BYTES_PER_MB)),
        },
        saving_is_computed=False,
        saving_note=NON_QUANTIFIABLE_NOTE,
        evidence=base_evidence(analysis),
    )
