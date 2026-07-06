#!/bin/sh
# =============================================================================
# operations entrypoint
# 1) Apply Django migrations (idempotent).
# 2) Collect static assets for whitenoise.
# 3) Launch gunicorn on 3002 (LAN) and 8091 (internal ops / health).
#
# python-dotenv in config/settings/base.py loads /app/.env at import time,
# so no OS-level env-file sourcing is needed. .env is bind-mounted into
# the container from /amr-ch-01_data/ninja-dashboard/.env by compose.
# =============================================================================
set -e

echo "[operations] applying migrations..."
python manage.py migrate --noinput

echo "[operations] collecting static files..."
python manage.py collectstatic --noinput --clear

echo "[operations] starting gunicorn on 3002 (LAN) + 8091 (internal)..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:3002 \
    --bind 0.0.0.0:8091 \
    --workers "${OPERATIONS_WORKERS:-3}" \
    --timeout "${OPERATIONS_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile - \
    --forwarded-allow-ips="*"
