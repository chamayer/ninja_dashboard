# =============================================================================
# ninja-dashboard / operations
# Django service: write-side operator console (decisions, merge review,
# policy edits, findings triage, ad-hoc queries). Companion to Metabase.
# See operations/BLUEPRINT.md.
# =============================================================================
FROM python:3.12-slim

# ── System deps ──────────────────────────────────────────────────────
# libpq5 for psycopg (binary wheel loads libpq at runtime);
# curl for HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ────────────────────────────────────────────────────
RUN groupadd -r operations && useradd -r -g operations -d /app operations

WORKDIR /app

# ── Python deps (own layer — rarely changes) ─────────────────────────
COPY operations/pyproject.toml operations/README.md ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ── App source ───────────────────────────────────────────────────────
COPY operations/config/ ./config/
COPY operations/apps/   ./apps/
COPY operations/manage.py ./
COPY operations/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN chown -R operations:operations /app
USER operations

# ── Runtime env ──────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    OPERATIONS_ENV_FILE=/app/.env

# 3002 → UI + API (LAN).
# 8091 → health / internal ops (compose publishes to 127.0.0.1 only).
EXPOSE 3002 8091

# Gunicorn is up before migrate finishes but /healthz responds early
# via its own route bound to 8091. See entrypoint.sh.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8091/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
