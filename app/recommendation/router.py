from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, select

from app.core.deps import CurrentUser, RequireTech, SessionDep
from app.core.enums import RecommendationSource, RecommendationStatus, Severity
from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PaginationParams, paginate, pagination_params
from app.recommendation.models import Recommendation
from app.recommendation.schemas import RecommendationRead, RecommendationUpdate

router = APIRouter(prefix="/recommendations", tags=["Recommendation"])

PaginationDep = Annotated[PaginationParams, Depends(pagination_params)]

SEVERITY_RANK = case(
    (Recommendation.severity == Severity.CRITICAL, 0),
    (Recommendation.severity == Severity.HIGH, 1),
    (Recommendation.severity == Severity.MEDIUM, 2),
    else_=3,
)


@router.get("", response_model=Page[RecommendationRead], summary="Lister les recommandations")
async def list_recommendations(
    session: SessionDep,
    current_user: CurrentUser,
    params: PaginationDep,
    project_id: int | None = Query(None),
    severity: Severity | None = Query(None),
    source: RecommendationSource | None = Query(None),
    recommendation_status: RecommendationStatus | None = Query(
        RecommendationStatus.OPEN, alias="status"
    ),
) -> Page[RecommendationRead]:
    statement = select(Recommendation).order_by(
        SEVERITY_RANK,
        Recommendation.saving_is_computed.desc(),
        Recommendation.estimated_energy_saving_kwh.desc().nullslast(),
        Recommendation.id,
    )
    if project_id is not None:
        statement = statement.where(Recommendation.project_id == project_id)
    if severity is not None:
        statement = statement.where(Recommendation.severity == severity)
    if source is not None:
        statement = statement.where(Recommendation.source == source)
    if recommendation_status is not None:
        statement = statement.where(Recommendation.status == recommendation_status)

    return await paginate(session, statement, params, RecommendationRead)


@router.get(
    "/{recommendation_id}",
    response_model=RecommendationRead,
    summary="Détail d'une recommandation",
)
async def get_recommendation(
    recommendation_id: int, session: SessionDep, current_user: CurrentUser
) -> RecommendationRead:
    recommendation = await session.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("Recommandation introuvable.")
    return RecommendationRead.model_validate(recommendation)


@router.get(
    "/{recommendation_id}/patch",
    response_model=dict,
    summary="Diff proposé pour cette recommandation",
)
async def get_recommendation_patch(
    recommendation_id: int, session: SessionDep, current_user: CurrentUser
) -> dict:
    recommendation = await session.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("Recommandation introuvable.")
    if not recommendation.patch:
        raise NotFoundError("Aucune modification automatique n'est proposée pour cette règle.")
    return recommendation.patch


@router.patch(
    "/{recommendation_id}",
    response_model=RecommendationRead,
    summary="Changer le statut d'une recommandation",
)
async def update_recommendation(
    recommendation_id: int,
    payload: RecommendationUpdate,
    session: SessionDep,
    current_user: RequireTech,
) -> RecommendationRead:
    recommendation = await session.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("Recommandation introuvable.")

    recommendation.status = payload.status
    await session.commit()
    await session.refresh(recommendation)
    return RecommendationRead.model_validate(recommendation)
