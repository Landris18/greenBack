from fastapi import APIRouter

from app.auth.router import router as auth_router
from app.carbon.router import router as carbon_router
from app.comparison.router import router as comparison_router
from app.container.router import router as container_router
from app.energy.router import router as energy_router
from app.host.router import router as host_router
from app.live.router import router as live_router
from app.metric.router import router as metric_router
from app.project.router import router as project_router
from app.recommendation.router import router as recommendation_router
from app.setting.router import router as setting_router
from app.user.router import router as user_router

api_router = APIRouter()

for router in (
    auth_router,
    user_router,
    project_router,
    host_router,
    container_router,
    metric_router,
    live_router,
    energy_router,
    carbon_router,
    recommendation_router,
    comparison_router,
    setting_router,
):
    api_router.include_router(router)
