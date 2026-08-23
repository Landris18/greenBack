from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.live.schemas import LivePoint, LiveSeries
from app.metric.models import LiveSample
from app.project.models import Project


async def live_series(
    session: AsyncSession, project_ids: list[int], seconds: int
) -> list[LiveSeries]:
    if not project_ids:
        return []

    start = datetime.now(UTC) - timedelta(seconds=max(1, seconds))

    per_tick = (
        select(
            LiveSample.project_id.label("project_id"),
            LiveSample.collected_at.label("collected_at"),
            func.sum(LiveSample.power_watts).label("power_watts"),
            func.sum(LiveSample.energy_wh).label("energy_wh"),
            func.sum(LiveSample.co2_g).label("co2_g"),
            func.sum(LiveSample.cpu_percent_of_host).label("cpu_percent_of_host"),
            func.sum(LiveSample.memory_working_set_bytes).label("memory_bytes"),
            func.count(func.distinct(LiveSample.container_id)).label("container_count"),
        )
        .where(LiveSample.project_id.in_(project_ids), LiveSample.collected_at >= start)
        .group_by(LiveSample.project_id, LiveSample.collected_at)
        .subquery()
    )

    window = {
        "partition_by": per_tick.c.project_id,
        "order_by": per_tick.c.collected_at,
    }
    statement = select(
        per_tick.c.project_id,
        per_tick.c.collected_at,
        per_tick.c.power_watts,
        per_tick.c.cpu_percent_of_host,
        per_tick.c.memory_bytes,
        per_tick.c.container_count,
        func.sum(per_tick.c.energy_wh).over(**window).label("energy_wh_cumulative"),
        func.sum(per_tick.c.co2_g).over(**window).label("co2_g_cumulative"),
    ).order_by(per_tick.c.project_id, per_tick.c.collected_at)

    rows = (await session.execute(statement)).all()

    names = {
        row.id: row.display_name or row.name
        for row in (
            await session.execute(
                select(Project.id, Project.name, Project.display_name).where(
                    Project.id.in_(project_ids)
                )
            )
        ).all()
    }

    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(row.project_id, []).append(row)

    series: list[LiveSeries] = []
    for project_id in project_ids:
        entries = grouped.get(project_id, [])
        points = [
            LivePoint(
                timestamp=row.collected_at,
                power_watts=round(float(row.power_watts or 0.0), 6),
                energy_wh_cumulative=round(float(row.energy_wh_cumulative or 0.0), 9),
                co2_g_cumulative=round(float(row.co2_g_cumulative or 0.0), 9),
                cpu_percent_of_host=round(float(row.cpu_percent_of_host or 0.0), 4),
                memory_bytes=int(row.memory_bytes or 0),
            )
            for row in entries
        ]
        average_power = sum(point.power_watts for point in points) / len(points) if points else 0.0

        series.append(
            LiveSeries(
                project_id=project_id,
                project_name=names.get(project_id, str(project_id)),
                container_count=int(entries[-1].container_count) if entries else 0,
                points=points,
                energy_wh_total=points[-1].energy_wh_cumulative if points else 0.0,
                co2_g_total=points[-1].co2_g_cumulative if points else 0.0,
                average_power_watts=round(average_power, 6),
            )
        )

    return series
