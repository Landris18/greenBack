from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContainerMetricSample(Base):
    __tablename__ = "container_metric_sample"
    __table_args__ = (
        Index("ix_container_metric_sample_container_collected", "container_id", "collected_at"),
        Index("ix_container_metric_sample_collected", "collected_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(
        ForeignKey("container.id", ondelete="CASCADE"), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    interval_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    has_previous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    cpu_total_usage_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    system_cpu_usage_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    online_cpus: Mapped[int] = mapped_column(Integer, nullable=False)
    net_rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    net_tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    blk_read_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    blk_write_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    cpu_cores_used: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cpu_percent_of_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_working_set_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    memory_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    memory_percent_of_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_rx_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_tx_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    blk_read_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    blk_write_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pids: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uptime_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class LiveSample(Base):
    __tablename__ = "live_sample"
    __table_args__ = (
        Index("ix_live_sample_container_collected", "container_id", "collected_at"),
        Index("ix_live_sample_collected", "collected_at"),
        {"prefixes": ["UNLOGGED"]},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    container_id: Mapped[int] = mapped_column(
        ForeignKey("container.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    cpu_cores_used: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cpu_percent_of_host: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cpu_percent_of_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_working_set_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    memory_percent_of_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_rate_bps: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    io_rate_bps: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    power_watts: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    energy_wh: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    co2_g: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
