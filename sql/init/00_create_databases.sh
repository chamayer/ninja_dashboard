#!/bin/sh
# Runs once, on first Postgres container boot. Creates the Metabase app
# DB and role. The main `ninja` DB is created by Postgres itself from
# $POSTGRES_DB.
#
# Uses POSIX sh (not bash) — postgres:16-alpine doesn't ship bash.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE "${MB_DB_USER}" WITH LOGIN PASSWORD '${MB_DB_PASS}';
    CREATE DATABASE "${MB_DB_DBNAME}" OWNER "${MB_DB_USER}";
    GRANT ALL PRIVILEGES ON DATABASE "${MB_DB_DBNAME}" TO "${MB_DB_USER}";
EOSQL
