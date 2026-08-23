from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin
from app.core.enums import PowerSource, ResourceStatus


class Host(Base, TimestampMixin):
    __tablename__ = "host"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    docker_url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    cpu_cores: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_memory_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    os_info: Mapped[str | None] = mapped_column(String(512), nullable=True)
    power_source: Mapped[PowerSource] = mapped_column(
        Enum(PowerSource, name="power_source"), default=PowerSource.MODEL, nullable=False
    )
    status: Mapped[ResourceStatus] = mapped_column(
        Enum(ResourceStatus, name="resource_status"), default=ResourceStatus.UNKNOWN, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    measurement_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class HostMetricSample(Base):
    __tablename__ = "host_metric_sample"
    __table_args__ = (Index("ix_host_metric_sample_host_collected", "host_id", "collected_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("host.id", ondelete="CASCADE"), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    interval_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False)
    memory_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rapl_energy_uj: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    power_watts: Mapped[float] = mapped_column(Float, nullable=False)
    idle_power_watts: Mapped[float] = mapped_column(Float, nullable=False)
    dynamic_power_watts: Mapped[float] = mapped_column(Float, nullable=False)
    power_source: Mapped[PowerSource] = mapped_column(
        Enum(PowerSource, name="power_source"), nullable=False
    )
    has_previous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
