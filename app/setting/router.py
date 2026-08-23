from fastapi import APIRouter

from app.core.deps import CurrentUser, RequireAdmin, SessionDep
from app.setting.schemas import GreenConfigRead, GreenConfigUpdate
from app.setting.service import create_config_version, get_active_config

router = APIRouter(prefix="/settings", tags=["Setting"])


@router.get("/green", response_model=GreenConfigRead, summary="Paramètres Green IT actifs")
async def read_green_settings(session: SessionDep, current_user: CurrentUser) -> GreenConfigRead:
    config = await get_active_config(session)
    await session.commit()
    return GreenConfigRead.model_validate(config)


@router.put(
    "/green",
    response_model=GreenConfigRead,
    summary="Publier une nouvelle version des paramètres Green IT",
)
async def update_green_settings(
    payload: GreenConfigUpdate, session: SessionDep, current_user: RequireAdmin
) -> GreenConfigRead:
    config = await create_config_version(session, payload, current_user.id)
    return GreenConfigRead.model_validate(config)
