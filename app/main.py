import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.api import api_router
from app.core import models  # noqa: F401
from app.core.config import settings
from app.core.exceptions import register_exception_handlers

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

DESCRIPTION = (
    "Plateforme décisionnelle Green IT. Les valeurs énergétiques et carbone exposées par cette "
    "API sont des estimations calculées à partir des métriques d'infrastructure collectées et du "
    "modèle énergétique documenté, et non des mesures électriques directes."
)


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description=DESCRIPTION,
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_PREFIX)

    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", app=settings.APP_NAME, environment=settings.APP_ENV)

    return app


app = create_app()
