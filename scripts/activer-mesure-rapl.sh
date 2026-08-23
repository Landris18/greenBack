#!/usr/bin/env bash
set -euo pipefail

GROUPE="greensi-rapl"
REGLE="/etc/udev/rules.d/99-greensi-rapl.rules"
POWERCAP="/sys/devices/virtual/powercap"

if [[ $EUID -ne 0 ]]; then
    echo "Ce script doit être lancé avec sudo." >&2
    exit 1
fi

if [[ ! -d "$POWERCAP" ]] || [[ -z "$(find "$POWERCAP" -name energy_uj -print -quit 2>/dev/null)" ]]; then
    echo "Aucune zone RAPL sur cette machine." >&2
    echo "C'est le cas des machines virtuelles et de certains processeurs." >&2
    echo "GreenSI utilisera une autre source de mesure ou le modèle énergétique." >&2
    exit 2
fi

if ! getent group "$GROUPE" > /dev/null; then
    groupadd --system "$GROUPE"
    echo "Groupe $GROUPE créé."
fi

GID=$(getent group "$GROUPE" | cut -d: -f3)

cat > "$REGLE" <<EOF
SUBSYSTEM=="powercap", ACTION=="add|change", RUN+="/usr/bin/chgrp -f $GROUPE /sys\$devpath/energy_uj", RUN+="/usr/bin/chmod -f g+r /sys\$devpath/energy_uj"
EOF

echo "Règle udev installée dans $REGLE."

find "$POWERCAP" -name energy_uj -exec chgrp "$GROUPE" {} +
find "$POWERCAP" -name energy_uj -exec chmod g+r {} +

udevadm control --reload-rules > /dev/null 2>&1 || true
udevadm trigger --subsystem-match=powercap > /dev/null 2>&1 || true

echo
echo "Zones RAPL désormais lisibles :"
find "$POWERCAP" -name energy_uj -printf '%h\n' | while read -r zone; do
    printf '    %-12s %s\n' "$(cat "$zone/name" 2>/dev/null || echo '?')" "$zone"
done

echo
echo "Ajoutez cette ligne dans le fichier .env puis relancez le collector :"
echo
echo "    RAPL_GID=$GID"
echo
echo "    docker compose up -d collector"
