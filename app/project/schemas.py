from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ConfigFileKind, ConfigFileSource, ResourceStatus
from app.host.schemas import HostRead


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    host_id: int
    name: str
    display_name: str | None
    is_registered: bool
    compose_path: str | None
    working_dir: str | None
    config_read_at: datetime | None
    config_error: str | None
    status: ResourceStatus
    first_seen_at: datetime
    last_seen_at: datetime
    last_sync_at: datetime | None
    host: HostRead | None = None


class ProjectSummary(BaseModel):
    project: ProjectRead
    container_count: int
    running_count: int
    cpu_percent_of_host: float
    memory_bytes: int
    power_watts: float
    energy_kwh: float
    co2_kg: float
    recommendation_count: int
    critical_count: int
    has_live_data: bool


class ProjectUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    is_registered: bool | None = None


class ConfigFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    kind: ConfigFileKind
    path: str
    service_name: str | None
    content: str
    content_hash: str
    source: ConfigFileSource
    read_at: datetime


class ConfigFileUpload(BaseModel):
    kind: ConfigFileKind
    path: str = Field(min_length=1, max_length=1024)
    service_name: str | None = None
    content: str = Field(min_length=1)


class ProjectConfigStatus(BaseModel):
    project_id: int
    is_registered: bool
    compose_path: str | None
    config_read_at: datetime | None
    config_error: str | None
    files: list[ConfigFileRead]
