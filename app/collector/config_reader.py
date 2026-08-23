import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import ConfigFileKind, ConfigFileSource
from app.host.models import Host
from app.project.models import Project, ProjectConfigFile

logger = logging.getLogger("greensi.collector")

MAX_FILE_BYTES = 512 * 1024


class ConfigAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReadFile:
    kind: ConfigFileKind
    host_path: str
    content: str
    service_name: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def translate_host_path(host_path: str, host_root: str, mount_root: str) -> Path:
    if not host_path:
        raise ConfigAccessError("Chemin vide.")

    candidate = PurePosixPath(host_path)
    root = PurePosixPath(host_root)
    if not candidate.is_absolute():
        raise ConfigAccessError(f"Chemin non absolu : {host_path}")
    if not candidate.is_relative_to(root):
        raise ConfigAccessError(
            f"Le chemin {host_path} est hors de la racine autorisée {host_root}."
        )

    return Path(mount_root) / candidate.relative_to(root)


def resolve_within(path: Path, mount_root: str) -> Path:
    root = Path(mount_root).resolve()
    try:
        resolved = path.resolve()
    except OSError as error:
        raise ConfigAccessError(f"Chemin illisible : {error}") from error

    if not resolved.is_relative_to(root):
        raise ConfigAccessError(
            "Le chemin sort de la racine autorisée après résolution des liens symboliques."
        )
    return resolved


def read_text_file(path: Path, mount_root: str) -> str:
    resolved = resolve_within(path, mount_root)
    try:
        if not resolved.is_file():
            raise ConfigAccessError(f"Fichier introuvable : {resolved}")
        if resolved.stat().st_size > MAX_FILE_BYTES:
            raise ConfigAccessError("Fichier trop volumineux pour être analyse.")
        return resolved.read_text(encoding="utf-8", errors="replace")
    except PermissionError as error:
        raise ConfigAccessError(
            "Lecture refusée par le système de fichiers. Le collecteur doit tourner avec un "
            f"utilisateur autorise a lire ce chemin ({error.strerror})."
        ) from error
    except OSError as error:
        raise ConfigAccessError(f"Fichier illisible : {error}") from error


def dockerfile_paths(compose_content: str, compose_host_path: str) -> list[tuple[str, str]]:
    try:
        document = yaml.safe_load(compose_content) or {}
    except yaml.YAMLError as error:
        raise ConfigAccessError(f"Fichier compose illisible : {error}") from error

    services = document.get("services") or {}
    if not isinstance(services, dict):
        return []

    base = PurePosixPath(compose_host_path).parent
    found: list[tuple[str, str]] = []

    for service_name, definition in services.items():
        if not isinstance(definition, dict):
            continue
        build = definition.get("build")
        if build is None:
            continue

        if isinstance(build, str):
            context, dockerfile = build, "Dockerfile"
        elif isinstance(build, dict):
            context = str(build.get("context") or ".")
            dockerfile = str(build.get("dockerfile") or "Dockerfile")
        else:
            continue

        context_path = PurePosixPath(context)
        absolute_context = context_path if context_path.is_absolute() else base / context_path
        found.append((str(service_name), str(absolute_context / dockerfile)))

    return found


def read_project_files(compose_host_path: str, host_root: str, mount_root: str) -> list[ReadFile]:
    compose_path = translate_host_path(compose_host_path, host_root, mount_root)
    compose_content = read_text_file(compose_path, mount_root)

    files = [
        ReadFile(kind=ConfigFileKind.COMPOSE, host_path=compose_host_path, content=compose_content)
    ]

    for service_name, dockerfile_host_path in dockerfile_paths(compose_content, compose_host_path):
        try:
            path = translate_host_path(dockerfile_host_path, host_root, mount_root)
            content = read_text_file(path, mount_root)
        except ConfigAccessError as error:
            logger.debug("Dockerfile ignore (%s) : %s", dockerfile_host_path, error)
            continue
        files.append(
            ReadFile(
                kind=ConfigFileKind.DOCKERFILE,
                host_path=dockerfile_host_path,
                content=content,
                service_name=service_name,
            )
        )

    return files


async def store_files(session: AsyncSession, project: Project, files: list[ReadFile]) -> int:
    now = datetime.now(UTC)
    stored = 0

    for item in files:
        statement = select(ProjectConfigFile).where(
            ProjectConfigFile.project_id == project.id,
            ProjectConfigFile.path == item.host_path,
            ProjectConfigFile.service_name.is_not_distinct_from(item.service_name),
        )
        record = (await session.execute(statement)).scalar_one_or_none()

        if record is None:
            record = ProjectConfigFile(
                project_id=project.id,
                path=item.host_path,
                service_name=item.service_name,
                kind=item.kind,
                read_at=now,
            )
            session.add(record)

        if record.content_hash != item.content_hash:
            stored += 1
        record.kind = item.kind
        record.service_name = item.service_name
        record.content = item.content
        record.content_hash = item.content_hash
        record.source = ConfigFileSource.AUTO
        record.read_at = now

    project.config_read_at = now
    project.config_error = None
    await session.flush()
    return stored


async def read_registered_projects(session: AsyncSession, host: Host) -> None:
    statement = select(Project).where(Project.host_id == host.id, Project.is_registered.is_(True))
    projects = (await session.execute(statement)).scalars().all()

    for project in projects:
        if not project.compose_path:
            project.config_error = (
                "Aucun fichier compose déclaré par Docker pour ce projet. "
                "Déposez-le manuellement depuis l'interface."
            )
            continue

        try:
            files = read_project_files(
                project.compose_path,
                settings.PROJECTS_ROOT_HOST,
                settings.PROJECTS_ROOT_MOUNT,
            )
            await store_files(session, project, files)
        except ConfigAccessError as error:
            project.config_error = str(error)
            logger.info("Lecture de configuration refusée pour %s : %s", project.name, error)

    await session.commit()
