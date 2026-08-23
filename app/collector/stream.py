import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from app.collector.frame import StatsFrame, parse_stats_frame
from app.core.config import settings

logger = logging.getLogger("greensi.collector")

RECONNECT_BASE_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0


class StatsStream(Protocol):
    def frames(self, docker_id: str, host_cpu_cores: int) -> AsyncIterator[StatsFrame]: ...


def base_url_from_docker_host(docker_host: str) -> str:
    if docker_host.startswith("tcp://"):
        return docker_host.replace("tcp://", "http://", 1)
    if docker_host.startswith(("http://", "https://")):
        return docker_host
    raise ValueError(
        "Le streaming des statistiques exige un endpoint Docker en TCP, "
        f"valeur reçue : {docker_host}"
    )


class HttpStatsStream:
    def __init__(self, docker_host: str | None = None) -> None:
        self._base_url = base_url_from_docker_host(docker_host or settings.DOCKER_HOST)
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=None)

    async def frames(self, docker_id: str, host_cpu_cores: int) -> AsyncIterator[StatsFrame]:
        url = f"/containers/{docker_id}/stats?stream=true"
        async with self._client.stream("GET", url) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                frame = parse_stats_frame(line, docker_id, host_cpu_cores)
                if frame is not None:
                    yield frame

    async def close(self) -> None:
        await self._client.aclose()


class StreamRegistry:
    def __init__(self, stream: StatsStream) -> None:
        self._stream = stream
        self._tasks: dict[str, asyncio.Task] = {}
        self._latest: dict[str, StatsFrame] = {}

    @property
    def tracked(self) -> set[str]:
        return set(self._tasks)

    def latest(self, docker_id: str) -> StatsFrame | None:
        return self._latest.get(docker_id)

    def snapshot(self) -> dict[str, StatsFrame]:
        return dict(self._latest)

    async def _run(self, docker_id: str, host_cpu_cores: int) -> None:
        delay = RECONNECT_BASE_SECONDS
        while True:
            try:
                async for frame in self._stream.frames(docker_id, host_cpu_cores):
                    self._latest[docker_id] = frame
                    delay = RECONNECT_BASE_SECONDS
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "Flux interrompu pour %s (%s). Nouvelle tentative dans %.0f s.",
                    docker_id[:12],
                    error,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_SECONDS)

    def start(self, docker_id: str, host_cpu_cores: int) -> None:
        if docker_id in self._tasks:
            return
        self._tasks[docker_id] = asyncio.create_task(
            self._run(docker_id, host_cpu_cores), name=f"stats-{docker_id[:12]}"
        )

    def stop(self, docker_id: str) -> None:
        task = self._tasks.pop(docker_id, None)
        if task is not None:
            task.cancel()
        self._latest.pop(docker_id, None)

    async def sync(self, docker_ids: set[str], host_cpu_cores: int) -> None:
        for docker_id in docker_ids - self.tracked:
            self.start(docker_id, host_cpu_cores)
        for docker_id in self.tracked - docker_ids:
            self.stop(docker_id)

    async def close(self) -> None:
        for docker_id in list(self._tasks):
            self.stop(docker_id)
        await asyncio.gather(*[], return_exceptions=True)
