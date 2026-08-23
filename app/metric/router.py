from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.container.models import Container
from app.core.deps import CurrentUser, SessionDep
from app.core.enums import ContainerStatus
from app.metric.schemas import MetricSummary
from app.metric.selectors import project_metric_summary
from app.utils.time_window import TimeWindowDep

router = APIRouter(prefix="/metrics", tags=["Metric"])


@router.get("/summary", response_model=MetricSummary, summary="Synthese des métriques")
async def get_metric_summary(
    session: SessionDep,
    current_user: CurrentUser,
    window: TimeWindowDep,
    project_id: int = Query(...),
) -> MetricSummary:
    aggregates = await project_metric_summary(session, project_id, window.start, window.end)

    counts_statement = select(
        func.count(Container.id),
        func.count(Container.id).filter(Container.status == ContainerStatus.RUNNING),
    ).where(Container.project_id == project_id)
    container_count, running_count = (await session.execute(counts_statement)).one()

    return MetricSummary(
        container_count=int(container_count or 0),
        running_count=int(running_count or 0),
        **aggregates,
    )
