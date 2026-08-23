from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import PowerSource, ResourceStatus


class HostCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    docker_url: str = Field(min_length=1, max_length=512)


class HostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    docker_url: str
    cpu_cores: int
    total_memory_bytes: int
    os_info: str | None
    power_source: PowerSource
    status: ResourceStatus
    last_seen_at: datetime | None
    last_error: str | None
    measurement_sources: dict | None
    created_at: datetime
    updated_at: datetime


class HostMetricPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collected_at: datetime
    cpu_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    power_watts: float
    idle_power_watts: float
    dynamic_power_watts: float
    power_source: PowerSource
