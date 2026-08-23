import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import models  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.core.enums import UserRole
from app.core.security import hash_password
from app.setting.models import GreenConfig
from app.user.models import User

TEST_DATABASE_NAME = f"{settings.DATABASE_NAME}_test"


def _url(database: str) -> str:
    return (
        f"postgresql+asyncpg://{settings.DATABASE_USER}:{settings.DATABASE_PASSWORD}"
        f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{database}"
    )


async def _create_database() -> None:
    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}"')
        await connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}"')
    await admin.dispose()

    engine = create_async_engine(_url(TEST_DATABASE_NAME))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_create_database())


@pytest_asyncio.fixture
async def session(test_database) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_url(TEST_DATABASE_NAME))
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.exec_driver_sql(f'TRUNCATE TABLE "{table.name}" CASCADE')

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest.fixture
def user_factory(session):
    async def create(
        email: str = "tech@greensi.fr",
        role: UserRole = UserRole.TECH,
        password: str = "motdepasse123",
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            full_name=email.split("@")[0],
            role=role,
            is_active=is_active,
            hashed_password=hash_password(password),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    return create


@pytest.fixture
def green_config_factory(session):
    async def create(**overrides) -> GreenConfig:
        config = GreenConfig(version=1, is_active=True, **overrides)
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return config

    return create
