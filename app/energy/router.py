from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep
from app.energy.schemas import (
    BreakdownItem,
    EnergyPoint,
    EnergySummary,
    EnergyTotals,
    ProjectEnergySeries,
)
from app.energy.selectors import (
    breakdown_by_container,
    breakdown_by_project,
    current_power_source,
    dominant_power_source,
    energy_history,
    energy_history_by_project,
    energy_totals,
    overhead_totals,
)
from app.setting.service import get_active_config
from app.utils.time_window import TimeWindowDep

router = APIRouter(prefix="/energy", tags=["Energy"])


@router.get("/summary", response_model=EnergySummary, summary="Synthese énergétique estimée")
async def get_energy_summary(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    host_id: int | None = Query(None),
) -> EnergySummary:
    config = await get_active_config(session)
    await session.commit()

    totals = await energy_totals(
        session, window.start, window.end, project_id=project_id, host_id=host_id
    )
    overhead = await overhead_totals(session, window.start, window.end, host_id=host_id)
    breakdown = await breakdown_by_container(
        session, window.start, window.end, project_id=project_id
    )
    source = await dominant_power_source(
        session, window.start, window.end, project_id=project_id, host_id=host_id
    )
    source_actuelle = await current_power_source(session, host_id=host_id)

    return EnergySummary(
        totals=totals,
        overhead=overhead,
        breakdown=breakdown,
        power_source=source or "MODEL",
        current_power_source=source_actuelle or source or "MODEL",
        emission_factor_g_per_kwh=config.emission_factor_g_per_kwh,
        emission_factor_label=config.emission_factor_label,
    )


@router.get("", response_model=EnergyTotals, summary="Énergie estimée sur une période")
async def get_energy(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    container_id: int | None = Query(None),
) -> EnergyTotals:
    return await energy_totals(
        session,
        window.start,
        window.end,
        project_id=project_id,
        container_id=container_id,
    )


@router.get("/history", response_model=list[EnergyPoint], summary="Historique énergétique")
async def get_energy_history(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    container_id: int | None = Query(None),
    include_overhead: bool = Query(False),
) -> list[EnergyPoint]:
    return await energy_history(
        session,
        window.start,
        window.end,
        window.granularity,
        project_id=project_id,
        container_id=container_id,
        include_overhead=include_overhead,
    )


@router.get(
    "/breakdown",
    response_model=list[BreakdownItem],
    summary="Répartition par conteneur ou par projet",
)
async def get_energy_breakdown(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    by: str = Query("container", pattern="^(container|project)$"),
    limit: int = Query(20, ge=1, le=100),
) -> list[BreakdownItem]:
    if by == "project":
        return await breakdown_by_project(session, window.start, window.end, limit=limit)
    return await breakdown_by_container(
        session, window.start, window.end, project_id=project_id, limit=limit
    )


@router.get(
    "/history/projects",
    response_model=list[ProjectEnergySeries],
    summary="Historique énergétique groupé par projet",
)
async def get_energy_history_by_project(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
) -> list[ProjectEnergySeries]:
    return await energy_history_by_project(session, window.start, window.end, window.granularity)
