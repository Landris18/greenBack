from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, SessionDep
from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PaginationParams, paginate, pagination_params
from app.host.models import Host, HostMetricSample
from app.host.schemas import HostMetricPoint, HostRead

router = APIRouter(prefix="/hosts", tags=["Host"])

PaginationDep = Annotated[PaginationParams, Depends(pagination_params)]


@router.get("", response_model=Page[HostRead], summary="Lister les hôtes Docker")
async def list_hosts(
    session: SessionDep, current_user: CurrentUser, params: PaginationDep
) -> Page[HostRead]:
    return await paginate(session, select(Host).order_by(Host.name), params, HostRead)


@router.get("/{host_id}", response_model=HostRead, summary="Détail d'un hôte")
async def get_host(host_id: int, session: SessionDep, current_user: CurrentUser) -> HostRead:
    host = await session.get(Host, host_id)
    if host is None:
        raise NotFoundError("Hôte introuvable.")
    return HostRead.model_validate(host)


@router.get(
    "/{host_id}/metrics",
    response_model=list[HostMetricPoint],
    summary="Historique des métriques d'un hôte",
)
async def get_host_metrics(
    host_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(500, ge=1, le=5000),
) -> list[HostMetricPoint]:
    host = await session.get(Host, host_id)
    if host is None:
        raise NotFoundError("Hôte introuvable.")

    since = datetime.now(UTC) - timedelta(hours=hours)
    statement = (
        select(HostMetricSample)
        .where(HostMetricSample.host_id == host_id, HostMetricSample.collected_at >= since)
        .order_by(HostMetricSample.collected_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(statement)).scalars().all()
    return [HostMetricPoint.model_validate(row) for row in reversed(rows)]
