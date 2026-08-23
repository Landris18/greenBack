from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import IdleAttributionPolicy


class GreenConfigUpdate(BaseModel):
    emission_factor_g_per_kwh: float = Field(gt=0, le=2000)
    emission_factor_label: str = Field(min_length=1, max_length=255)
    p_idle_watts: float = Field(ge=0, le=10000)
    p_max_watts: float = Field(gt=0, le=10000)
    mem_power_w_per_gb: float = Field(ge=0, le=100)
    non_cpu_overhead_ratio: float = Field(ge=0, le=10)
    max_idle_ratio: float = Field(ge=0, lt=1)
    weight_cpu: float = Field(ge=0, le=1)
    weight_memory: float = Field(ge=0, le=1)
    weight_io: float = Field(ge=0, le=1)
    weight_network: float = Field(ge=0, le=1)
    idle_attribution_policy: IdleAttributionPolicy
    threshold_cpu_underuse_percent: float = Field(gt=0, le=100)
    threshold_memory_underuse_percent: float = Field(gt=0, le=100)
    threshold_idle_cpu_percent: float = Field(ge=0, le=100)
    threshold_idle_network_bps: float = Field(ge=0)
    threshold_idle_hours: int = Field(ge=1, le=720)
    threshold_image_size_bytes: int = Field(ge=0)
    threshold_exited_days: int = Field(ge=1, le=365)
    threshold_restart_count: int = Field(ge=1, le=1000)
    analysis_window_days: int = Field(ge=1, le=90)
    threshold_cpu_high_percent: float = Field(gt=0, le=100)
    threshold_memory_high_percent: float = Field(gt=0, le=100)
    live_retention_minutes: int = Field(ge=1, le=1440)
    persist_every_n_ticks: int = Field(ge=1, le=600)

    @model_validator(mode="after")
    def check_consistency(self) -> "GreenConfigUpdate":
        if self.p_max_watts <= self.p_idle_watts:
            raise ValueError("La puissance maximale doit être supérieure à la puissance à vide.")
        weight_sum = self.weight_cpu + self.weight_memory + self.weight_io + self.weight_network
        if abs(weight_sum - 1.0) > 0.001:
            raise ValueError("La somme des pondérations d'attribution doit valoir 1.")
        return self


class GreenConfigRead(GreenConfigUpdate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    is_active: bool
    created_by: int | None
    calibration_note: str | None
    created_at: datetime
    updated_at: datetime
