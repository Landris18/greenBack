import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.aggregator import ContainerContext
from app.collector.docker_source import DockerSource, DockerUnavailableError
from app.collector.snapshot import ContainerSnapshot
from app.container.models import Container
from app.core.enums import ContainerStatus, ResourceStatus
from app.host.models import Host
from app.metric.models import LiveSample
from app.project.models import UNGROUPED_PROJECT_NAME, Project

logger = logging.getLogger("greensi.collector")

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
COMPOSE_CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
COMPOSE_WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"


def project_name_for(snapshot: ContainerSnapshot) -> str:
    return snapshot.labels.get(COMPOSE_PROJECT_LABEL) or UNGROUPED_PROJECT_NAME


def compose_path_for(snapshot: ContainerSnapshot) -> str | None:
    raw = snapshot.labels.get(COMPOSE_CONFIG_FILES_LABEL)
    if not raw:
        return None
    return raw.split(",")[0].strip() or None


def to_container_status(raw: str) -> ContainerStatus:
    try:
        return ContainerStatus(raw)
    except ValueError:
        return ContainerStatus.UNKNOWN


async def upsert_project(
    session: AsyncSession, host: Host, snapshot: ContainerSnapshot, now: datetime
) -> Project:
    name = project_name_for(snapshot)
    statement = select(Project).where(Project.host_id == host.id, Project.name == name)
    project = (await session.execute(statement)).scalar_one_or_none()

    if project is None:
        project = Project(
            host_id=host.id,
            name=name,
            first_seen_at=now,
            last_seen_at=now,
            status=ResourceStatus.ONLINE,
        )
        session.add(project)
        logger.info("Nouveau projet détecté : %s", name)

    project.last_seen_at = now
    project.last_sync_at = now
    project.status = ResourceStatus.ONLINE

    compose_path = compose_path_for(snapshot)
    if compose_path and project.compose_path != compose_path:
        project.compose_path = compose_path
    working_dir = snapshot.labels.get(COMPOSE_WORKING_DIR_LABEL)
    if working_dir and project.working_dir != working_dir:
        project.working_dir = working_dir

    await session.flush()
    return project


async def upsert_container(
    session: AsyncSession, project: Project, snapshot: ContainerSnapshot, now: datetime
) -> Container:
    statement = select(Container).where(
        Container.project_id == project.id, Container.name == snapshot.name
    )
    container = (await session.execute(statement)).scalar_one_or_none()

    if container is None:
        container = Container(
            project_id=project.id,
            name=snapshot.name,
            docker_id=snapshot.docker_id,
            image_ref=snapshot.image_ref,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(container)

    container.docker_id = snapshot.docker_id
    container.service_name = snapshot.labels.get(COMPOSE_SERVICE_LABEL)
    container.image_ref = snapshot.image_ref
    container.image_id = snapshot.image_id
    container.image_size_bytes = snapshot.image_size_bytes
    container.cpu_limit_cores = snapshot.cpu_limit_cores
    container.memory_limit_bytes = snapshot.memory_limit_bytes
    container.status = to_container_status(snapshot.status)
    container.restart_count = snapshot.restart_count
    container.started_at = snapshot.started_at
    container.labels = snapshot.labels
    container.last_seen_at = now

    await session.flush()
    return container


async def mark_absent_containers(
    session: AsyncSession, host: Host, seen_docker_ids: set[str]
) -> int:
    statement = (
        update(Container)
        .where(
            Container.project_id.in_(select(Project.id).where(Project.host_id == host.id)),
            Container.status != ContainerStatus.ABSENT,
        )
        .values(status=ContainerStatus.ABSENT)
    )
    if seen_docker_ids:
        statement = statement.where(Container.docker_id.notin_(seen_docker_ids))

    result = await session.execute(statement.execution_options(synchronize_session=False))
    return result.rowcount or 0


async def discover(
    session: AsyncSession, host: Host, source: DockerSource
) -> dict[str, ContainerContext]:
    now = datetime.now(UTC)

    try:
        info = await source.info()
        snapshots = await source.inventory(info.cpu_cores or host.cpu_cores)
    except DockerUnavailableError as error:
        host.status = ResourceStatus.ERROR
        host.last_error = str(error)
        await session.commit()
        logger.error("Hote %s injoignable : %s", host.name, error)
        return {}

    host.cpu_cores = info.cpu_cores or host.cpu_cores
    host.total_memory_bytes = info.total_memory_bytes or host.total_memory_bytes
    host.os_info = info.os_info or host.os_info
    host.status = ResourceStatus.ONLINE
    host.last_error = None
    host.last_seen_at = now

    contexts: dict[str, ContainerContext] = {}
    for snapshot in snapshots:
        project = await upsert_project(session, host, snapshot, now)
        container = await upsert_container(session, project, snapshot, now)
        contexts[snapshot.docker_id] = ContainerContext(
            container_id=container.id,
            project_id=project.id,
            docker_id=snapshot.docker_id,
            name=snapshot.name,
            cpu_limit_cores=snapshot.cpu_limit_cores,
            memory_limit_bytes=snapshot.memory_limit_bytes,
            status=to_container_status(snapshot.status),
            started_at=snapshot.started_at,
        )

    disparus = await mark_absent_containers(session, host, set(contexts))
    if disparus:
        logger.info("%d'conteneur(s) disparu(s) de Docker, marqué(s) absent(s).", disparus)

    await session.commit()
    return contexts


def running_docker_ids(contexts: dict[str, ContainerContext]) -> set[str]:
    return {
        docker_id
        for docker_id, context in contexts.items()
        if context.status is ContainerStatus.RUNNING
    }


async def purge_live_samples(session: AsyncSession, retention_minutes: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=max(1, retention_minutes))
    result = await session.execute(delete(LiveSample).where(LiveSample.collected_at < cutoff))
    await session.commit()
    return result.rowcount or 0
