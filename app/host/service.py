from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.host.models import Host


async def get_or_create_host(session: AsyncSession, docker_url: str, name: str) -> Host:
    statement = select(Host).where(Host.docker_url == docker_url)
    host = (await session.execute(statement)).scalar_one_or_none()
    if host is not None:
        return host

    host = Host(name=name, docker_url=docker_url)
    session.add(host)
    await session.flush()
    return host
