#!/usr/bin/env bash
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONT="$(cd "$RACINE/.." && pwd)/greenFront"
ENV_FICHIER="$RACINE/.env"

cd "$RACINE"

if [[ ! -d "$FRONT" ]]; then
    echo "Le dépôt greenFront est introuvable dans $(dirname "$FRONT")." >&2
    echo "Clonez-le à côté de greenBack :" >&2
    echo >&2
    echo "    git clone https://github.com/Landris18/greenFront.git \"$FRONT\"" >&2
    exit 1
fi

if [[ -f "$ENV_FICHIER" ]]; then
    echo "Le fichier .env existe déjà, il est conservé."
else
    cp .env.example "$ENV_FICHIER"

    CLE=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 48)
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$CLE|" "$ENV_FICHIER"
    sed -i "s|^HOST_UID=.*|HOST_UID=$(id -u)|" "$ENV_FICHIER"
    sed -i "s|^HOST_GID=.*|HOST_GID=$(id -g)|" "$ENV_FICHIER"
    sed -i "s|^PROJECTS_ROOT=.*|PROJECTS_ROOT=$HOME|" "$ENV_FICHIER"
    sed -i "s|^COLLECTOR_HOST_NAME=.*|COLLECTOR_HOST_NAME=$(hostname)|" "$ENV_FICHIER"

    echo "Fichier .env créé, adapté à cette machine :"
    echo "    utilisateur       $(id -u):$(id -g)"
    echo "    projets observés  $HOME"
    echo "    clé secrète       générée aléatoirement"
fi

echo
echo "Démarrage de la plateforme."
docker compose up -d --build

echo
echo "Interface        http://localhost:${FRONT_PORT:-3000}"
echo "API              http://localhost:${API_PORT:-8000}/docs"
echo "Identifiants     voir SEED_ADMIN_EMAIL et SEED_ADMIN_PASSWORD dans .env"
echo
echo "Mesure matérielle : sur une machine physique, RAPL peut être activé avec"
echo "    sudo ./scripts/activer-mesure-rapl.sh"
