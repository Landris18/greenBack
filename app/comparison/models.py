from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class Comparison(Base, TimestampMixin):
    __tablename__ = "comparison"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_a_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    project_b_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    period_a_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_a_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_b_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_b_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
