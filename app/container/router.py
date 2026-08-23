from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.container.models import Container
from app.container.schemas import ContainerDetail, ContainerLive, ContainerRead
from app.core.deps import CurrentUser, SessionDep
from app.core.enums import ContainerStatus, MetricKind
from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PaginationParams, paginate, pagination_params
from app.energy.selectors import energy_by_container_ids
from app.metric.models import ContainerMetricSample
from app.metric.schemas import MetricSeries
from app.metric.selectors import container_series, latest_samples_by_container
from app.project.models import Project
from app.utils.time_window import TimeWindowDep

router = APIRouter(prefix="/containers", tags=["Container"])

PaginationDep = Annotated[PaginationParams, Depends(pagination_params)]

SERIES_DEFINITIONS = {
    MetricKind.CPU: (
        ContainerMetricSample.cpu_percent,
        ContainerMetricSample.cpu_cores_used,
        "%",
        "CPU",
        "Cœurs utilises",
    ),
    MetricKind.MEMORY: (
        ContainerMetricSample.memory_working_set_bytes,
        None,
        "octets",
        "Mémoire",
        None,
    ),
    MetricKind.NETWORK: (
        ContainerMetricSample.net_rx_rate,
        ContainerMetricSample.net_tx_rate,
        "o/s",
        "Réseau entrant",
        "Réseau sortant",
    ),
    MetricKind.STORAGE: (
        ContainerMetricSample.blk_read_rate,
        ContainerMetricSample.blk_write_rate,
        "o/s",
        "Lecture disque",
        "Écriture disque",
    ),
}


def _to_live(container: Container, sample, energy: tuple[float, float]) -> ContainerLive:
    base = ContainerRead.model_validate(container).model_dump()
    memory_percent = None
    if container.memory_limit_bytes and sample is not None:
        memory_percent = sample.memory_working_set_bytes / container.memory_limit_bytes * 100.0

    return ContainerLive(
        **base,
        cpu_percent=round(sample.cpu_percent, 3) if sample else 0.0,
        cpu_cores_used=round(sample.cpu_cores_used, 4) if sample else 0.0,
        memory_working_set_bytes=sample.memory_working_set_bytes if sample else 0,
        memory_percent=round(memory_percent, 2) if memory_percent is not None else None,
        cpu_percent_of_limit=(
            round(sample.cpu_percent_of_limit, 3)
            if sample and sample.cpu_percent_of_limit is not None
            else None
        ),
        memory_percent_of_limit=(
            round(sample.memory_percent_of_limit, 2)
            if sample and sample.memory_percent_of_limit is not None
            else None
        ),
        net_rate_bps=round(sample.net_rx_rate + sample.net_tx_rate, 2) if sample else 0.0,
        io_rate_bps=round(sample.blk_read_rate + sample.blk_write_rate, 2) if sample else 0.0,
        uptime_seconds=sample.uptime_seconds if sample else 0.0,
        energy_kwh=energy[0],
        co2_kg=energy[1],
    )


@router.get("", response_model=Page[ContainerLive], summary="Lister les conteneurs")
async def list_containers(
    session: SessionDep,
    current_user: CurrentUser,
    params: PaginationDep,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    container_status: ContainerStatus | None = Query(None, alias="status"),
    include_absent: bool = Query(False),
) -> Page[ContainerLive]:
    statement = select(Container).order_by(Container.name)
    if project_id is not None:
        statement = statement.where(Container.project_id == project_id)
    if container_status is not None:
        statement = statement.where(Container.status == container_status)
    elif not include_absent:
        statement = statement.where(Container.status != ContainerStatus.ABSENT)

    page = await paginate(session, statement, params, ContainerRead)
    container_ids = [item.id for item in page.dataset]

    containers = (
        (await session.execute(select(Container).where(Container.id.in_(container_ids))))
        .scalars()
        .all()
    )
    by_id = {container.id: container for container in containers}
    latest = await latest_samples_by_container(session, container_ids)
    energy = await energy_by_container_ids(session, container_ids, window.start, window.end)

    dataset = [
        _to_live(by_id[item.id], latest.get(item.id), energy.get(item.id, (0.0, 0.0)))
        for item in page.dataset
        if item.id in by_id
    ]
    return Page[ContainerLive](dataset=dataset, pagination=page.pagination)


@router.get("/{container_id}", response_model=ContainerDetail, summary="Détail d'un conteneur")
async def get_container(
    container_id: int, session: SessionDep, current_user: CurrentUser, window: TimeWindowDep
) -> ContainerDetail:
    container = await session.get(Container, container_id)
    if container is None:
        raise NotFoundError("Conteneur introuvable.")

    project = await session.get(Project, container.project_id)
    latest = await latest_samples_by_container(session, [container_id])
    energy = await energy_by_container_ids(session, [container_id], window.start, window.end)

    stats_statement = select(
        func.count(ContainerMetricSample.id),
        func.min(ContainerMetricSample.collected_at),
        func.max(ContainerMetricSample.collected_at),
    ).where(ContainerMetricSample.container_id == container_id)
    sample_count, first_metric_at, last_metric_at = (await session.execute(stats_statement)).one()

    live = _to_live(container, latest.get(container_id), energy.get(container_id, (0.0, 0.0)))
    return ContainerDetail(
        **live.model_dump(),
        project_name=project.name if project else "",
        sample_count=int(sample_count or 0),
        first_metric_at=first_metric_at,
        last_metric_at=last_metric_at,
    )


@router.get(
    "/{container_id}/metrics",
    response_model=MetricSeries,
    summary="Série temporelle d'un conteneur",
)
async def get_container_metrics(
    container_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    metric: MetricKind = Query(MetricKind.CPU),
) -> MetricSeries:
    if await session.get(Container, container_id) is None:
        raise NotFoundError("Conteneur introuvable.")

    column, secondary, unit, label, secondary_label = SERIES_DEFINITIONS[metric]
    points = await container_series(
        session, container_id, window.start, window.end, window.granularity, column, secondary
    )
    return MetricSeries(
        metric=metric.value,
        unit=unit,
        label=label,
        secondary_label=secondary_label,
        points=points,
    )
