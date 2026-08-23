from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep
from app.live.schemas import LiveResponse
from app.live.selectors import live_series

router = APIRouter(prefix="/live", tags=["Live"])


@router.get("", response_model=LiveResponse, summary="Mesures temps réel par projet")
async def get_live(
    session: SessionDep,
    current_user: CurrentUser,
    project_ids: str = Query(..., description="Identifiants de projet séparés par des virgules"),
    seconds: int = Query(300, ge=5, le=7200),
) -> LiveResponse:
    identifiers = [
        int(item) for item in project_ids.split(",") if item.strip().lstrip("-").isdigit()
    ]
    end = datetime.now(UTC)

    return LiveResponse(
        series=await live_series(session, identifiers, seconds),
        window_start=end - timedelta(seconds=seconds),
        window_end=end,
        interval_seconds=1,
    )
