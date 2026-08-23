import asyncio
import logging
from typing import Any, Protocol

import docker
from docker.errors import DockerException

from app.collector.snapshot import ContainerSnapshot, HostInfo, build_snapshot
from app.core.config import settings

logger = logging.getLogger("greensi.collector")


class DockerUnavailableError(RuntimeError):
    pass


class DockerSource(Protocol):
    async def info(self) -> HostInfo: ...

    async def inventory(self, host_cpu_cores: int) -> list[ContainerSnapshot]: ...

    async def close(self) -> None: ...


class DockerEngineSource:
    def __init__(self, base_url: str | None = None, timeout: int | None = None) -> None:
        self._base_url = base_url or settings.DOCKER_HOST
        self._timeout = timeout or settings.DOCKER_TIMEOUT_SECONDS
        self._client: docker.DockerClient | None = None
        self._image_sizes: dict[str, int | None] = {}

    def _connect(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.DockerClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def info(self) -> HostInfo:
        try:
            raw = await asyncio.to_thread(lambda: self._connect().info())
        except DockerException as error:
            raise DockerUnavailableError(str(error)) from error

        return HostInfo(
            cpu_cores=int(raw.get("NCPU") or 0),
            total_memory_bytes=int(raw.get("MemTotal") or 0),
            os_info=f"{raw.get('OperatingSystem', '')} {raw.get('KernelVersion', '')}".strip(),
        )

    def _image_size(self, image_id: str | None) -> int | None:
        if not image_id:
            return None
        if image_id in self._image_sizes:
            return self._image_sizes[image_id]

        try:
            image = self._connect().images.get(image_id)
            size = int(image.attrs.get("Size") or 0) or None
        except DockerException:
            size = None
        self._image_sizes[image_id] = size
        return size

    def _collect(self) -> list[ContainerSnapshot]:
        client = self._connect()
        snapshots: list[ContainerSnapshot] = []

        for summary in client.api.containers(all=True):
            container_id = summary.get("Id")
            if not container_id:
                continue
            try:
                attrs: dict[str, Any] = client.api.inspect_container(container_id)
            except DockerException as error:
                logger.warning("Inspection impossible pour %s : %s", container_id[:12], error)
                continue
            snapshots.append(build_snapshot(attrs, self._image_size(attrs.get("Image"))))

        return snapshots

    async def inventory(self, host_cpu_cores: int) -> list[ContainerSnapshot]:
        try:
            return await asyncio.to_thread(self._collect)
        except DockerException as error:
            raise DockerUnavailableError(str(error)) from error

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None
