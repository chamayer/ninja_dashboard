#!/bin/sh
set -eu

# Local-only role bootstrap. The migration role needs elevated rights to run
# the initial schema migrations; app requests use the separate runtime role.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$OPERATIONS_DB_PASSWORD" \
  --set=migrate_password="$OPERATIONS_MIGRATE_DB_PASSWORD" \
  <<'SQL'
SELECT format('CREATE ROLE operations_app LOGIN PASSWORD %L', :'app_password')
\gexec
SELECT format('CREATE ROLE operations_migrate LOGIN SUPERUSER PASSWORD %L', :'migrate_password')
\gexec
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_readonly') THEN
    CREATE ROLE operations_readonly NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_health') THEN
    CREATE ROLE operations_health NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_ro') THEN
    CREATE ROLE metabase_ro NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ninja_ingest') THEN
    CREATE ROLE ninja_ingest NOLOGIN;
  END IF;
END
$$;
SQL

# Ingest-owned SQL migrations create some Operations-schema read tables before
# Django migrations run. Django migration 0001 also creates this schema when
# it is absent, but the full stack runs ingest migration first.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --command='CREATE SCHEMA IF NOT EXISTS operations'
