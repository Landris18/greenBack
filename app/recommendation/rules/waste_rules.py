from app.core.enums import ContainerStatus, Difficulty, RuleCode, Severity
from app.recommendation.rules.base import (
    RELIABILITY_NOTE,
    STORAGE_ONLY_NOTE,
    ContainerAnalysis,
    RuleFinding,
    RuleThresholds,
    base_evidence,
    monthly_saving_kwh,
    register,
)

BYTES_PER_MB = 1024**2
BYTES_PER_GB = 1024**3


@register
def idle_container(analysis: ContainerAnalysis, thresholds: RuleThresholds) -> RuleFinding | None:
    if analysis.status is not ContainerStatus.RUNNING:
        return None
    if analysis.window_hours < thresholds.idle_hours or analysis.sample_count < 10:
        return None
    if analysis.cpu_percent_p95 >= thresholds.idle_cpu_percent:
        return None
    if analysis.net_rate_p95 >= thresholds.idle_network_bps:
        return None

    saving_kwh = monthly_saving_kwh(analysis)
    saving_kg = saving_kwh * thresholds.emission_factor_g_per_kwh / 1000.0

    return RuleFinding(
        rule_code=RuleCode.IDLE_CONTAINER,
        severity=Severity.HIGH,
        difficulty=Difficulty.EASY,
        title=f"Conteneur inactif : {analysis.name}",
        description=(
            f"Sur les {analysis.window_hours:.0f} dernières heures, le conteneur est reste actif "
            f"sans activité significative : {analysis.cpu_percent_p95:.2f} % de CPU et "
            f"{analysis.net_rate_p95:.0f} o/s de trafic réseau au 95e percentile. L'arreter "
            "supprime réellement sa part de consommation dynamique."
        ),
        current_value={
            "cpu_percent_p95": round(analysis.cpu_percent_p95, 3),
            "net_rate_bps_p95": round(analysis.net_rate_p95, 1),
            "state": "running",
        },
        suggested_value={"state": "stopped"},
        energy_saving_kwh=round(saving_kwh, 4),
        co2_saving_kg=round(saving_kg, 4),
        saving_is_computed=True,
        saving_note=(
            "Gain calcule : consommation estimée réellement attribuée a ce conteneur sur la "
            "fenêtre observée, extrapolée sur 30 jours."
        ),
        evidence={
            **base_evidence(analysis),
            "observed_energy_wh": round(analysis.energy_wh_total, 4),
            "extrapolation_days": 30,
        },
    )


@register
def oversized_image(analysis: ContainerAnalysis, thresholds: RuleThresholds) -> RuleFinding | None:
    if not analysis.image_size_bytes:
        return None
    if analysis.image_size_bytes < thresholds.image_size_bytes:
        return None

    return RuleFinding(
        rule_code=RuleCode.OVERSIZED_IMAGE,
        severity=Severity.MEDIUM,
        difficulty=Difficulty.MEDIUM,
        title=f"Image Docker volumineuse : {analysis.name}",
        description=(
            f"L'image {analysis.image_ref} pese "
            f"{analysis.image_size_bytes / BYTES_PER_GB:.2f} Go. Un build multi-étapes sur une "
            "base slim ou alpine, sans les dépendances de compilation, réduit fortement cette "
            "taille."
        ),
        current_value={
            "image_ref": analysis.image_ref,
            "image_size_gb": round(analysis.image_size_bytes / BYTES_PER_GB, 2),
        },
        suggested_value={"strategy": "multi-stage build sur une image de base slim"},
        saving_is_computed=False,
        saving_note=STORAGE_ONLY_NOTE,
        evidence=base_evidence(analysis),
    )


@register
def exited_container_present(
    analysis: ContainerAnalysis, thresholds: RuleThresholds
) -> RuleFinding | None:
    if analysis.status is not ContainerStatus.EXITED:
        return None
    if analysis.exited_days is None or analysis.exited_days < thresholds.exited_days:
        return None

    return RuleFinding(
        rule_code=RuleCode.EXITED_CONTAINER_PRESENT,
        severity=Severity.LOW,
        difficulty=Difficulty.EASY,
        title=f"Conteneur arrêté non supprime : {analysis.name}",
        description=(
            f"Le conteneur est arrêté depuis {analysis.exited_days:.0f} jours mais reste présent "
            "sur l'hôte. Il ne consomme plus de CPU mais immobilise du stockage et encombre "
            "l'inventaire."
        ),
        current_value={"status": "exited", "days_since_last_seen": round(analysis.exited_days, 1)},
        suggested_value={"action": "docker rm"},
        saving_is_computed=False,
        saving_note=STORAGE_ONLY_NOTE,
        evidence=base_evidence(analysis),
    )


@register
def restart_loop(analysis: ContainerAnalysis, thresholds: RuleThresholds) -> RuleFinding | None:
    if analysis.restart_count < thresholds.restart_count:
        return None

    return RuleFinding(
        rule_code=RuleCode.RESTART_LOOP,
        severity=Severity.HIGH,
        difficulty=Difficulty.HARD,
        title=f"Redémarrages répétés : {analysis.name}",
        description=(
            f"Le conteneur a redémarré {analysis.restart_count} fois. Chaque redémarrage "
            "consomme des ressources sans rendre de service et signale un défaut de "
            "configuration ou d'application a corriger."
        ),
        current_value={"restart_count": analysis.restart_count},
        suggested_value={"action": "analyser les journaux et corriger la cause des redémarrages"},
        saving_is_computed=False,
        saving_note=RELIABILITY_NOTE,
        evidence=base_evidence(analysis),
    )
