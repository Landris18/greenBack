import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from app.collector.bmc import RedfishClient
from app.core.config import settings
from app.core.enums import PowerSource
from app.energy.model import (
    DEFAULT_RAPL_MAX_RANGE_UJ,
    host_power_from_battery,
    host_power_from_hwmon,
    host_power_from_rapl,
    rapl_delta_uj,
    select_rapl_zones,
)

logger = logging.getLogger("greensi.collector")

BATTERY_NAME_PREFIX = "bat"
RAPL_ZONE_PREFIX = "intel-rapl:"


@dataclass(frozen=True)
class HostReading:
    cpu_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    rapl_energy_uj: int | None
    measured_watts: float | None
    measured_source: PowerSource | None
    io_rate_bps: float
    net_rate_bps: float


@dataclass(frozen=True)
class RaplZone:
    name: str
    energy_path: Path
    max_range_uj: int


@dataclass(frozen=True)
class BatterySensor:
    name: str
    root: Path


@dataclass(frozen=True)
class HwmonSensor:
    name: str
    input_path: Path


@dataclass(frozen=True)
class MeasurementCapabilities:
    virtualized: bool = False
    bmc: bool = False
    battery: bool = False
    hwmon: bool = False
    rapl: bool = False
    rapl_zones: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "virtualized": self.virtualized,
            "bmc": self.bmc,
            "battery": self.battery,
            "hwmon": self.hwmon,
            "rapl": self.rapl,
            "rapl_zones": list(self.rapl_zones),
        }

    @property
    def has_hardware_source(self) -> bool:
        return self.bmc or self.battery or self.hwmon or self.rapl


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def is_virtualized(procfs_path: str) -> bool:
    cpuinfo = Path(procfs_path) / "cpuinfo"
    try:
        contenu = cpuinfo.read_text()
    except OSError:
        return False
    for ligne in contenu.splitlines():
        if ligne.startswith("flags") and " hypervisor" in f" {ligne}":
            return True
    return False


def control_roots(base: Path) -> list[Path]:
    racines = [base]
    try:
        enfants = sorted(entree for entree in base.iterdir() if entree.is_dir())
    except OSError:
        return racines
    racines.extend(entree for entree in enfants if not entree.name.startswith(RAPL_ZONE_PREFIX))
    return sorted(racines, key=lambda chemin: ("mmio" in chemin.name, chemin.name))


def zones_under(racine: Path) -> dict[str, RaplZone]:
    candidates: dict[str, RaplZone] = {}
    motif = f"{RAPL_ZONE_PREFIX}*"
    for zone in sorted(racine.glob(motif)) + sorted(racine.glob(f"{motif}/{motif}")):
        energy_path = zone / "energy_uj"
        if not energy_path.is_file() or not os.access(energy_path, os.R_OK):
            continue
        name = read_text(zone / "name")
        if not name:
            continue
        max_range = read_int(zone / "max_energy_range_uj") or DEFAULT_RAPL_MAX_RANGE_UJ
        candidates[name] = RaplZone(name=name, energy_path=energy_path, max_range_uj=max_range)
    return candidates


def discover_rapl_zones(root: str) -> list[RaplZone]:
    base = Path(root)
    if not base.is_dir():
        return []

    for racine in control_roots(base):
        candidates = zones_under(racine)
        retenues = select_rapl_zones(candidates)
        if retenues:
            return [candidates[name] for name in retenues]
    return []


def discover_battery(root: str) -> BatterySensor | None:
    base = Path(root)
    if not base.is_dir():
        return None

    for entree in sorted(base.iterdir()):
        if read_text(entree / "type") != "Battery":
            continue
        if not (entree / "status").is_file():
            continue
        if not (entree / "power_now").is_file() and not (entree / "current_now").is_file():
            continue
        return BatterySensor(name=entree.name, root=entree)
    return None


def discover_hwmon(root: str) -> list[HwmonSensor]:
    base = Path(root)
    if not base.is_dir():
        return []

    capteurs: list[HwmonSensor] = []
    for entree in sorted(base.iterdir()):
        name = read_text(entree / "name")
        if not name or name.lower().startswith(BATTERY_NAME_PREFIX):
            continue
        if read_text(entree / "device" / "type") == "Battery":
            continue
        for input_path in sorted(entree.glob("power*_input")):
            if os.access(input_path, os.R_OK):
                capteurs.append(HwmonSensor(name=name, input_path=input_path))
    return capteurs


class HostProbe:
    def __init__(self) -> None:
        self._previous_io: tuple[int, int] | None = None
        self._previous_net: tuple[int, int] | None = None
        self._previous_rapl: dict[str, int] = {}
        self._previous_rapl_calibration: dict[str, int] = {}
        self._bmc_watts: float | None = None
        self._bmc_read_at: float = 0.0
        psutil.cpu_percent(interval=None)

        self._rapl_zones = discover_rapl_zones(settings.rapl_path)
        self._battery = discover_battery(settings.power_supply_path)
        self._hwmon = discover_hwmon(settings.hwmon_path)
        self._bmc = (
            RedfishClient(
                base_url=settings.BMC_REDFISH_URL,
                username=settings.BMC_USERNAME,
                password=settings.BMC_PASSWORD,
                verify_tls=settings.BMC_VERIFY_TLS,
                timeout_seconds=settings.BMC_TIMEOUT_SECONDS,
            )
            if settings.BMC_REDFISH_URL
            else None
        )

        self.capabilities = MeasurementCapabilities(
            virtualized=is_virtualized(settings.PROCFS_PATH),
            bmc=self._bmc is not None,
            battery=self._battery is not None,
            hwmon=bool(self._hwmon),
            rapl=bool(self._rapl_zones),
            rapl_zones=[zone.name for zone in self._rapl_zones],
        )
        self._log_capabilities()

    def _log_capabilities(self) -> None:
        if not self.capabilities.has_hardware_source:
            raison = (
                "invité de virtualisation, aucun capteur matériel exposé"
                if self.capabilities.virtualized
                else "aucun capteur matériel accessible"
            )
            logger.warning(
                "Mesure matérielle indisponible (%s). Bascule sur le modèle énergétique.", raison
            )
            return

        logger.info(
            "Capteurs détectés : BMC %s, batterie %s, hwmon %s, RAPL %s",
            "oui" if self.capabilities.bmc else "non",
            self._battery.name if self._battery else "non",
            ", ".join(sorted({capteur.name for capteur in self._hwmon})) or "non",
            ", ".join(self.capabilities.rapl_zones) or "non",
        )

    async def _read_bmc(self) -> float | None:
        if self._bmc is None:
            return None
        maintenant = time.monotonic()
        if maintenant - self._bmc_read_at < settings.BMC_POLL_SECONDS and self._bmc_watts:
            return self._bmc_watts
        self._bmc_watts = await self._bmc.read_power_watts()
        self._bmc_read_at = maintenant
        return self._bmc_watts

    def _read_battery(self) -> float | None:
        if self._battery is None:
            return None
        racine = self._battery.root
        return host_power_from_battery(
            power_now_uw=read_int(racine / "power_now"),
            status=read_text(racine / "status"),
            current_now_ua=read_int(racine / "current_now"),
            voltage_now_uv=read_int(racine / "voltage_now"),
        )

    def _read_hwmon(self) -> float | None:
        mesures = [
            watts
            for capteur in self._hwmon
            if (watts := host_power_from_hwmon(read_int(capteur.input_path))) is not None
        ]
        return max(mesures) if mesures else None

    def _read_rapl(self, previous: dict[str, int] | None = None) -> tuple[int | None, int | None]:
        """previous est le magasin d'etat a utiliser pour le delta. Par defaut
        celui du cycle d'agregation principal ; un appelant independant (la
        calibration) doit fournir le sien pour ne pas se desynchroniser avec
        les lectures a 1s du cycle principal."""
        if not self._rapl_zones:
            return None, None
        etat = self._previous_rapl if previous is None else previous

        total_uj = 0
        delta_total_uj = 0
        complet = True

        for zone in self._rapl_zones:
            courant = read_int(zone.energy_path)
            if courant is None:
                complet = False
                continue
            total_uj += courant
            delta = rapl_delta_uj(courant, etat.get(zone.name), zone.max_range_uj)
            etat[zone.name] = courant
            if delta is None:
                complet = False
                continue
            delta_total_uj += delta

        if not complet or delta_total_uj <= 0:
            return (total_uj or None), None
        return total_uj, delta_total_uj

    async def read_reference_source(self) -> tuple[PowerSource, float] | None:
        """Source de mesure hors RAPL, utilisee pour calibrer le coefficient RAPL :
        la premiere, par ordre de perimetre decroissant, qui renvoie une valeur exploitable."""
        for candidat, source in (
            (await self._read_bmc(), PowerSource.BMC),
            (self._read_battery(), PowerSource.BATTERY),
            (self._read_hwmon(), PowerSource.HWMON),
        ):
            if candidat is not None and candidat > 0:
                return source, candidat
        return None

    def read_rapl_raw_delta_uj(self) -> int | None:
        """Delta RAPL brut en microjoules depuis le dernier appel de calibration.
        Etat independant de celui du cycle d'agregation principal (voir _read_rapl),
        pour que les lectures a 1s de ce dernier ne faussent pas le delta calcule ici.
        None si RAPL est indisponible ou si c'est le premier appel."""
        _, delta = self._read_rapl(previous=self._previous_rapl_calibration)
        return delta

    async def read(self, interval_seconds: float, non_cpu_overhead_ratio: float) -> HostReading:
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()

        io_rate = 0.0
        counters = psutil.disk_io_counters()
        if counters is not None:
            current_io = (counters.read_bytes, counters.write_bytes)
            if self._previous_io is not None and interval_seconds > 0:
                delta = sum(current_io) - sum(self._previous_io)
                io_rate = max(0.0, delta / interval_seconds)
            self._previous_io = current_io

        net_rate = 0.0
        net = psutil.net_io_counters()
        if net is not None:
            current_net = (net.bytes_recv, net.bytes_sent)
            if self._previous_net is not None and interval_seconds > 0:
                delta = sum(current_net) - sum(self._previous_net)
                net_rate = max(0.0, delta / interval_seconds)
            self._previous_net = current_net

        rapl_energy_uj, rapl_delta = self._read_rapl()
        rapl_watts = (
            host_power_from_rapl(rapl_delta, interval_seconds, non_cpu_overhead_ratio)
            if rapl_delta is not None
            else None
        )

        watts: float | None = None
        source: PowerSource | None = None

        for candidat, candidat_source in (
            (await self._read_bmc(), PowerSource.BMC),
            (self._read_battery(), PowerSource.BATTERY),
            (self._read_hwmon(), PowerSource.HWMON),
            (rapl_watts, PowerSource.RAPL),
        ):
            if candidat is not None and candidat > 0:
                watts = candidat
                source = candidat_source
                break

        return HostReading(
            cpu_percent=cpu_percent,
            memory_used_bytes=int(memory.total - memory.available),
            memory_total_bytes=int(memory.total),
            rapl_energy_uj=rapl_energy_uj,
            measured_watts=watts,
            measured_source=source,
            io_rate_bps=io_rate,
            net_rate_bps=net_rate,
        )

    async def aclose(self) -> None:
        if self._bmc is not None:
            await self._bmc.aclose()
