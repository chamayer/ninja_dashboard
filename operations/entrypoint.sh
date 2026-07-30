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

# Extract only OPERATIONS_* keys from the bind-mounted .env so pre-Django
# shell checks (DB passwords) see them. Blanket-sourcing the whole file
# breaks under dash (/bin/sh on python:slim images) when other keys in
# .env contain unquoted spaces — dash treats the tail of the value as
# further commands. python-dotenv handles the full file at Django import
# time; this loop only exists for the pre-import shell checks.
# Directory mount first, legacy single-file mount second. Compose bind-mounts
# the host env DIRECTORY at /app/envdir, because a single-file bind mount stays
# pinned to the inode present at container creation and silently never sees an
# atomic-save edit. Both paths are accepted so compose and image can deploy in
# either order.
ENV_FILE=/app/envdir/.env
[ -f "$ENV_FILE" ] || ENV_FILE=/app/.env

if [ -f "$ENV_FILE" ]; then
    for k in OPERATIONS_SECRET_KEY OPERATIONS_ALLOWED_HOSTS \
             OPERATIONS_DB_NAME OPERATIONS_DB_USER OPERATIONS_DB_PASSWORD \
             OPERATIONS_MIGRATE_DB_USER OPERATIONS_MIGRATE_DB_PASSWORD \
             OPERATIONS_INITIAL_ADMIN_PASSWORD; do
        v=$(grep "^${k}=" "$ENV_FILE" | head -1 | cut -d= -f2-)
        if [ -n "$v" ]; then
            export "${k}=${v}"
        fi
    done
else
    echo "[operations] WARNING: no env file at /app/envdir/.env or /app/.env" >&2
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

echo "[operations] setting initial admin password from env (if provided)..."
python manage.py set_initial_admin_password

echo "[operations] bootstrapping clients from ninja_core.organizations..."
python manage.py bootstrap_clients_from_ninja

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
    --keep-alive 2 \
    --access-logfile - \
    --error-logfile - \
    --forwarded-allow-ips="*"
