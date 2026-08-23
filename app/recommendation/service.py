from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_analysis import parse_compose, parse_dockerfile
from app.config_analysis.rules import ConfigContext, evaluate_config
from app.container.models import Container
from app.core.enums import ConfigFileKind, RecommendationStatus
from app.project.models import Project, ProjectConfigFile
from app.recommendation.models import Recommendation
from app.recommendation.rules import RuleFinding, RuleThresholds, evaluate
from app.recommendation.schemas import ScanResult
from app.recommendation.selectors import build_analyses, build_observations
from app.setting.models import GreenConfig

SCAN_NOTE = (
    "Seules les recommandations portant un gain calcule sont additionnées. Les autres décrivent "
    "un gain réel mais non exprimable en kWh à partir des métriques observées."
)


def thresholds_from_config(config: GreenConfig) -> RuleThresholds:
    return RuleThresholds(
        cpu_high_percent=config.threshold_cpu_high_percent,
        memory_high_percent=config.threshold_memory_high_percent,
        cpu_underuse_percent=config.threshold_cpu_underuse_percent,
        memory_underuse_percent=config.threshold_memory_underuse_percent,
        idle_cpu_percent=config.threshold_idle_cpu_percent,
        idle_network_bps=config.threshold_idle_network_bps,
        idle_hours=config.threshold_idle_hours,
        image_size_bytes=config.threshold_image_size_bytes,
        exited_days=config.threshold_exited_days,
        restart_count=config.threshold_restart_count,
        emission_factor_g_per_kwh=config.emission_factor_g_per_kwh,
    )


async def build_config_context(
    session: AsyncSession, project: Project, observations: dict
) -> ConfigContext:
    files = (
        (
            await session.execute(
                select(ProjectConfigFile).where(ProjectConfigFile.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )

    compose = None
    dockerfiles = {}
    for record in files:
        if record.kind is ConfigFileKind.COMPOSE:
            compose = parse_compose(record.content, record.path)
        elif record.service_name:
            dockerfiles[record.service_name] = parse_dockerfile(record.content, record.path)

    return ConfigContext(compose=compose, dockerfiles=dockerfiles, observations=observations)


def _apply(recommendation: Recommendation, finding: RuleFinding, detected_at: datetime) -> None:
    recommendation.severity = finding.severity
    recommendation.difficulty = finding.difficulty
    recommendation.title = finding.title
    recommendation.description = finding.description
    recommendation.current_value = finding.current_value
    recommendation.suggested_value = finding.suggested_value
    recommendation.estimated_energy_saving_kwh = finding.energy_saving_kwh
    recommendation.estimated_co2_saving_kg = finding.co2_saving_kg
    recommendation.saving_is_computed = finding.saving_is_computed
    recommendation.saving_note = finding.saving_note
    recommendation.evidence = finding.evidence
    recommendation.source = finding.source
    recommendation.patch = finding.patch
    recommendation.detected_at = detected_at


def _container_for(finding: RuleFinding, containers_by_service: dict) -> int | None:
    service = finding.evidence.get("service")
    if service and service in containers_by_service:
        return containers_by_service[service]
    return None


async def scan_project(session: AsyncSession, project: Project, config: GreenConfig) -> ScanResult:
    detected_at = datetime.now(UTC)
    thresholds = thresholds_from_config(config)

    containers = (
        (await session.execute(select(Container).where(Container.project_id == project.id)))
        .scalars()
        .all()
    )
    analyses = await build_analyses(session, project.id, config.analysis_window_days)
    observations = build_observations(list(containers), analyses, thresholds)

    findings: list[tuple[int | None, RuleFinding]] = []
    for analysis in analyses:
        for finding in evaluate(analysis, thresholds):
            findings.append((analysis.container_id, finding))

    containers_by_service = {
        (container.service_name or container.name): container.id for container in containers
    }
    context = await build_config_context(session, project, observations)
    for finding in evaluate_config(context, thresholds):
        findings.append((_container_for(finding, containers_by_service), finding))

    # Toutes les lignes du projet, quel que soit leur statut : une recommandation que
    # l'utilisateur a deja ACKNOWLEDGED/APPLIED/DISMISSED doit etre retrouvee et mise a
    # jour en place si le meme probleme est redetecte, jamais dupliquee en une nouvelle
    # ligne OPEN (_apply() ne touche pas .status, donc le choix de l'utilisateur est
    # preserve).
    existing_rows = (
        (
            await session.execute(
                select(Recommendation).where(Recommendation.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    existing = {(row.container_id, row.rule_code): row for row in existing_rows}

    created = 0
    updated = 0
    seen: set[tuple[int | None, str]] = set()

    for container_id, finding in findings:
        key = (container_id, finding.rule_code)
        if key in seen:
            continue
        seen.add(key)

        current = existing.get(key)
        if current is None:
            current = Recommendation(
                project_id=project.id,
                container_id=container_id,
                rule_code=finding.rule_code,
                status=RecommendationStatus.OPEN,
            )
            session.add(current)
            created += 1
        else:
            updated += 1
        _apply(current, finding, detected_at)

    # Ne bascule automatiquement en APPLIED que les lignes encore en cours de traitement
    # (OPEN/ACKNOWLEDGED) dont le probleme a disparu. Une ligne deja APPLIED ou DISMISSED
    # par l'utilisateur n'est jamais touchee ici : "le probleme n'est plus detecte" ne
    # doit pas ecraser un choix explicite deja fait (en particulier DISMISSED, qui
    # signifie que l'utilisateur a juge la recommandation non pertinente, pas resolue).
    resolved = 0
    for key, row in existing.items():
        if key in seen:
            continue
        if row.status in (RecommendationStatus.OPEN, RecommendationStatus.ACKNOWLEDGED):
            row.status = RecommendationStatus.APPLIED
            resolved += 1

    await session.commit()

    totals_statement = select(
        func.coalesce(func.sum(Recommendation.estimated_energy_saving_kwh), 0.0),
        func.coalesce(func.sum(Recommendation.estimated_co2_saving_kg), 0.0),
    ).where(
        Recommendation.project_id == project.id,
        Recommendation.status == RecommendationStatus.OPEN,
        Recommendation.saving_is_computed.is_(True),
    )
    saving_kwh, saving_kg = (await session.execute(totals_statement)).one()

    open_total = int(
        (
            await session.execute(
                select(func.count(Recommendation.id)).where(
                    Recommendation.project_id == project.id,
                    Recommendation.status == RecommendationStatus.OPEN,
                )
            )
        ).scalar_one()
    )

    return ScanResult(
        project_id=project.id,
        analysed_containers=len(analyses),
        analysed_services=len(context.compose.services) if context.compose else 0,
        created=created,
        updated=updated,
        resolved=resolved,
        open_total=open_total,
        computed_saving_kwh=round(float(saving_kwh), 4),
        computed_saving_kg_co2=round(float(saving_kg), 4),
        saving_note=SCAN_NOTE,
    )
