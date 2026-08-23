from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import ContainerStatus


class Container(Base, TimestampMixin):
    __tablename__ = "container"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_container_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    service_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    docker_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    image_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cpu_limit_cores: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[ContainerStatus] = mapped_column(
        Enum(ContainerStatus, name="container_status"),
        default=ContainerStatus.UNKNOWN,
        nullable=False,
    )
    restart_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    labels: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    project: Mapped["Project"] = relationship(lazy="selectin")  # noqa: F821
