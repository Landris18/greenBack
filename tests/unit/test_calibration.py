import pytest

from app.collector.calibration import (
    DISPERSION_RELATIVE_MAX,
    NB_ECHANTILLONS,
    ResultatCalibration,
    calculer_ratios,
    calibrer,
    note_de_calibration,
    opportunite_de_calibration,
)
from app.core.config import settings
from app.core.enums import PowerSource


@pytest.fixture(autouse=True)
def _journal_calibration_temporaire(tmp_path, monkeypatch):
    """calibrer() journalise chaque echantillon sur disque (voir calibration_log.py) :
    on redirige ce journal vers un fichier temporaire pour ne pas ecrire dans
    CALIBRATION_LOG_PATH (chemin de conteneur, non accessible en test)."""
    monkeypatch.setattr(settings, "CALIBRATION_LOG_PATH", str(tmp_path / "calibration_samples.csv"))


class TestCalculerRatios:
    def test_moyenne_et_ecart_type(self):
        moyenne, ecart_type, n = calculer_ratios([(20.0, 8.0), (24.0, 8.0), (16.0, 8.0)])
        assert moyenne == pytest.approx(2.5)
        assert ecart_type == pytest.approx(0.5)
        assert n == 3

    def test_rapl_nul_est_ignore(self):
        # (24.0, 0.0) est ecarte : il ne reste qu'une seule paire exploitable,
        # insuffisant pour calculer un ecart-type.
        assert calculer_ratios([(20.0, 8.0), (24.0, 0.0)]) is None

    def test_moins_de_deux_paires_exploitables_renvoie_none(self):
        assert calculer_ratios([(20.0, 8.0)]) is None
        assert calculer_ratios([]) is None


class TestResultatCalibration:
    def test_dispersion_relative(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY, ratio_moyen=2.0, ecart_type=0.4, nb_echantillons=5
        )
        assert resultat.dispersion_relative == pytest.approx(0.2)

    def test_dispersion_relative_ratio_nul(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY, ratio_moyen=0.0, ecart_type=0.0, nb_echantillons=5
        )
        assert resultat.dispersion_relative == float("inf")

    def test_fiable_si_assez_d_echantillons_et_peu_de_dispersion(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY, ratio_moyen=2.65, ecart_type=0.16, nb_echantillons=8
        )
        assert resultat.fiable is True

    def test_pas_fiable_si_trop_peu_d_echantillons(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY, ratio_moyen=2.65, ecart_type=0.16, nb_echantillons=2
        )
        assert resultat.fiable is False

    def test_pas_fiable_si_trop_disperse(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY,
            ratio_moyen=2.0,
            ecart_type=2.0 * DISPERSION_RELATIVE_MAX + 0.5,
            nb_echantillons=8,
        )
        assert resultat.fiable is False

    def test_overhead_ratio(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY, ratio_moyen=2.65, ecart_type=0.16, nb_echantillons=8
        )
        assert resultat.overhead_ratio == pytest.approx(1.65)

    def test_overhead_ratio_ne_descend_pas_sous_zero(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY, ratio_moyen=0.5, ecart_type=0.1, nb_echantillons=8
        )
        assert resultat.overhead_ratio == 0.0


class TestNoteDeCalibration:
    def test_contient_les_chiffres_cles(self):
        resultat = ResultatCalibration(
            PowerSource.BATTERY, ratio_moyen=2.65, ecart_type=0.16, nb_echantillons=12
        )
        note = note_de_calibration(resultat)
        assert "BATTERY" in note
        assert "2.650" in note
        assert "0.160" in note
        assert "12" in note


class FakeProbe:
    """Simule HostProbe pour les tests : renvoie des valeurs de reference et RAPL
    controlees, sans dependre du materiel."""

    def __init__(self, reference: tuple[PowerSource, float] | None, rapl_deltas: list[int | None]):
        self.rapl_available = True
        self._reference = reference
        self._rapl_deltas = list(rapl_deltas)

        class Capabilities:
            rapl = True

        self.capabilities = Capabilities()

    async def read_reference_source(self):
        return self._reference

    def read_rapl_raw_delta_uj(self):
        return self._rapl_deltas.pop(0) if self._rapl_deltas else None


class TestOpportuniteDeCalibration:
    async def test_aucune_opportunite_sans_rapl(self):
        probe = FakeProbe(reference=(PowerSource.BATTERY, 15.0), rapl_deltas=[])
        probe.capabilities.rapl = False
        assert await opportunite_de_calibration(probe) is None

    async def test_aucune_opportunite_sans_source_de_reference(self):
        probe = FakeProbe(reference=None, rapl_deltas=[])
        assert await opportunite_de_calibration(probe) is None

    async def test_opportunite_detectee(self):
        probe = FakeProbe(reference=(PowerSource.BATTERY, 15.0), rapl_deltas=[])
        assert await opportunite_de_calibration(probe) == PowerSource.BATTERY


class TestCalibrer:
    async def test_renvoie_none_sans_opportunite(self):
        probe = FakeProbe(reference=None, rapl_deltas=[])
        assert await calibrer(probe) is None

    async def test_calcule_un_resultat_fiable_sur_des_echantillons_coherents(self, monkeypatch):
        import app.collector.calibration as calibration

        monkeypatch.setattr(calibration, "INTERVALLE_SECONDES", 0.001)
        deltas = [8_000_000] * (NB_ECHANTILLONS + 1)
        probe = FakeProbe(reference=(PowerSource.BATTERY, 20.0), rapl_deltas=deltas)

        resultat = await calibrer(probe)

        assert resultat is not None
        assert resultat.source_reference == PowerSource.BATTERY
        assert resultat.nb_echantillons >= 2

    async def test_ecarte_les_echantillons_dont_la_source_change(self, monkeypatch):
        import app.collector.calibration as calibration

        monkeypatch.setattr(calibration, "INTERVALLE_SECONDES", 0.001)

        class SourceChangeanteProbe(FakeProbe):
            def __init__(self):
                super().__init__(
                    reference=(PowerSource.BATTERY, 20.0),
                    rapl_deltas=[8_000_000] * (NB_ECHANTILLONS + 1),
                )
                self._appel = 0

            async def read_reference_source(self):
                self._appel += 1
                if self._appel % 2 == 0:
                    return PowerSource.HWMON, 20.0
                return PowerSource.BATTERY, 20.0

        resultat = await calibrer(SourceChangeanteProbe())
        assert resultat is None or resultat.nb_echantillons < NB_ECHANTILLONS
