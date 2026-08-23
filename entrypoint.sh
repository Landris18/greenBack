#!/bin/bash
set -euo pipefail

ROLE="${1:-web}"

wait_for_database() {
    python - <<'PYTHON'
import asyncio
import sys

import asyncpg

from app.core.config import settings


async def wait() -> None:
    for attempt in range(60):
        try:
            connection = await asyncpg.connect(
                host=settings.DATABASE_HOST,
                port=settings.DATABASE_PORT,
                user=settings.DATABASE_USER,
                password=settings.DATABASE_PASSWORD,
                database=settings.DATABASE_NAME,
            )
            await connection.close()
            return
        except Exception:
            await asyncio.sleep(2)
    sys.exit("Base de donnees injoignable.")


asyncio.run(wait())
PYTHON
}

wait_for_database

case "$ROLE" in
    web)
        alembic upgrade head
        python -m app.seed
        exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-2}"
        ;;
    dev)
        alembic upgrade head
        python -m app.seed
        exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
        ;;
    collector)
        exec python -m app.collector
        ;;
    *)
        exec "$@"
        ;;
esac
