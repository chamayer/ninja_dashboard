#!/bin/sh
# =============================================================================
# operations entrypoint
# 1) Apply Django migrations (idempotent).
# 2) Collect static assets for whitenoise.
# 3) Launch gunicorn on 3002 (LAN) and 8091 (internal ops / health).
#
# /app/.env is bind-mounted from /amr-ch-01_data/ninja-dashboard/.env by
# compose. Source it here so pre-Django shell checks (DB passwords) see
# the values — python-dotenv only loads at Django import time, which is
# too late for this script. Same pattern as postgres/metabase services.
# =============================================================================
set -e

# Load bind-mounted .env into shell env before any pre-Django checks.
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi

runtime_db_user="${OPERATIONS_DB_USER:-operations_app}"
runtime_db_password="${OPERATIONS_DB_PASSWORD:-}"
migrate_db_user="${OPERATIONS_MIGRATE_DB_USER:-operations_migrate}"
migrate_db_password="${OPERATIONS_MIGRATE_DB_PASSWORD:-}"

if [ -z "$runtime_db_password" ]; then
    echo "[operations] OPERATIONS_DB_PASSWORD is required for runtime role ${runtime_db_user}" >&2
    exit 1
fi

if [ -z "$migrate_db_password" ]; then
    echo "[operations] OPERATIONS_MIGRATE_DB_PASSWORD is required for migration role ${migrate_db_user}" >&2
    exit 1
fi

echo "[operations] applying migrations as ${migrate_db_user}..."
export OPERATIONS_DB_USER="$migrate_db_user"
export OPERATIONS_DB_PASSWORD="$migrate_db_password"
python manage.py migrate --noinput

echo "[operations] collecting static files..."
python manage.py collectstatic --noinput --clear

echo "[operations] switching to runtime DB role ${runtime_db_user}..."
export OPERATIONS_DB_USER="$runtime_db_user"
export OPERATIONS_DB_PASSWORD="$runtime_db_password"

echo "[operations] starting gunicorn on 3002 (LAN) + 8091 (internal)..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:3002 \
    --bind 0.0.0.0:8091 \
    --workers "${OPERATIONS_WORKERS:-3}" \
    --timeout "${OPERATIONS_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile - \
    --forwarded-allow-ips="*"
