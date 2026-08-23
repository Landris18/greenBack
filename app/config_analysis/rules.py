from dataclasses import dataclass, field

from app.config_analysis.parsers import (
    ParsedCompose,
    ParsedDockerfile,
    apt_without_cleanup,
    installs_build_tooling,
    is_light_image,
)
from app.config_analysis.patch import (
    build_patch,
    find_key_line,
    insert_after,
    remove_service,
    replace_line,
    set_service_key,
)
from app.core.enums import Difficulty, RecommendationSource, RuleCode, Severity
from app.recommendation.rules.base import RuleFinding, RuleThresholds

SLIM_FAMILIES = ("python", "node", "ruby", "openjdk", "eclipse-temurin", "golang", "php")
MB = 1024**2

CONFIG_NON_QUANTIFIABLE = (
    "Gain non quantifiable en kWh à partir des métriques observées : l'économie porte sur la "
    "taille de l'image, le stockage et la durée des déploiements."
)
SIZING_NOTE = (
    "Gain non quantifiable en kWh : ajuster une limite ne réduit pas la consommation d'un service "
    "qui ne l'atteignait jamais. Le gain porte sur la densité d'hébergement et la prévisibilité."
)
SECURITY_NOTE = "Gain non quantifiable en kWh : l'impact porte sur la surface d'attaque."


@dataclass(frozen=True)
class ServiceObservation:
    service_name: str
    container_id: int | None
    cpu_cores_p95: float
    memory_working_set_p95: float
    is_idle: bool
    sample_count: int
    energy_wh_total: float = 0.0
    window_hours: float = 0.0


@dataclass(frozen=True)
class ConfigContext:
    compose: ParsedCompose | None
    dockerfiles: dict[str, ParsedDockerfile] = field(default_factory=dict)
    observations: dict[str, ServiceObservation] = field(default_factory=dict)


def _light_variant(image: str) -> str | None:
    reference = image.split()[0]
    if is_light_image(reference):
        return None
    name, _, tag = reference.partition(":")
    family = name.split("/")[-1].lower()
    if family not in SLIM_FAMILIES:
        return None
    return f"{name}:{tag}-slim" if tag else f"{name}:slim"


def _container_id(context: ConfigContext, service: str) -> int | None:
    observation = context.observations.get(service)
    return observation.container_id if observation else None


def heavy_base_image(context: ConfigContext) -> list[RuleFinding]:
    findings: list[RuleFinding] = []

    for service, dockerfile in context.dockerfiles.items():
        for instruction in dockerfile.base_images:
            variant = _light_variant(instruction.value)
            if variant is None:
                continue

            original_reference = instruction.value.split()[0]
            updated = replace_line(
                dockerfile.content,
                instruction.line_number,
                instruction.raw.replace(original_reference, variant),
            )
            patch = build_patch(dockerfile.content, updated, dockerfile.path, "DOCKERFILE", service)

            findings.append(
                RuleFinding(
                    rule_code=RuleCode.HEAVY_BASE_IMAGE,
                    severity=Severity.MEDIUM,
                    difficulty=Difficulty.EASY,
                    title=f"Image de base non allégée pour {service}",
                    description=(
                        f"Le service utilise {original_reference}. La variante {variant} fournit "
                        "le même interpréteur sans la chaîne de compilation ni les outils de "
                        "développement, ce qui réduit fortement la taille de l'image."
                    ),
                    current_value={"image": original_reference, "file": dockerfile.path},
                    suggested_value={"image": variant},
                    saving_is_computed=False,
                    saving_note=CONFIG_NON_QUANTIFIABLE,
                    evidence={"line": instruction.line_number, "service": service},
                    source=RecommendationSource.CONFIG,
                    patch=patch.as_dict(),
                )
            )
            break

    return findings


def no_multistage_build(context: ConfigContext) -> list[RuleFinding]:
    findings: list[RuleFinding] = []

    for service, dockerfile in context.dockerfiles.items():
        if dockerfile.stage_count > 1:
            continue
        tooling = installs_build_tooling(dockerfile)
        if not tooling:
            continue

        findings.append(
            RuleFinding(
                rule_code=RuleCode.NO_MULTISTAGE_BUILD,
                severity=Severity.MEDIUM,
                difficulty=Difficulty.HARD,
                title=f"Build en une seule étape pour {service}",
                description=(
                    "Le Dockerfile installe une chaîne de compilation puis la conserve dans "
                    "l'image finale. Un build multi-étapes compile dans une première image et ne "
                    "copie que le résultat dans une image d'exécution allégée. La restructuration "
                    "depend de l'application et n'est pas générée automatiquement."
                ),
                current_value={
                    "stages": dockerfile.stage_count,
                    "build_tooling_lines": [item.line_number for item in tooling],
                    "file": dockerfile.path,
                },
                suggested_value={"strategy": "FROM ... AS builder puis FROM ...-slim"},
                saving_is_computed=False,
                saving_note=CONFIG_NON_QUANTIFIABLE,
                evidence={"service": service},
                source=RecommendationSource.CONFIG,
            )
        )

    return findings


def apt_cache_not_cleaned(context: ConfigContext) -> list[RuleFinding]:
    findings: list[RuleFinding] = []

    for service, dockerfile in context.dockerfiles.items():
        offenders = apt_without_cleanup(dockerfile)
        if not offenders:
            continue

        instruction = offenders[0]
        cleaned = f"{instruction.raw.rstrip()} \\\n    && rm -rf /var/lib/apt/lists/*"
        updated = replace_line(dockerfile.content, instruction.line_number, cleaned)
        patch = build_patch(dockerfile.content, updated, dockerfile.path, "DOCKERFILE", service)

        findings.append(
            RuleFinding(
                rule_code=RuleCode.APT_CACHE_NOT_CLEANED,
                severity=Severity.LOW,
                difficulty=Difficulty.EASY,
                title=f"Cache apt conserve dans l'image de {service}",
                description=(
                    "Les listes de paquets téléchargées par apt-get restent dans la couche finale "
                    "et alourdissent l'image sans aucune utilité à l'exécution."
                ),
                current_value={"line": instruction.line_number, "file": dockerfile.path},
                suggested_value={"append": "rm -rf /var/lib/apt/lists/*"},
                saving_is_computed=False,
                saving_note=CONFIG_NON_QUANTIFIABLE,
                evidence={"service": service, "occurrences": len(offenders)},
                source=RecommendationSource.CONFIG,
                patch=patch.as_dict(),
            )
        )

    return findings


def runs_as_root(context: ConfigContext) -> list[RuleFinding]:
    findings: list[RuleFinding] = []

    for service, dockerfile in context.dockerfiles.items():
        if dockerfile.has_user:
            continue

        entrypoints = dockerfile.by_keyword("CMD") + dockerfile.by_keyword("ENTRYPOINT")
        anchor = min((item.line_number for item in entrypoints), default=None)
        patch = None
        if anchor is not None:
            updated = insert_after(
                dockerfile.content,
                anchor - 1,
                [
                    "RUN addgroup --system app && adduser --system --ingroup app app",
                    "USER app",
                ],
            )
            patch = build_patch(
                dockerfile.content, updated, dockerfile.path, "DOCKERFILE", service
            ).as_dict()

        findings.append(
            RuleFinding(
                rule_code=RuleCode.RUNS_AS_ROOT,
                severity=Severity.MEDIUM,
                difficulty=Difficulty.EASY,
                title=f"Conteneur exécuté en root : {service}",
                description=(
                    "Aucune instruction USER n'est déclarée : le processus tourne en root dans le "
                    "conteneur. Déclarer un utilisateur non privilégié réduit la portée d'une "
                    "compromission."
                ),
                current_value={"user": "root", "file": dockerfile.path},
                suggested_value={"user": "app"},
                saving_is_computed=False,
                saving_note=SECURITY_NOTE,
                evidence={"service": service},
                source=RecommendationSource.CONFIG,
                patch=patch,
            )
        )

    return findings


def _suggested_memory_mb(observation: ServiceObservation) -> int:
    return max(64, int(observation.memory_working_set_p95 * 1.5 / MB))


def _suggested_cpus(observation: ServiceObservation) -> float:
    return max(0.1, round(observation.cpu_cores_p95 * 1.5, 2))


def compose_no_limits(context: ConfigContext) -> list[RuleFinding]:
    if context.compose is None:
        return []

    findings: list[RuleFinding] = []
    for name, service in context.compose.services.items():
        if service.cpus is not None or service.memory_limit_bytes is not None:
            continue
        observation = context.observations.get(name)
        if observation is None or observation.sample_count < 5:
            continue

        memory_mb = _suggested_memory_mb(observation)
        cpus = _suggested_cpus(observation)

        updated = set_service_key(context.compose.content, name, "cpus", str(cpus))
        updated = set_service_key(updated, name, "mem_limit", f"{memory_mb}m")
        patch = build_patch(context.compose.content, updated, context.compose.path, "COMPOSE", name)

        findings.append(
            RuleFinding(
                rule_code=RuleCode.COMPOSE_NO_LIMITS,
                severity=Severity.MEDIUM,
                difficulty=Difficulty.EASY,
                title=f"Aucune limite déclarée pour {name}",
                description=(
                    f"Le service peut consommer sans plafond les ressources de l'hôte. Sur la "
                    f"fenêtre observée il utilise au plus {observation.cpu_cores_p95:.2f} cœur et "
                    f"{observation.memory_working_set_p95 / MB:.0f} Mo au 95e percentile."
                ),
                current_value={"cpus": None, "mem_limit": None},
                suggested_value={"cpus": cpus, "mem_limit": f"{memory_mb}m"},
                saving_is_computed=False,
                saving_note=SIZING_NOTE,
                evidence={"service": name, "sample_count": observation.sample_count},
                source=RecommendationSource.CONFIG,
                patch=patch.as_dict(),
            )
        )

    return findings


def compose_limit_too_high(context: ConfigContext, thresholds: RuleThresholds) -> list[RuleFinding]:
    if context.compose is None:
        return []

    findings: list[RuleFinding] = []
    for name, service in context.compose.services.items():
        if not service.memory_limit_bytes:
            continue
        observation = context.observations.get(name)
        if observation is None or observation.sample_count < 5:
            continue

        ratio = observation.memory_working_set_p95 / service.memory_limit_bytes * 100.0
        if ratio >= thresholds.memory_underuse_percent:
            continue

        memory_mb = _suggested_memory_mb(observation)
        updated = set_service_key(context.compose.content, name, "mem_limit", f"{memory_mb}m")
        patch = build_patch(context.compose.content, updated, context.compose.path, "COMPOSE", name)

        findings.append(
            RuleFinding(
                rule_code=RuleCode.COMPOSE_LIMIT_TOO_HIGH,
                severity=Severity.HIGH,
                difficulty=Difficulty.EASY,
                title=f"Limite mémoire surdimensionnée pour {name}",
                description=(
                    f"La limite déclarée est {service.memory_limit_raw} alors que le service "
                    f"n'utilise que {observation.memory_working_set_p95 / MB:.0f} Mo au 95e "
                    f"percentile, soit {ratio:.1f} % de la limite."
                ),
                current_value={"mem_limit": service.memory_limit_raw},
                suggested_value={"mem_limit": f"{memory_mb}m"},
                saving_is_computed=False,
                saving_note=SIZING_NOTE,
                evidence={"service": name, "usage_ratio_percent": round(ratio, 2)},
                source=RecommendationSource.CONFIG,
                patch=patch.as_dict(),
            )
        )

    return findings


def unused_service(context: ConfigContext, thresholds: RuleThresholds) -> list[RuleFinding]:
    if context.compose is None:
        return []

    findings: list[RuleFinding] = []
    for name in context.compose.services:
        observation = context.observations.get(name)
        if observation is None or not observation.is_idle:
            continue

        saving_kwh = 0.0
        if observation.window_hours > 0:
            saving_kwh = observation.energy_wh_total / observation.window_hours * 720.0 / 1000.0
        saving_kg = saving_kwh * thresholds.emission_factor_g_per_kwh / 1000.0

        updated = remove_service(context.compose.content, name)
        patch = build_patch(context.compose.content, updated, context.compose.path, "COMPOSE", name)

        findings.append(
            RuleFinding(
                rule_code=RuleCode.UNUSED_SERVICE,
                severity=Severity.HIGH,
                difficulty=Difficulty.MEDIUM,
                title=f"Service sans activité : {name}",
                description=(
                    "Le service est déclaré et démarré mais n'a montré aucune activité "
                    "significative sur la fenêtre observée. Le retirer du fichier compose supprime "
                    "réellement sa part de consommation dynamique."
                ),
                current_value={"service": name, "state": "déclaré et actif"},
                suggested_value={"service": name, "state": "retire du compose"},
                energy_saving_kwh=round(saving_kwh, 4),
                co2_saving_kg=round(saving_kg, 4),
                saving_is_computed=True,
                saving_note=(
                    "Gain calcule : consommation estimée réellement attribuée a ce service sur la "
                    "fenêtre observée, extrapolée sur 30 jours."
                ),
                evidence={"service": name, "window_hours": round(observation.window_hours, 2)},
                source=RecommendationSource.CONFIG,
                patch=patch.as_dict(),
            )
        )

    return findings


def evaluate_config(context: ConfigContext, thresholds: RuleThresholds) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    findings.extend(heavy_base_image(context))
    findings.extend(no_multistage_build(context))
    findings.extend(apt_cache_not_cleaned(context))
    findings.extend(runs_as_root(context))
    findings.extend(compose_no_limits(context))
    findings.extend(compose_limit_too_high(context, thresholds))
    findings.extend(unused_service(context, thresholds))
    return findings


__all__ = [
    "ConfigContext",
    "ServiceObservation",
    "evaluate_config",
    "find_key_line",
]
