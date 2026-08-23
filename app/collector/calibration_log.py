"""Journal CSV des mesures individuelles de calibration RAPL, manuelles ou automatiques.

Une campagne de calibration (voir calibration.py) agrege des paires de mesures en un
ratio moyen et un ecart-type, mais le guide de redaction du memoire exige de pouvoir
citer les valeurs individuelles en annexe pour que l'analyse statistique soit
verifiable. Ce module ecrit donc chaque paire au fur et a mesure -- y compris les
echantillons ecartes, avec leur motif -- plutot que de ne garder que l'agregat final.
"""

import csv
import fcntl
import os
from pathlib import Path

CHAMPS = [
    "run_id",
    "horodatage",
    "mode",
    "source_reference",
    "echantillon_index",
    "intervalle_s",
    "puissance_reference_w",
    "puissance_rapl_brute_w",
    "retenu",
    "motif_exclusion",
]


def enregistrer_echantillon(
    chemin: str,
    *,
    run_id: str,
    horodatage: str,
    mode: str,
    source_reference: str,
    echantillon_index: int,
    intervalle_s: float | None,
    puissance_reference_w: float | None,
    puissance_rapl_brute_w: float | None,
    retenu: bool,
    motif_exclusion: str | None,
) -> None:
    """Ajoute une ligne au journal CSV, en creant le fichier et son en-tete si
    necessaire. Un verrou de fichier (fcntl) protege l'ecriture si une campagne
    manuelle (scripts/calibration-manuelle.py) et le collecteur automatique
    ecrivent en meme temps."""
    path = Path(chemin)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", newline="", encoding="utf-8") as fichier:
        fcntl.flock(fichier.fileno(), fcntl.LOCK_EX)
        try:
            vide = os.fstat(fichier.fileno()).st_size == 0
            ecrivain = csv.writer(fichier)
            if vide:
                ecrivain.writerow(CHAMPS)
            ecrivain.writerow(
                [
                    run_id,
                    horodatage,
                    mode,
                    source_reference,
                    echantillon_index,
                    "" if intervalle_s is None else f"{intervalle_s:.3f}",
                    "" if puissance_reference_w is None else f"{puissance_reference_w:.4f}",
                    "" if puissance_rapl_brute_w is None else f"{puissance_rapl_brute_w:.4f}",
                    int(retenu),
                    motif_exclusion or "",
                ]
            )
            fichier.flush()
        finally:
            fcntl.flock(fichier.fileno(), fcntl.LOCK_UN)
