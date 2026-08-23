#!/usr/bin/env python3
"""Saisie interactive d'une campagne de calibration manuelle (ex. RAPL vs wattmetre
ou batterie), enregistree paire par paire dans le meme journal CSV que la
calibration automatique du collecteur (app/collector/calibration_log.py), pour
que l'annexe du memoire dispose des valeurs individuelles verifiables, pas
seulement de la moyenne et de l'ecart-type finaux.

Usage :
    python scripts/calibration-manuelle.py [--fichier CHEMIN] [--source NOM]

A chaque etape, entrer la puissance de reference mesuree (W) puis la puissance
RAPL brute lue au meme instant (W). Ligne vide ou Ctrl+D pour terminer la
campagne ; le ratio moyen et l'ecart-type sont recalcules a la fin avec la meme
fonction que la calibration automatique (calculer_ratios).
"""

import argparse
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collector.calibration import calculer_ratios  # noqa: E402
from app.collector.calibration_log import enregistrer_echantillon  # noqa: E402

FICHIER_PAR_DEFAUT = Path(__file__).resolve().parent.parent / "data" / "calibration" / "calibration_samples.csv"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--fichier",
        default=str(FICHIER_PAR_DEFAUT),
        help="Chemin du journal CSV, partage avec la calibration automatique",
    )
    parser.add_argument(
        "--source",
        default="MANUEL",
        help="Nom de la source de reference utilisee (ex. WATTMETRE, BATTERY)",
    )
    args = parser.parse_args()

    run_id = f"manuel-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    print(f"Campagne manuelle {run_id} -- source de reference : {args.source}")
    print(f"Journal : {args.fichier}")
    print("Entrez les paires (puissance reference W, puissance RAPL brute W).")
    print("Ligne vide pour terminer.\n")

    paires: list[tuple[float, float]] = []
    index = 0
    while True:
        try:
            brut_ref = input(f"[{index}] Puissance reference (W) : ").strip()
        except EOFError:
            print()
            break
        if not brut_ref:
            break

        try:
            brut_rapl = input(f"[{index}] Puissance RAPL brute (W) : ").strip()
            reference_w = float(brut_ref.replace(",", "."))
            rapl_w = float(brut_rapl.replace(",", "."))
        except (ValueError, EOFError):
            print("  Valeur invalide, echantillon ignore.\n")
            continue

        enregistrer_echantillon(
            args.fichier,
            run_id=run_id,
            horodatage=datetime.now(UTC).isoformat(),
            mode="manuel",
            source_reference=args.source,
            echantillon_index=index,
            intervalle_s=None,
            puissance_reference_w=reference_w,
            puissance_rapl_brute_w=rapl_w,
            retenu=True,
            motif_exclusion=None,
        )
        paires.append((reference_w, rapl_w))
        index += 1

    stats = calculer_ratios(paires)
    if stats is None:
        print(f"\n{len(paires)} paire(s) enregistree(s) dans {args.fichier}, pas assez pour un ecart-type.")
        return 0

    moyenne, ecart_type, n = stats
    print(f"\n{n} paire(s) exploitable(s) enregistree(s) dans {args.fichier}")
    print(f"Ratio moyen : {moyenne:.3f} (ecart-type {ecart_type:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
