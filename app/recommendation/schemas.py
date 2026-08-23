from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.enums import (
    Difficulty,
    RecommendationSource,
    RecommendationStatus,
    RuleCode,
    Severity,
)


class RecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    container_id: int | None
    rule_code: RuleCode
    severity: Severity
    difficulty: Difficulty
    title: str
    description: str
    current_value: dict[str, Any]
    suggested_value: dict[str, Any]
    estimated_energy_saving_kwh: float | None
    estimated_co2_saving_kg: float | None
    saving_is_computed: bool
    saving_note: str | None
    status: RecommendationStatus
    evidence: dict[str, Any]
    source: RecommendationSource
    patch: dict[str, Any] | None
    detected_at: datetime
    updated_at: datetime


class RecommendationUpdate(BaseModel):
    status: RecommendationStatus


class ScanResult(BaseModel):
    project_id: int
    analysed_containers: int
    analysed_services: int
    created: int
    updated: int
    resolved: int
    open_total: int
    computed_saving_kwh: float
    computed_saving_kg_co2: float
    saving_note: str
