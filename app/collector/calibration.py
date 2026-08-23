"""Calibration automatique du coefficient de majoration RAPL (non_cpu_overhead_ratio).

RAPL ne mesure que le domaine processeur. Sur toute machine qui expose en plus une
source couvrant un perimetre plus large (BMC, batterie, hwmon), on peut comparer les
deux simultanement pour estimer le coefficient reel, au lieu de garder une valeur
par defaut non verifiee. Voir la campagne manuelle qui a etabli le protocole ci-dessous
(12 mesures, ratio 2.65, ecart-type 0.16).

Chaque paire de mesures, retenue ou ecartee, est journalisee individuellement par
app.collector.calibration_log (voir CALIBRATION_LOG_PATH) au fur et a mesure de la
campagne -- automatique ici, ou manuelle via scripts/calibration-manuelle.py -- pour
que les valeurs brutes derriere le ratio moyen et l'ecart-type restent verifiables.
"""

import asyncio
import logging
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.collector.calibration_log import enregistrer_echantillon
from app.collector.host_probe import HostProbe
from app.core.config import settings
from app.core.enums import PowerSource

logger = logging.getLogger("greensi.collector")

NB_ECHANTILLONS = 8
INTERVALLE_SECONDES = 5.0
DISPERSION_RELATIVE_MAX = 0.30


@dataclass(frozen=True)
class ResultatCalibration:
    source_reference: PowerSource
    ratio_moyen: float
    ecart_type: float
    nb_echantillons: int

    @property
    def dispersion_relative(self) -> float:
        return self.ecart_type / self.ratio_moyen if self.ratio_moyen else float("inf")

    @property
    def fiable(self) -> bool:
        return self.nb_echantillons >= 3 and self.dispersion_relative <= DISPERSION_RELATIVE_MAX

    @property
    def overhead_ratio(self) -> float:
        """Coefficient equivalent pour host_power_from_rapl (ratio - 1)."""
        return max(0.0, self.ratio_moyen - 1.0)


def calculer_ratios(paires: list[tuple[float, float]]) -> tuple[float, float, int] | None:
    """paires = [(watts_reference, watts_rapl_brut), ...]. Moyenne et ecart-type du ratio."""
    ratios = [reference / rapl for reference, rapl in paires if rapl > 0]
    if len(ratios) < 2:
        return None
    return statistics.mean(ratios), statistics.stdev(ratios), len(ratios)


async def opportunite_de_calibration(probe: HostProbe) -> PowerSource | None:
    """La calibration n'a de sens que si RAPL ET une source de reference plus large
    sont exploitables au meme instant. Renvoie la source de reference si c'est le cas."""
    if not probe.capabilities.rapl:
        return None
    reference = await probe.read_reference_source()
    return reference[0] if reference else None


async def calibrer(probe: HostProbe) -> ResultatCalibration | None:
    """Compare RAPL brut (sans majoration) a la premiere source de reference disponible,
    sur NB_ECHANTILLONS mesures appariees espacees de INTERVALLE_SECONDES. Renvoie None
    si aucune paire de sources n'est exploitable, ou si trop peu d'echantillons aboutissent."""
    source_attendue = await opportunite_de_calibration(probe)
    if source_attendue is None:
        return None

    probe.read_rapl_raw_delta_uj()  # amorce le compteur : le premier appel ne rend pas de delta
    t_precedent = time.monotonic()

    run_id = f"auto-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"

    paires: list[tuple[float, float]] = []
    for index in range(NB_ECHANTILLONS):
        await asyncio.sleep(INTERVALLE_SECONDES)

        t_maintenant = time.monotonic()
        intervalle = t_maintenant - t_precedent
        t_precedent = t_maintenant

        delta_uj = probe.read_rapl_raw_delta_uj()
        reference = await probe.read_reference_source()

        rapl_watts_brut = (
            (delta_uj / 1_000_000.0) / intervalle
            if delta_uj is not None and delta_uj > 0 and intervalle > 0
            else None
        )
        reference_watts = reference[1] if reference is not None else None

        motif_exclusion: str | None = None
        retenu = False
        if delta_uj is None or delta_uj <= 0:
            motif_exclusion = "delta_rapl_invalide"
        elif intervalle <= 0:
            motif_exclusion = "intervalle_invalide"
        elif reference is None:
            motif_exclusion = "source_reference_indisponible"
        elif reference[0] != source_attendue:
            motif_exclusion = "source_reference_changee"  # source de reference changee en cours de route
        else:
            retenu = True
            paires.append((reference[1], rapl_watts_brut))

        enregistrer_echantillon(
            settings.CALIBRATION_LOG_PATH,
            run_id=run_id,
            horodatage=datetime.now(UTC).isoformat(),
            mode="auto",
            source_reference=source_attendue.value,
            echantillon_index=index,
            intervalle_s=intervalle,
            puissance_reference_w=reference_watts,
            puissance_rapl_brute_w=rapl_watts_brut,
            retenu=retenu,
            motif_exclusion=motif_exclusion,
        )

    stats = calculer_ratios(paires)
    if stats is None:
        logger.warning(
            "Calibration RAPL/%s : pas assez d'echantillons exploitables (%d/%d).",
            source_attendue.value,
            len(paires),
            NB_ECHANTILLONS,
        )
        return None

    moyenne, ecart_type, n = stats
    resultat = ResultatCalibration(source_attendue, moyenne, ecart_type, n)
    logger.info(
        "Calibration RAPL/%s : ratio moyen %.3f (ecart-type %.3f, dispersion %.0f%%, n=%d/%d)%s",
        source_attendue.value,
        moyenne,
        ecart_type,
        resultat.dispersion_relative * 100,
        n,
        NB_ECHANTILLONS,
        "" if resultat.fiable else " -- jugee trop bruitee, non appliquee",
    )
    return resultat


def note_de_calibration(resultat: ResultatCalibration) -> str:
    return (
        f"Calibration automatique : RAPL vs {resultat.source_reference.value}, "
        f"ratio moyen {resultat.ratio_moyen:.3f} (ecart-type {resultat.ecart_type:.3f}, "
        f"dispersion {resultat.dispersion_relative * 100:.0f}%, "
        f"{resultat.nb_echantillons} echantillons)."
    )
