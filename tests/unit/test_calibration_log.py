import csv

from app.collector.calibration_log import CHAMPS, enregistrer_echantillon


def _lire_lignes(chemin) -> list[dict]:
    with open(chemin, newline="", encoding="utf-8") as fichier:
        return list(csv.DictReader(fichier))


class TestEnregistrerEchantillon:
    def test_cree_le_fichier_avec_en_tete_puis_ajoute_une_ligne(self, tmp_path):
        chemin = tmp_path / "sous-dossier" / "journal.csv"

        enregistrer_echantillon(
            str(chemin),
            run_id="auto-test",
            horodatage="2026-01-01T00:00:00+00:00",
            mode="auto",
            source_reference="BATTERY",
            echantillon_index=0,
            intervalle_s=5.0,
            puissance_reference_w=18.62,
            puissance_rapl_brute_w=7.05,
            retenu=True,
            motif_exclusion=None,
        )

        lignes = _lire_lignes(chemin)
        assert len(lignes) == 1
        assert lignes[0]["run_id"] == "auto-test"
        assert lignes[0]["puissance_reference_w"] == "18.6200"
        assert lignes[0]["puissance_rapl_brute_w"] == "7.0500"
        assert lignes[0]["retenu"] == "1"
        assert lignes[0]["motif_exclusion"] == ""

        with open(chemin, newline="", encoding="utf-8") as fichier:
            entete = next(csv.reader(fichier))
        assert entete == CHAMPS

    def test_les_appels_successifs_s_ajoutent_sans_repeter_l_en_tete(self, tmp_path):
        chemin = tmp_path / "journal.csv"

        for index in range(3):
            enregistrer_echantillon(
                str(chemin),
                run_id="auto-test",
                horodatage="2026-01-01T00:00:00+00:00",
                mode="auto",
                source_reference="BATTERY",
                echantillon_index=index,
                intervalle_s=5.0,
                puissance_reference_w=10.0 + index,
                puissance_rapl_brute_w=4.0,
                retenu=True,
                motif_exclusion=None,
            )

        lignes = _lire_lignes(chemin)
        assert len(lignes) == 3
        assert [ligne["echantillon_index"] for ligne in lignes] == ["0", "1", "2"]

    def test_echantillon_ecarte_garde_son_motif_et_les_valeurs_manquantes_sont_vides(self, tmp_path):
        chemin = tmp_path / "journal.csv"

        enregistrer_echantillon(
            str(chemin),
            run_id="auto-test",
            horodatage="2026-01-01T00:00:00+00:00",
            mode="auto",
            source_reference="BATTERY",
            echantillon_index=0,
            intervalle_s=5.0,
            puissance_reference_w=None,
            puissance_rapl_brute_w=None,
            retenu=False,
            motif_exclusion="source_reference_indisponible",
        )

        lignes = _lire_lignes(chemin)
        assert lignes[0]["retenu"] == "0"
        assert lignes[0]["motif_exclusion"] == "source_reference_indisponible"
        assert lignes[0]["puissance_reference_w"] == ""
        assert lignes[0]["puissance_rapl_brute_w"] == ""
