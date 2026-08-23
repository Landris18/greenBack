from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import ConfigFileKind, ConfigFileSource, ResourceStatus

UNGROUPED_PROJECT_NAME = "Hors projet"


class Project(Base, TimestampMixin):
    __tablename__ = "project"
    __table_args__ = (UniqueConstraint("host_id", "name", name="uq_project_host_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(
        ForeignKey("host.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    compose_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    working_dir: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    config_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ResourceStatus] = mapped_column(
        Enum(ResourceStatus, name="resource_status"), default=ResourceStatus.UNKNOWN, nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    host: Mapped["Host"] = relationship(lazy="selectin")  # noqa: F821
    config_files: Mapped[list["ProjectConfigFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


class ProjectConfigFile(Base, TimestampMixin):
    __tablename__ = "project_config_file"
    __table_args__ = (
        Index(
            "uq_config_file_project_path_service",
            "project_id",
            "path",
            "service_name",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ConfigFileKind] = mapped_column(
        Enum(ConfigFileKind, name="config_file_kind"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    service_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[ConfigFileSource] = mapped_column(
        Enum(ConfigFileSource, name="config_file_source"),
        default=ConfigFileSource.AUTO,
        nullable=False,
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="config_files")
