FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /api

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system appuser && adduser --system --ingroup appuser appuser

COPY --chown=appuser:appuser . .
RUN chmod +x entrypoint.sh

FROM base AS web
USER appuser
EXPOSE 8000
ENTRYPOINT ["/api/entrypoint.sh"]
CMD ["web"]

FROM base AS collector
USER appuser
ENTRYPOINT ["/api/entrypoint.sh"]
CMD ["collector"]

FROM base AS dev
USER appuser
EXPOSE 8000
ENTRYPOINT ["/api/entrypoint.sh"]
CMD ["dev"]
