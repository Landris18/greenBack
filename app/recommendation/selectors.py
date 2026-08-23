from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_analysis.rules import ServiceObservation
from app.container.models import Container
from app.core.enums import ContainerStatus
from app.energy.models import EnergySample
from app.metric.models import ContainerMetricSample
from app.recommendation.rules.base import ContainerAnalysis, RuleThresholds

P95 = 0.95


async def build_analyses(
    session: AsyncSession, project_id: int, window_days: int
) -> list[ContainerAnalysis]:
    now = datetime.now(UTC)
    start = now - timedelta(days=window_days)

    containers = (
        (await session.execute(select(Container).where(Container.project_id == project_id)))
        .scalars()
        .all()
    )
    if not containers:
        return []

    container_ids = [container.id for container in containers]

    percentile_statement = (
        select(
            ContainerMetricSample.container_id,
            func.percentile_cont(P95)
            .within_group(ContainerMetricSample.cpu_cores_used)
            .label("cpu_cores_p95"),
            func.percentile_cont(P95)
            .within_group(ContainerMetricSample.cpu_percent)
            .label("cpu_percent_p95"),
            func.percentile_cont(P95)
            .within_group(ContainerMetricSample.cpu_percent_of_limit)
            .label("cpu_limit_p95"),
            func.percentile_cont(P95)
            .within_group(ContainerMetricSample.memory_working_set_bytes)
            .label("memory_p95"),
            func.percentile_cont(P95)
            .within_group(ContainerMetricSample.memory_percent_of_limit)
            .label("memory_limit_p95"),
            func.percentile_cont(P95)
            .within_group(ContainerMetricSample.net_rx_rate + ContainerMetricSample.net_tx_rate)
            .label("net_p95"),
            func.count(ContainerMetricSample.id).label("sample_count"),
            func.min(ContainerMetricSample.collected_at).label("first_at"),
            func.max(ContainerMetricSample.collected_at).label("last_at"),
        )
        .where(
            ContainerMetricSample.container_id.in_(container_ids),
            ContainerMetricSample.collected_at >= start,
        )
        .group_by(ContainerMetricSample.container_id)
    )
    metrics = {row.container_id: row for row in (await session.execute(percentile_statement)).all()}

    energy_statement = (
        select(EnergySample.container_id, func.sum(EnergySample.energy_wh).label("energy_wh"))
        .where(
            EnergySample.container_id.in_(container_ids),
            EnergySample.collected_at >= start,
        )
        .group_by(EnergySample.container_id)
    )
    energy = {
        row.container_id: float(row.energy_wh or 0.0)
        for row in (await session.execute(energy_statement)).all()
    }

    analyses: list[ContainerAnalysis] = []
    for container in containers:
        row = metrics.get(container.id)
        window_hours = 0.0
        if row is not None and row.first_at and row.last_at:
            window_hours = (row.last_at - row.first_at).total_seconds() / 3600.0

        exited_days = None
        if container.status is ContainerStatus.EXITED:
            exited_days = (now - container.last_seen_at).total_seconds() / 86400.0

        analyses.append(
            ContainerAnalysis(
                container_id=container.id,
                name=container.name,
                image_ref=container.image_ref,
                image_size_bytes=container.image_size_bytes,
                status=container.status,
                restart_count=container.restart_count,
                cpu_limit_cores=container.cpu_limit_cores,
                memory_limit_bytes=container.memory_limit_bytes,
                cpu_cores_p95=float(row.cpu_cores_p95 or 0.0) if row else 0.0,
                cpu_percent_p95=float(row.cpu_percent_p95 or 0.0) if row else 0.0,
                cpu_percent_of_limit_p95=(
                    float(row.cpu_limit_p95) if row and row.cpu_limit_p95 is not None else None
                ),
                memory_working_set_p95=float(row.memory_p95 or 0.0) if row else 0.0,
                memory_percent_of_limit_p95=(
                    float(row.memory_limit_p95)
                    if row and row.memory_limit_p95 is not None
                    else None
                ),
                net_rate_p95=float(row.net_p95 or 0.0) if row else 0.0,
                energy_wh_total=energy.get(container.id, 0.0),
                window_hours=window_hours,
                sample_count=int(row.sample_count) if row else 0,
                last_seen_at=container.last_seen_at,
                exited_days=exited_days,
            )
        )
    return analyses


def build_observations(
    session_containers: list[Container],
    analyses: list[ContainerAnalysis],
    thresholds: RuleThresholds,
) -> dict[str, ServiceObservation]:
    by_id = {container.id: container for container in session_containers}
    observations: dict[str, ServiceObservation] = {}

    for analysis in analyses:
        container = by_id.get(analysis.container_id)
        service = (container.service_name if container else None) or analysis.name
        is_idle = (
            analysis.status is ContainerStatus.RUNNING
            and analysis.window_hours >= thresholds.idle_hours
            and analysis.sample_count >= 10
            and analysis.cpu_percent_p95 < thresholds.idle_cpu_percent
            and analysis.net_rate_p95 < thresholds.idle_network_bps
        )
        observations[service] = ServiceObservation(
            service_name=service,
            container_id=analysis.container_id,
            cpu_cores_p95=analysis.cpu_cores_p95,
            memory_working_set_p95=analysis.memory_working_set_p95,
            is_idle=is_idle,
            sample_count=analysis.sample_count,
            energy_wh_total=analysis.energy_wh_total,
            window_hours=analysis.window_hours,
        )

    return observations
