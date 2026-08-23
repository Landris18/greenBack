from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import PowerSource


class EnergySample(Base):
    __tablename__ = "energy_sample"
    __table_args__ = (
        Index("ix_energy_sample_container_collected", "container_id", "collected_at"),
        Index("ix_energy_sample_project_collected", "project_id", "collected_at"),
        Index("ix_energy_sample_host_collected", "host_id", "collected_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("host.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=True
    )
    container_id: Mapped[int | None] = mapped_column(
        ForeignKey("container.id", ondelete="CASCADE"), nullable=True
    )
    green_config_id: Mapped[int] = mapped_column(
        ForeignKey("green_config.id", ondelete="RESTRICT"), nullable=False
    )

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    interval_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    share_ratio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    power_watts: Mapped[float] = mapped_column(Float, nullable=False)
    energy_wh: Mapped[float] = mapped_column(Float, nullable=False)
    co2_g: Mapped[float] = mapped_column(Float, nullable=False)
    power_source: Mapped[PowerSource] = mapped_column(
        Enum(PowerSource, name="power_source"), nullable=False
    )
    is_overhead: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
