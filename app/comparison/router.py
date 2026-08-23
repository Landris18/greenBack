from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.comparison.models import Comparison
from app.comparison.schemas import ComparisonCreate, ComparisonRead, ComparisonResult
from app.comparison.service import build_comparison
from app.core.deps import CurrentUser, SessionDep
from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PaginationParams, paginate, pagination_params

router = APIRouter(prefix="/comparisons", tags=["Comparison"])

PaginationDep = Annotated[PaginationParams, Depends(pagination_params)]


@router.get("", response_model=Page[ComparisonRead], summary="Lister les comparaisons")
async def list_comparisons(
    session: SessionDep, current_user: CurrentUser, params: PaginationDep
) -> Page[ComparisonRead]:
    statement = select(Comparison).order_by(Comparison.created_at.desc())
    return await paginate(session, statement, params, ComparisonRead)


@router.post(
    "",
    response_model=ComparisonRead,
    status_code=status.HTTP_201_CREATED,
    summary="Comparer deux projets",
)
async def create_comparison(
    payload: ComparisonCreate, session: SessionDep, current_user: CurrentUser
) -> ComparisonRead:
    result = await build_comparison(
        session,
        payload.project_a_id,
        payload.period_a_start,
        payload.period_a_end,
        payload.project_b_id,
        payload.period_b_start,
        payload.period_b_end,
    )

    comparison = Comparison(
        name=payload.name,
        project_a_id=payload.project_a_id,
        project_b_id=payload.project_b_id,
        period_a_start=payload.period_a_start,
        period_a_end=payload.period_a_end,
        period_b_start=payload.period_b_start,
        period_b_end=payload.period_b_end,
        created_by=current_user.id,
        result=result.model_dump(mode="json"),
    )
    session.add(comparison)
    await session.commit()
    await session.refresh(comparison)
    return ComparisonRead.model_validate(comparison)


@router.post("/preview", response_model=ComparisonResult, summary="Prévisualiser une comparaison")
async def preview_comparison(
    payload: ComparisonCreate, session: SessionDep, current_user: CurrentUser
) -> ComparisonResult:
    return await build_comparison(
        session,
        payload.project_a_id,
        payload.period_a_start,
        payload.period_a_end,
        payload.project_b_id,
        payload.period_b_start,
        payload.period_b_end,
    )


@router.get("/{comparison_id}", response_model=ComparisonRead, summary="Détail d'une comparaison")
async def get_comparison(
    comparison_id: int, session: SessionDep, current_user: CurrentUser
) -> ComparisonRead:
    comparison = await session.get(Comparison, comparison_id)
    if comparison is None:
        raise NotFoundError("Comparaison introuvable.")
    return ComparisonRead.model_validate(comparison)


@router.delete(
    "/{comparison_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une comparaison",
)
async def delete_comparison(
    comparison_id: int, session: SessionDep, current_user: CurrentUser
) -> None:
    comparison = await session.get(Comparison, comparison_id)
    if comparison is None:
        raise NotFoundError("Comparaison introuvable.")
    await session.delete(comparison)
    await session.commit()
