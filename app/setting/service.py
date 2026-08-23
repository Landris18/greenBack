from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.energy.model import AttributionWeights, PowerModelParams
from app.setting.models import GreenConfig
from app.setting.schemas import GreenConfigUpdate


async def get_active_config(session: AsyncSession) -> GreenConfig:
    statement = select(GreenConfig).where(GreenConfig.is_active.is_(True))
    config = (await session.execute(statement)).scalar_one_or_none()
    if config is not None:
        return config

    config = GreenConfig(version=1, is_active=True)
    session.add(config)
    await session.flush()
    return config


async def create_config_version(
    session: AsyncSession,
    payload: GreenConfigUpdate,
    user_id: int | None,
    calibration_note: str | None = None,
) -> GreenConfig:
    current = await get_active_config(session)
    current.is_active = False

    config = GreenConfig(
        version=current.version + 1,
        is_active=True,
        created_by=user_id,
        calibration_note=calibration_note,
        **payload.model_dump(),
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


def weights_from_config(config: GreenConfig) -> AttributionWeights:
    return AttributionWeights(
        cpu=config.weight_cpu,
        memory=config.weight_memory,
        io=config.weight_io,
        network=config.weight_network,
    )


def power_params_from_config(config: GreenConfig) -> PowerModelParams:
    return PowerModelParams(
        p_idle_watts=config.p_idle_watts,
        p_max_watts=config.p_max_watts,
        mem_power_w_per_gb=config.mem_power_w_per_gb,
        non_cpu_overhead_ratio=config.non_cpu_overhead_ratio,
    )
