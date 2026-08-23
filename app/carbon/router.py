from fastapi import APIRouter, Query

from app.carbon.schemas import CarbonPoint, CarbonSummary, CarbonTotals
from app.core.deps import CurrentUser, SessionDep
from app.energy.schemas import BreakdownItem
from app.energy.selectors import (
    breakdown_by_container,
    energy_history,
    energy_totals,
    overhead_totals,
)
from app.setting.service import get_active_config
from app.utils.time_window import TimeWindowDep

router = APIRouter(prefix="/carbon", tags=["Carbon"])


async def _totals(session, window, project_id, container_id) -> CarbonTotals:
    config = await get_active_config(session)
    await session.commit()
    totals = await energy_totals(
        session,
        window.start,
        window.end,
        project_id=project_id,
        container_id=container_id,
    )
    return CarbonTotals(
        co2_kg=totals.co2_kg,
        energy_kwh=totals.energy_kwh,
        emission_factor_g_per_kwh=config.emission_factor_g_per_kwh,
        emission_factor_label=config.emission_factor_label,
        window_start=window.start,
        window_end=window.end,
    )


@router.get("", response_model=CarbonTotals, summary="Empreinte carbone estimée")
async def get_carbon(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    container_id: int | None = Query(None),
) -> CarbonTotals:
    return await _totals(session, window, project_id, container_id)


@router.get("/summary", response_model=CarbonSummary, summary="Synthese carbone estimée")
async def get_carbon_summary(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
) -> CarbonSummary:
    totals = await _totals(session, window, project_id, None)
    overhead = await overhead_totals(session, window.start, window.end)
    breakdown = await breakdown_by_container(
        session, window.start, window.end, project_id=project_id
    )
    points = await energy_history(
        session, window.start, window.end, window.granularity, project_id=project_id
    )

    return CarbonSummary(
        totals=totals,
        overhead_co2_kg=overhead.co2_kg,
        breakdown=breakdown,
        history=[CarbonPoint(timestamp=p.timestamp, co2_kg=p.co2_kg) for p in points],
    )


@router.get("/history", response_model=list[CarbonPoint], summary="Historique carbone")
async def get_carbon_history(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    container_id: int | None = Query(None),
) -> list[CarbonPoint]:
    points = await energy_history(
        session,
        window.start,
        window.end,
        window.granularity,
        project_id=project_id,
        container_id=container_id,
    )
    return [CarbonPoint(timestamp=p.timestamp, co2_kg=p.co2_kg) for p in points]


@router.get(
    "/breakdown", response_model=list[BreakdownItem], summary="Répartition carbone par conteneur"
)
async def get_carbon_breakdown(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[BreakdownItem]:
    return await breakdown_by_container(
        session, window.start, window.end, project_id=project_id, limit=limit
    )
