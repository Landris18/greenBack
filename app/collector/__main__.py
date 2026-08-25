import utils.session
import asyncio
import logging
import signal

from pydantic import ValidationError

from app.collector.aggregator import Aggregator, ContainerContext
from app.collector.calibration import calibrer, note_de_calibration, opportunite_de_calibration
from app.collector.config_reader import read_registered_projects
from app.collector.docker_source import DockerEngineSource
from app.collector.host_probe import HostProbe
from app.collector.stream import HttpStatsStream, StreamRegistry
from app.collector.supervisor import discover, purge_live_samples, running_docker_ids
from app.core import models  # noqa: F401
from app.core.config import settings
from app.core.database import SessionFactory
from app.host.service import get_or_create_host
from app.setting.schemas import GreenConfigUpdate
from app.setting.service import create_config_version, get_active_config

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("greensi.collector")

DISCOVERY_INTERVAL_SECONDS = 10.0
PURGE_INTERVAL_SECONDS = 60.0
REPORT_EVERY_TICKS = 30
CALIBRATION_RETRY_SECONDS = 60.0


async def bootstrap():
    async with SessionFactory() as session:
        host = await get_or_create_host(session, settings.DOCKER_HOST, settings.COLLECTOR_HOST_NAME)
        await session.commit()
        await session.refresh(host)
        return host


async def save_capabilities(host, capabilities) -> None:
    host.measurement_sources = capabilities.as_dict()
    async with SessionFactory() as session:
        await session.merge(host)
        await session.commit()


async def calibration_loop(probe: HostProbe) -> None:
    """Tente une calibration automatique du coefficient RAPL des qu'une source de
    reference (BMC, batterie ou hwmon) devient disponible en meme temps que RAPL.
    Une seule tentative par redemarrage du collecteur si la version active porte
    deja une note de calibration : on ne recalibre pas ce qui l'a deja ete."""
    async with SessionFactory() as session:
        config = await get_active_config(session)
        await session.commit()
        if config.calibration_note:
            logger.info(
                "Coefficient RAPL deja calibre (version %d), aucune nouvelle tentative.",
                config.version,
            )
            return

    while True:
        try:
            if await opportunite_de_calibration(probe) is not None:
                break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Echec de la verification d'opportunite de calibration")
        await asyncio.sleep(CALIBRATION_RETRY_SECONDS)

    logger.info(
        "Opportunite de calibration RAPL detectee, mesure en cours (~%ds).",
        int(CALIBRATION_RETRY_SECONDS),
    )
    try:
        resultat = await calibrer(probe)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Echec de la calibration automatique du coefficient RAPL")
        return

    if resultat is None or not resultat.fiable:
        return

    async with SessionFactory() as session:
        config = await get_active_config(session)
        champs = GreenConfigUpdate.model_validate(config, from_attributes=True).model_dump()
        champs["non_cpu_overhead_ratio"] = resultat.overhead_ratio
        try:
            # model_dump() puis re-validation (plutot que model_copy(update=...), qui
            # contournerait silencieusement les bornes Field(ge=..., le=...)) : un ratio
            # physiquement aberrant doit etre rejete, pas ecrit tel quel en configuration active.
            payload = GreenConfigUpdate.model_validate(champs)
        except ValidationError:
            logger.exception(
                "Coefficient RAPL calibre automatiquement hors bornes admissibles (ratio %.3f), "
                "calibration ignoree.",
                resultat.overhead_ratio,
            )
            return

        nouvelle = await create_config_version(
            session, payload, user_id=None, calibration_note=note_de_calibration(resultat)
        )
        logger.info(
            "Coefficient RAPL recalibre automatiquement : %.3f -> %.3f (version %d).",
            config.non_cpu_overhead_ratio,
            nouvelle.non_cpu_overhead_ratio,
            nouvelle.version,
        )


async def discovery_loop(host, source, registry: StreamRegistry, shared: dict) -> None:
    while True:
        try:
            async with SessionFactory() as session:
                merged = await session.merge(host)
                contexts: dict[str, ContainerContext] = await discover(session, merged, source)
                shared["contexts"] = contexts
                shared["host_cpu_cores"] = merged.cpu_cores
                await registry.sync(running_docker_ids(contexts), merged.cpu_cores or 1)
                await read_registered_projects(session, merged)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec du cycle de découverte")
        await asyncio.sleep(DISCOVERY_INTERVAL_SECONDS)


async def purge_loop(shared: dict) -> None:
    while True:
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
        try:
            async with SessionFactory() as session:
                config = await get_active_config(session)
                await session.commit()
                removed = await purge_live_samples(session, config.live_retention_minutes)
                if removed:
                    logger.debug("Purge de %d'mesures temps réel", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec de la purge des mesures temps réel")


async def tick_loop(host, probe: HostProbe, registry: StreamRegistry, shared: dict) -> None:
    aggregator: Aggregator | None = None

    while True:
        started = asyncio.get_running_loop().time()
        try:
            contexts = shared.get("contexts") or {}
            if contexts:
                async with SessionFactory() as session:
                    merged = await session.merge(host)
                    if aggregator is None:
                        aggregator = Aggregator(host=merged, probe=probe)
                    aggregator.host = merged

                    config = await get_active_config(session)
                    await session.commit()

                    result = await aggregator.tick(session, registry.snapshot(), contexts, config)

                    if aggregator.tick_index % REPORT_EVERY_TICKS == 0:
                        logger.info(
                            "%d'mesures temps réel, %.2f W (%s), %d'flux, %d'trames périmées",
                            result.live_rows,
                            result.power_watts,
                            result.power_source.value,
                            len(registry.tracked),
                            result.stale_frames,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Echec d'un cycle d'agregation")

        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0.0, 1.0 - elapsed))


async def main() -> None:
    host = await bootstrap()
    probe = HostProbe()
    await save_capabilities(host, probe.capabilities)
    source = DockerEngineSource(host.docker_url)
    stream = HttpStatsStream(host.docker_url)
    registry = StreamRegistry(stream)
    shared: dict = {"contexts": {}}

    logger.info(
        "Collector démarré sur %s en streaming 1 s (mesure matérielle %s)",
        host.docker_url,
        "active" if probe.capabilities.has_hardware_source else "indisponible",
    )

    tasks = [
        asyncio.create_task(discovery_loop(host, source, registry, shared), name="decouverte"),
        asyncio.create_task(tick_loop(host, probe, registry, shared), name="agregation"),
        asyncio.create_task(purge_loop(shared), name="purge"),
        asyncio.create_task(calibration_loop(probe), name="calibration"),
    ]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await registry.close()
    await stream.close()
    await source.close()
    await probe.aclose()
    logger.info("Collector arrêté.")


if __name__ == "__main__":
    asyncio.run(main())
