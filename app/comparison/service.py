from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.comparison.schemas import ComparisonResult, ComparisonSideMetrics, GainItem
from app.container.models import Container
from app.core.exceptions import NotFoundError
from app.energy.selectors import energy_totals
from app.metric.models import ContainerMetricSample
from app.project.models import Project

DIVERGENCE_TOLERANCE = 0.20
P95 = 0.95


def gain_percent(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return round((before - after) / before * 100.0, 2)


async def build_side_metrics(
    session: AsyncSession, project_id: int, start: datetime, end: datetime
) -> ComparisonSideMetrics:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Projet {project_id} introuvable.")

    duration_hours = max((end - start).total_seconds() / 3600.0, 0.0)

    metrics_statement = (
        select(
            func.avg(ContainerMetricSample.cpu_percent).label("cpu_avg"),
            func.percentile_cont(P95)
            .within_group(ContainerMetricSample.cpu_percent)
            .label("cpu_p95"),
            func.avg(ContainerMetricSample.memory_working_set_bytes).label("memory_avg"),
            func.max(ContainerMetricSample.memory_working_set_bytes).label("memory_max"),
            func.count(func.distinct(ContainerMetricSample.container_id)).label("container_count"),
        )
        .join(Container, Container.id == ContainerMetricSample.container_id)
        .where(
            Container.project_id == project_id,
            ContainerMetricSample.collected_at >= start,
            ContainerMetricSample.collected_at <= end,
        )
    )
    row = (await session.execute(metrics_statement)).one()

    image_statement = select(func.coalesce(func.sum(Container.image_size_bytes), 0)).where(
        Container.project_id == project_id
    )
    total_image_size = int((await session.execute(image_statement)).scalar_one())

    totals = await energy_totals(session, start, end, project_id=project_id)

    container_count = int(row.container_count or 0)
    energy_per_hour = totals.energy_kwh / duration_hours if duration_hours else 0.0
    co2_per_hour = totals.co2_kg / duration_hours if duration_hours else 0.0
    energy_per_hour_per_container = energy_per_hour / container_count if container_count else 0.0

    return ComparisonSideMetrics(
        project_id=project_id,
        project_name=project.name,
        period_start=start,
        period_end=end,
        duration_hours=round(duration_hours, 3),
        container_count=container_count,
        cpu_percent_avg=round(float(row.cpu_avg or 0.0), 3),
        cpu_percent_p95=round(float(row.cpu_p95 or 0.0), 3),
        memory_bytes_avg=round(float(row.memory_avg or 0.0), 1),
        memory_bytes_max=round(float(row.memory_max or 0.0), 1),
        total_image_size_bytes=total_image_size,
        energy_kwh=round(totals.energy_kwh, 10),
        co2_kg=round(totals.co2_kg, 10),
        energy_kwh_per_hour=round(energy_per_hour, 12),
        co2_kg_per_hour=round(co2_per_hour, 12),
        energy_kwh_per_hour_per_container=round(energy_per_hour_per_container, 12),
    )


def _relative_divergence(a: float, b: float) -> float:
    reference = max(abs(a), abs(b))
    if reference == 0:
        return 0.0
    return abs(a - b) / reference


def build_gains(a: ComparisonSideMetrics, b: ComparisonSideMetrics) -> list[GainItem]:
    return [
        GainItem(
            key="cpu_percent_avg",
            label="CPU moyen",
            unit="%",
            before=a.cpu_percent_avg,
            after=b.cpu_percent_avg,
            gain_percent=gain_percent(a.cpu_percent_avg, b.cpu_percent_avg),
        ),
        GainItem(
            key="memory_bytes_avg",
            label="Mémoire moyenne",
            unit="octets",
            before=a.memory_bytes_avg,
            after=b.memory_bytes_avg,
            gain_percent=gain_percent(a.memory_bytes_avg, b.memory_bytes_avg),
        ),
        GainItem(
            key="total_image_size_bytes",
            label="Taille cumulée des images",
            unit="octets",
            before=float(a.total_image_size_bytes),
            after=float(b.total_image_size_bytes),
            gain_percent=gain_percent(
                float(a.total_image_size_bytes), float(b.total_image_size_bytes)
            ),
        ),
        GainItem(
            key="energy_kwh_per_hour",
            label="Énergie estimée par heure",
            unit="kWh/h",
            before=a.energy_kwh_per_hour,
            after=b.energy_kwh_per_hour,
            gain_percent=gain_percent(a.energy_kwh_per_hour, b.energy_kwh_per_hour),
            is_normalized=True,
        ),
        GainItem(
            key="co2_kg_per_hour",
            label="Empreinte carbone estimée par heure",
            unit="kgCO2e/h",
            before=a.co2_kg_per_hour,
            after=b.co2_kg_per_hour,
            gain_percent=gain_percent(a.co2_kg_per_hour, b.co2_kg_per_hour),
            is_normalized=True,
        ),
        GainItem(
            key="energy_kwh_per_hour_per_container",
            label="Énergie estimée par heure et par conteneur",
            unit="kWh/h/conteneur",
            before=a.energy_kwh_per_hour_per_container,
            after=b.energy_kwh_per_hour_per_container,
            gain_percent=gain_percent(
                a.energy_kwh_per_hour_per_container, b.energy_kwh_per_hour_per_container
            ),
            is_normalized=True,
        ),
    ]


def build_warnings(a: ComparisonSideMetrics, b: ComparisonSideMetrics) -> list[str]:
    warnings: list[str] = []

    if _relative_divergence(a.duration_hours, b.duration_hours) > DIVERGENCE_TOLERANCE:
        warnings.append(
            f"Les deux périodes n'ont pas la même durée ({a.duration_hours:.1f} h contre "
            f"{b.duration_hours:.1f} h). Les gains sont calculés sur les valeurs ramenées à "
            "l'heure."
        )
    if _relative_divergence(a.container_count, b.container_count) > DIVERGENCE_TOLERANCE:
        warnings.append(
            f"Le nombre de conteneurs observés diffère ({a.container_count} contre "
            f"{b.container_count}). Comparez de préférence l'énergie par heure et par conteneur."
        )
    if a.container_count == 0 or b.container_count == 0:
        warnings.append("Au moins un des deux projets n'a aucune métrique sur la période demandée.")
    if not _periods_overlap(a, b):
        warnings.append(
            "Les deux périodes ne se recouvrent pas. L'état de la machine hôte a pu changer "
            "entre les deux mesures, ce qui réduit la comparabilité."
        )
    return warnings


def _periods_overlap(a: ComparisonSideMetrics, b: ComparisonSideMetrics) -> bool:
    return a.period_start < b.period_end and b.period_start < a.period_end


async def build_comparison(
    session: AsyncSession,
    project_a_id: int,
    period_a_start: datetime,
    period_a_end: datetime,
    project_b_id: int,
    period_b_start: datetime,
    period_b_end: datetime,
) -> ComparisonResult:
    side_a = await build_side_metrics(session, project_a_id, period_a_start, period_a_end)
    side_b = await build_side_metrics(session, project_b_id, period_b_start, period_b_end)

    return ComparisonResult(
        side_a=side_a,
        side_b=side_b,
        gains=build_gains(side_a, side_b),
        warnings=build_warnings(side_a, side_b),
    )
