from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import (
    Difficulty,
    RecommendationSource,
    RecommendationStatus,
    RuleCode,
    Severity,
)


class Recommendation(Base, TimestampMixin):
    __tablename__ = "recommendation"
    __table_args__ = (
        Index(
            "uq_recommendation_open",
            "project_id",
            "container_id",
            "rule_code",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
        Index("ix_recommendation_project_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    container_id: Mapped[int | None] = mapped_column(
        ForeignKey("container.id", ondelete="CASCADE"), nullable=True
    )
    rule_code: Mapped[RuleCode] = mapped_column(Enum(RuleCode, name="rule_code"), nullable=False)
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), nullable=False)
    difficulty: Mapped[Difficulty] = mapped_column(
        Enum(Difficulty, name="difficulty"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    current_value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    suggested_value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    estimated_energy_saving_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_co2_saving_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    saving_is_computed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    saving_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(RecommendationStatus, name="recommendation_status"),
        default=RecommendationStatus.OPEN,
        nullable=False,
    )
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[RecommendationSource] = mapped_column(
        Enum(RecommendationSource, name="recommendation_source"),
        default=RecommendationSource.RUNTIME,
        nullable=False,
    )
    patch: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    container: Mapped["Container | None"] = relationship(lazy="selectin")  # noqa: F821
