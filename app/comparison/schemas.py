from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComparisonSideMetrics(BaseModel):
    project_id: int
    project_name: str
    period_start: datetime
    period_end: datetime
    duration_hours: float
    container_count: int
    cpu_percent_avg: float
    cpu_percent_p95: float
    memory_bytes_avg: float
    memory_bytes_max: float
    total_image_size_bytes: int
    energy_kwh: float
    co2_kg: float
    energy_kwh_per_hour: float
    co2_kg_per_hour: float
    energy_kwh_per_hour_per_container: float


class GainItem(BaseModel):
    key: str
    label: str
    unit: str
    before: float
    after: float
    gain_percent: float | None
    is_normalized: bool = False


class ComparisonResult(BaseModel):
    side_a: ComparisonSideMetrics
    side_b: ComparisonSideMetrics
    gains: list[GainItem]
    warnings: list[str] = Field(default_factory=list)


class ComparisonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    project_a_id: int
    project_b_id: int
    period_a_start: datetime
    period_a_end: datetime
    period_b_start: datetime
    period_b_end: datetime

    @model_validator(mode="after")
    def check_periods(self) -> "ComparisonCreate":
        if self.period_a_start >= self.period_a_end:
            raise ValueError("La période A est invalide.")
        if self.period_b_start >= self.period_b_end:
            raise ValueError("La période B est invalide.")
        return self


class ComparisonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_a_id: int
    project_b_id: int
    period_a_start: datetime
    period_a_end: datetime
    period_b_start: datetime
    period_b_end: datetime
    created_by: int | None
    created_at: datetime
    result: ComparisonResult
