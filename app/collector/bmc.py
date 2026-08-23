import logging
from typing import Any

import httpx

logger = logging.getLogger("greensi.collector")

CHASSIS_COLLECTION = "/redfish/v1/Chassis"


def parse_chassis_members(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    members = payload.get("Members")
    if not isinstance(members, list):
        return []
    chemins: list[str] = []
    for member in members:
        if isinstance(member, dict):
            chemin = member.get("@odata.id")
            if isinstance(chemin, str) and chemin:
                chemins.append(chemin)
    return chemins


def parse_power_payload(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None

    controls = payload.get("PowerControl")
    if isinstance(controls, list):
        for control in controls:
            if not isinstance(control, dict):
                continue
            watts = control.get("PowerConsumedWatts")
            if isinstance(watts, int | float) and watts > 0:
                return float(watts)

    watts = payload.get("PowerConsumedWatts")
    if isinstance(watts, int | float) and watts > 0:
        return float(watts)
    return None


class RedfishClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_tls: bool = True,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = (username, password) if username else None
        self._verify_tls = verify_tls
        self._timeout = timeout_seconds
        self._power_path: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def _get(self, path: str) -> Any | None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                auth=self._auth,
                verify=self._verify_tls,
                timeout=self._timeout,
            )
        try:
            response = await self._client.get(path)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Lecture Redfish impossible sur %s : %s", path, error)
            return None

    async def _resolve_power_path(self) -> str | None:
        if self._power_path is not None:
            return self._power_path

        collection = await self._get(CHASSIS_COLLECTION)
        for chassis in parse_chassis_members(collection):
            chemin = f"{chassis.rstrip('/')}/Power"
            if parse_power_payload(await self._get(chemin)) is not None:
                self._power_path = chemin
                logger.info("Source BMC active : %s%s", self._base_url, chemin)
                return chemin
        return None

    async def read_power_watts(self) -> float | None:
        chemin = await self._resolve_power_path()
        if chemin is None:
            return None
        watts = parse_power_payload(await self._get(chemin))
        if watts is None:
            self._power_path = None
        return watts

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
