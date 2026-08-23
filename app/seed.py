import asyncio
import logging

from sqlalchemy import select

from app.core import models  # noqa: F401
from app.core.config import settings
from app.core.database import SessionFactory
from app.core.enums import UserRole
from app.core.security import hash_password
from app.setting.service import get_active_config
from app.user.models import User

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("greensi.seed")


async def seed() -> None:
    async with SessionFactory() as session:
        config = await get_active_config(session)
        await session.commit()
        logger.info("Configuration Green IT active : version %d", config.version)

        email = settings.SEED_ADMIN_EMAIL.lower()
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if existing is not None:
            logger.info("Compte administrateur déjà présent : %s", email)
            return

        session.add(
            User(
                email=email,
                full_name=settings.SEED_ADMIN_NAME,
                role=UserRole.ADMIN,
                hashed_password=hash_password(settings.SEED_ADMIN_PASSWORD),
            )
        )
        await session.commit()
        logger.info("Compte administrateur créé : %s", email)


if __name__ == "__main__":
    asyncio.run(seed())
