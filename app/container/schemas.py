from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import ContainerStatus


class ContainerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    docker_id: str
    service_name: str | None
    image_ref: str
    image_id: str | None
    image_size_bytes: int | None
    cpu_limit_cores: float | None
    memory_limit_bytes: int | None
    status: ContainerStatus
    restart_count: int
    started_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime


class ContainerLive(ContainerRead):
    cpu_percent: float = 0.0
    cpu_cores_used: float = 0.0
    memory_working_set_bytes: int = 0
    memory_percent: float | None = None
    cpu_percent_of_limit: float | None = None
    memory_percent_of_limit: float | None = None
    net_rate_bps: float = 0.0
    io_rate_bps: float = 0.0
    uptime_seconds: float = 0.0
    energy_kwh: float = 0.0
    co2_kg: float = 0.0


class ContainerDetail(ContainerLive):
    project_name: str
    sample_count: int
    first_metric_at: datetime | None
    last_metric_at: datetime | None
