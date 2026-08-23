from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.models import Container
from app.core.enums import Granularity
from app.metric.models import ContainerMetricSample
from app.metric.schemas import MetricPoint


async def latest_samples_by_container(
    session: AsyncSession, container_ids: list[int]
) -> dict[int, ContainerMetricSample]:
    if not container_ids:
        return {}

    latest_ids = (
        select(func.max(ContainerMetricSample.id))
        .where(ContainerMetricSample.container_id.in_(container_ids))
        .group_by(ContainerMetricSample.container_id)
    )
    statement = select(ContainerMetricSample).where(ContainerMetricSample.id.in_(latest_ids))
    rows = (await session.execute(statement)).scalars().all()
    return {row.container_id: row for row in rows}


def _bucket(granularity: Granularity):
    return func.date_trunc(granularity.value, ContainerMetricSample.collected_at)


async def container_series(
    session: AsyncSession,
    container_id: int,
    start: datetime,
    end: datetime,
    granularity: Granularity,
    value_column,
    secondary_column=None,
) -> list[MetricPoint]:
    bucket = _bucket(granularity).label("bucket")
    columns = [bucket, func.avg(value_column).label("value")]
    if secondary_column is not None:
        columns.append(func.avg(secondary_column).label("secondary_value"))

    statement = (
        select(*columns)
        .where(
            ContainerMetricSample.container_id == container_id,
            ContainerMetricSample.collected_at >= start,
            ContainerMetricSample.collected_at <= end,
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(statement)).all()
    return [
        MetricPoint(
            timestamp=row.bucket,
            value=float(row.value or 0.0),
            secondary_value=(
                float(row.secondary_value or 0.0) if secondary_column is not None else None
            ),
        )
        for row in rows
    ]


async def project_metric_summary(
    session: AsyncSession, project_id: int, start: datetime, end: datetime
) -> dict[str, float | int | datetime | None]:
    statement = (
        select(
            func.count(ContainerMetricSample.id).label("sample_count"),
            func.avg(ContainerMetricSample.cpu_percent).label("cpu_avg"),
            func.max(ContainerMetricSample.cpu_percent).label("cpu_max"),
            func.avg(ContainerMetricSample.memory_working_set_bytes).label("memory_avg"),
            func.max(ContainerMetricSample.memory_working_set_bytes).label("memory_max"),
            func.avg(ContainerMetricSample.net_rx_rate + ContainerMetricSample.net_tx_rate).label(
                "net_avg"
            ),
            func.avg(
                ContainerMetricSample.blk_read_rate + ContainerMetricSample.blk_write_rate
            ).label("io_avg"),
            func.min(ContainerMetricSample.collected_at).label("window_start"),
            func.max(ContainerMetricSample.collected_at).label("window_end"),
        )
        .join(Container, Container.id == ContainerMetricSample.container_id)
        .where(
            Container.project_id == project_id,
            ContainerMetricSample.collected_at >= start,
            ContainerMetricSample.collected_at <= end,
        )
    )
    row = (await session.execute(statement)).one()
    return {
        "sample_count": int(row.sample_count or 0),
        "cpu_percent_avg": float(row.cpu_avg or 0.0),
        "cpu_percent_max": float(row.cpu_max or 0.0),
        "memory_bytes_avg": float(row.memory_avg or 0.0),
        "memory_bytes_max": float(row.memory_max or 0.0),
        "net_rate_bps_avg": float(row.net_avg or 0.0),
        "io_rate_bps_avg": float(row.io_avg or 0.0),
        "window_start": row.window_start,
        "window_end": row.window_end,
    }
