from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.models import Container
from app.core.enums import Granularity
from app.energy.models import EnergySample
from app.energy.schemas import BreakdownItem, EnergyPoint, EnergyTotals, ProjectEnergySeries
from app.host.models import HostMetricSample
from app.project.models import Project


def _scope(statement, project_id: int | None, container_id: int | None, host_id: int | None):
    if project_id is not None:
        statement = statement.where(EnergySample.project_id == project_id)
    if container_id is not None:
        statement = statement.where(EnergySample.container_id == container_id)
    if host_id is not None:
        statement = statement.where(EnergySample.host_id == host_id)
    return statement


async def energy_totals(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    project_id: int | None = None,
    container_id: int | None = None,
    host_id: int | None = None,
    include_overhead: bool = False,
) -> EnergyTotals:
    statement = select(
        func.coalesce(func.sum(EnergySample.energy_wh), 0.0).label("energy_wh"),
        func.coalesce(func.sum(EnergySample.co2_g), 0.0).label("co2_g"),
        func.coalesce(func.avg(EnergySample.power_watts), 0.0).label("power_avg"),
        func.count(EnergySample.id).label("sample_count"),
    ).where(EnergySample.collected_at >= start, EnergySample.collected_at <= end)

    if not include_overhead:
        statement = statement.where(EnergySample.is_overhead.is_(False))
    statement = _scope(statement, project_id, container_id, host_id)

    row = (await session.execute(statement)).one()
    return EnergyTotals(
        energy_kwh=float(row.energy_wh) / 1000.0,
        co2_kg=float(row.co2_g) / 1000.0,
        average_power_watts=float(row.power_avg),
        sample_count=int(row.sample_count),
        window_start=start,
        window_end=end,
    )


async def overhead_totals(
    session: AsyncSession, start: datetime, end: datetime, host_id: int | None = None
) -> EnergyTotals:
    statement = select(
        func.coalesce(func.sum(EnergySample.energy_wh), 0.0).label("energy_wh"),
        func.coalesce(func.sum(EnergySample.co2_g), 0.0).label("co2_g"),
        func.coalesce(func.avg(EnergySample.power_watts), 0.0).label("power_avg"),
        func.count(EnergySample.id).label("sample_count"),
    ).where(
        EnergySample.collected_at >= start,
        EnergySample.collected_at <= end,
        EnergySample.is_overhead.is_(True),
    )
    if host_id is not None:
        statement = statement.where(EnergySample.host_id == host_id)

    row = (await session.execute(statement)).one()
    return EnergyTotals(
        energy_kwh=float(row.energy_wh) / 1000.0,
        co2_kg=float(row.co2_g) / 1000.0,
        average_power_watts=float(row.power_avg),
        sample_count=int(row.sample_count),
        window_start=start,
        window_end=end,
    )


async def energy_history(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    granularity: Granularity,
    project_id: int | None = None,
    container_id: int | None = None,
    host_id: int | None = None,
    include_overhead: bool = False,
) -> list[EnergyPoint]:
    bucket = func.date_trunc(granularity.value, EnergySample.collected_at).label("bucket")
    statement = (
        select(
            bucket,
            func.sum(EnergySample.energy_wh).label("energy_wh"),
            func.sum(EnergySample.co2_g).label("co2_g"),
        )
        .where(EnergySample.collected_at >= start, EnergySample.collected_at <= end)
        .group_by(bucket)
        .order_by(bucket)
    )
    if not include_overhead:
        statement = statement.where(EnergySample.is_overhead.is_(False))
    statement = _scope(statement, project_id, container_id, host_id)

    rows = (await session.execute(statement)).all()
    return [
        EnergyPoint(
            timestamp=row.bucket,
            energy_kwh=float(row.energy_wh or 0.0) / 1000.0,
            co2_kg=float(row.co2_g or 0.0) / 1000.0,
        )
        for row in rows
    ]


async def breakdown_by_container(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    project_id: int | None = None,
    limit: int = 20,
) -> list[BreakdownItem]:
    statement = (
        select(
            Container.id.label("entity_id"),
            Container.name.label("label"),
            func.sum(EnergySample.energy_wh).label("energy_wh"),
            func.sum(EnergySample.co2_g).label("co2_g"),
        )
        .join(Container, Container.id == EnergySample.container_id)
        .where(
            EnergySample.collected_at >= start,
            EnergySample.collected_at <= end,
            EnergySample.is_overhead.is_(False),
        )
        .group_by(Container.id, Container.name)
        .order_by(func.sum(EnergySample.energy_wh).desc())
        .limit(limit)
    )
    if project_id is not None:
        statement = statement.where(EnergySample.project_id == project_id)

    rows = (await session.execute(statement)).all()
    return [
        BreakdownItem(
            entity_id=row.entity_id,
            label=row.label,
            energy_kwh=float(row.energy_wh or 0.0) / 1000.0,
            co2_kg=float(row.co2_g or 0.0) / 1000.0,
        )
        for row in rows
    ]


async def breakdown_by_project(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    limit: int = 20,
) -> list[BreakdownItem]:
    statement = (
        select(
            Project.id.label("entity_id"),
            Project.name.label("label"),
            func.sum(EnergySample.energy_wh).label("energy_wh"),
            func.sum(EnergySample.co2_g).label("co2_g"),
        )
        .join(Project, Project.id == EnergySample.project_id)
        .where(
            EnergySample.collected_at >= start,
            EnergySample.collected_at <= end,
            EnergySample.is_overhead.is_(False),
        )
        .group_by(Project.id, Project.name)
        .order_by(func.sum(EnergySample.energy_wh).desc())
        .limit(limit)
    )

    rows = (await session.execute(statement)).all()
    return [
        BreakdownItem(
            entity_id=row.entity_id,
            label=row.label,
            energy_kwh=float(row.energy_wh or 0.0) / 1000.0,
            co2_kg=float(row.co2_g or 0.0) / 1000.0,
        )
        for row in rows
    ]


async def energy_history_by_project(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    granularity: Granularity,
) -> list[ProjectEnergySeries]:
    bucket = func.date_trunc(granularity.value, EnergySample.collected_at).label("bucket")
    statement = (
        select(
            EnergySample.project_id,
            Project.name.label("project_name"),
            bucket,
            func.sum(EnergySample.energy_wh).label("energy_wh"),
            func.sum(EnergySample.co2_g).label("co2_g"),
        )
        .join(Project, Project.id == EnergySample.project_id)
        .where(
            EnergySample.collected_at >= start,
            EnergySample.collected_at <= end,
            EnergySample.is_overhead.is_(False),
        )
        .group_by(EnergySample.project_id, Project.name, bucket)
        .order_by(EnergySample.project_id, bucket)
    )

    rows = (await session.execute(statement)).all()
    groupes: dict[int, ProjectEnergySeries] = {}

    for row in rows:
        serie = groupes.get(row.project_id)
        if serie is None:
            serie = ProjectEnergySeries(
                project_id=row.project_id, project_name=row.project_name, points=[]
            )
            groupes[row.project_id] = serie
        serie.points.append(
            EnergyPoint(
                timestamp=row.bucket,
                energy_kwh=float(row.energy_wh or 0.0) / 1000.0,
                co2_kg=float(row.co2_g or 0.0) / 1000.0,
            )
        )

    return sorted(
        groupes.values(),
        key=lambda serie: sum(point.energy_kwh for point in serie.points),
        reverse=True,
    )


async def dominant_power_source(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    project_id: int | None = None,
    host_id: int | None = None,
) -> str | None:
    statement = (
        select(EnergySample.power_source, func.count(EnergySample.id).label("total"))
        .where(EnergySample.collected_at >= start, EnergySample.collected_at <= end)
        .group_by(EnergySample.power_source)
        .order_by(func.count(EnergySample.id).desc())
        .limit(1)
    )
    statement = _scope(statement, project_id, None, host_id)
    row = (await session.execute(statement)).first()
    return row.power_source.value if row else None


async def current_power_source(session: AsyncSession, host_id: int | None = None) -> str | None:
    statement = (
        select(HostMetricSample.power_source)
        .order_by(HostMetricSample.collected_at.desc())
        .limit(1)
    )
    if host_id is not None:
        statement = statement.where(HostMetricSample.host_id == host_id)
    row = (await session.execute(statement)).first()
    return row.power_source.value if row else None


async def energy_by_container_ids(
    session: AsyncSession, container_ids: list[int], start: datetime, end: datetime
) -> dict[int, tuple[float, float]]:
    if not container_ids:
        return {}

    statement = (
        select(
            EnergySample.container_id,
            func.sum(EnergySample.energy_wh).label("energy_wh"),
            func.sum(EnergySample.co2_g).label("co2_g"),
        )
        .where(
            EnergySample.container_id.in_(container_ids),
            EnergySample.collected_at >= start,
            EnergySample.collected_at <= end,
        )
        .group_by(EnergySample.container_id)
    )
    rows = (await session.execute(statement)).all()
    return {
        row.container_id: (
            float(row.energy_wh or 0.0) / 1000.0,
            float(row.co2_g or 0.0) / 1000.0,
        )
        for row in rows
    }
