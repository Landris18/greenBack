import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.container.models import Container
from app.core.deps import CurrentUser, RequireTech, SessionDep
from app.core.enums import ConfigFileSource, ContainerStatus, RecommendationStatus, Severity
from app.core.exceptions import NotFoundError
from app.energy.selectors import energy_totals
from app.metric.models import LiveSample
from app.project.models import Project, ProjectConfigFile
from app.project.schemas import (
    ConfigFileRead,
    ConfigFileUpload,
    ProjectConfigStatus,
    ProjectRead,
    ProjectSummary,
    ProjectUpdate,
)
from app.recommendation.models import Recommendation
from app.recommendation.schemas import ScanResult
from app.recommendation.service import scan_project
from app.setting.service import get_active_config

router = APIRouter(prefix="/projects", tags=["Project"])

LIVE_WINDOW_SECONDS = 10


async def _get_project(session: SessionDep, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Projet introuvable.")
    return project


async def _summarise(session, project: Project, hours: int) -> ProjectSummary:
    counts_statement = select(
        func.count(Container.id),
        func.count(Container.id).filter(Container.status == ContainerStatus.RUNNING),
    ).where(
        Container.project_id == project.id,
        Container.status != ContainerStatus.ABSENT,
    )
    container_count, running_count = (await session.execute(counts_statement)).one()

    since = datetime.now(UTC) - timedelta(seconds=LIVE_WINDOW_SECONDS)
    latest_statement = (
        select(
            func.max(LiveSample.collected_at).label("last_at"),
            func.sum(LiveSample.power_watts).label("power"),
            func.sum(LiveSample.cpu_percent_of_host).label("cpu"),
            func.sum(LiveSample.memory_working_set_bytes).label("memory"),
        )
        .where(LiveSample.project_id == project.id, LiveSample.collected_at >= since)
        .group_by(LiveSample.collected_at)
        .order_by(func.max(LiveSample.collected_at).desc())
        .limit(1)
    )
    live = (await session.execute(latest_statement)).first()

    recommendation_statement = select(
        func.count(Recommendation.id),
        func.count(Recommendation.id).filter(
            Recommendation.severity.in_([Severity.CRITICAL, Severity.HIGH])
        ),
    ).where(
        Recommendation.project_id == project.id,
        Recommendation.status == RecommendationStatus.OPEN,
    )
    recommendation_count, critical_count = (await session.execute(recommendation_statement)).one()

    end = datetime.now(UTC)
    totals = await energy_totals(session, end - timedelta(hours=hours), end, project_id=project.id)

    return ProjectSummary(
        project=ProjectRead.model_validate(project),
        container_count=int(container_count or 0),
        running_count=int(running_count or 0),
        cpu_percent_of_host=round(float(live.cpu or 0.0), 4) if live else 0.0,
        memory_bytes=int(live.memory or 0) if live else 0,
        power_watts=round(float(live.power or 0.0), 6) if live else 0.0,
        energy_kwh=totals.energy_kwh,
        co2_kg=totals.co2_kg,
        recommendation_count=int(recommendation_count or 0),
        critical_count=int(critical_count or 0),
        has_live_data=bool(live and live.last_at),
    )


@router.get("", response_model=list[ProjectSummary], summary="Projets détectés automatiquement")
async def list_projects(
    session: SessionDep,
    current_user: CurrentUser,
    hours: int = Query(24, ge=1, le=8760),
) -> list[ProjectSummary]:
    projects = (await session.execute(select(Project).order_by(Project.name))).scalars().all()
    return [await _summarise(session, project, hours) for project in projects]


@router.get("/{project_id}", response_model=ProjectSummary, summary="Détail d'un projet")
async def get_project(
    project_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    hours: int = Query(24, ge=1, le=8760),
) -> ProjectSummary:
    project = await _get_project(session, project_id)
    return await _summarise(session, project, hours)


@router.patch("/{project_id}", response_model=ProjectRead, summary="Modifier un projet")
async def update_project(
    project_id: int, payload: ProjectUpdate, session: SessionDep, current_user: RequireTech
) -> ProjectRead:
    project = await _get_project(session, project_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await session.commit()
    await session.refresh(project)
    return ProjectRead.model_validate(project)


@router.post(
    "/{project_id}/register",
    response_model=ProjectRead,
    summary="Suivre ce projet et lire sa configuration",
)
async def register_project(
    project_id: int, session: SessionDep, current_user: RequireTech
) -> ProjectRead:
    project = await _get_project(session, project_id)
    project.is_registered = True
    project.config_error = None
    await session.commit()
    await session.refresh(project)
    return ProjectRead.model_validate(project)


@router.get(
    "/{project_id}/config",
    response_model=ProjectConfigStatus,
    summary="Fichiers de configuration connus",
)
async def get_project_config(
    project_id: int, session: SessionDep, current_user: CurrentUser
) -> ProjectConfigStatus:
    project = await _get_project(session, project_id)
    files = (
        (
            await session.execute(
                select(ProjectConfigFile)
                .where(ProjectConfigFile.project_id == project_id)
                .order_by(ProjectConfigFile.kind, ProjectConfigFile.path)
            )
        )
        .scalars()
        .all()
    )

    return ProjectConfigStatus(
        project_id=project.id,
        is_registered=project.is_registered,
        compose_path=project.compose_path,
        config_read_at=project.config_read_at,
        config_error=project.config_error,
        files=[ConfigFileRead.model_validate(item) for item in files],
    )


@router.post(
    "/{project_id}/config",
    response_model=ConfigFileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Déposer manuellement un fichier de configuration",
)
async def upload_project_config(
    project_id: int,
    payload: ConfigFileUpload,
    session: SessionDep,
    current_user: RequireTech,
) -> ConfigFileRead:
    project = await _get_project(session, project_id)
    now = datetime.now(UTC)

    statement = select(ProjectConfigFile).where(
        ProjectConfigFile.project_id == project.id, ProjectConfigFile.path == payload.path
    )
    record = (await session.execute(statement)).scalar_one_or_none()
    if record is None:
        record = ProjectConfigFile(project_id=project.id, path=payload.path, read_at=now)
        session.add(record)

    record.kind = payload.kind
    record.service_name = payload.service_name
    record.content = payload.content
    record.content_hash = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    record.source = ConfigFileSource.UPLOAD
    record.read_at = now

    project.config_read_at = now
    project.config_error = None
    project.is_registered = True

    await session.commit()
    await session.refresh(record)
    return ConfigFileRead.model_validate(record)


@router.delete(
    "/{project_id}/config/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer un fichier de configuration",
)
async def delete_project_config(
    project_id: int, file_id: int, session: SessionDep, current_user: RequireTech
) -> None:
    record = await session.get(ProjectConfigFile, file_id)
    if record is None or record.project_id != project_id:
        raise NotFoundError("Fichier introuvable.")
    await session.delete(record)
    await session.commit()


@router.post(
    "/{project_id}/analyze",
    response_model=ScanResult,
    summary="Analyser l'exécution et la configuration",
)
async def analyze_project(
    project_id: int, session: SessionDep, current_user: RequireTech
) -> ScanResult:
    project = await _get_project(session, project_id)
    config = await get_active_config(session)
    await session.commit()
    return await scan_project(session, project, config)
