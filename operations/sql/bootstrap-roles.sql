-- One-time Postgres bootstrap for the Operations service.
--
-- Creates the two login-capable roles Django needs, grants CREATE on the
-- database to the migration role, and pre-creates the `operations`
-- schema owned by the migration role.
--
-- Chicken-and-egg: migration 0006 tries to ALTER ROLE operations_migrate
-- itself (to force BYPASSRLS), which fails unless operations_migrate is
-- already SUPERUSER. So we bootstrap it as SUPERUSER here. Migration 0006
-- also creates the other four roles (operations_readonly, operations_health,
-- metabase_ro, ninja_ingest) idempotently — they don't need to be in
-- bootstrap.
--
-- Run once on a fresh Postgres, as the ninja superuser, BEFORE the
-- operations container's first migrate:
--
--   MIG_PW=$(grep '^OPERATIONS_MIGRATE_DB_PASSWORD=' /amr-ch-01_data/ninja-dashboard/.env | cut -d= -f2-)
--   APP_PW=$(grep '^OPERATIONS_DB_PASSWORD='         /amr-ch-01_data/ninja-dashboard/.env | cut -d= -f2-)
--   docker exec -i ninja-postgres psql -U ninja -d ninja \
--       -v migrate_pw="${MIG_PW}" \
--       -v app_pw="${APP_PW}" \
--       < operations/sql/bootstrap-roles.sql
--
-- Idempotent: safe to re-run. Refreshes passwords on both roles if the
-- roles already exist. Useful after rotating either password in .env.

-- ---------------------------------------------------------------------------
-- Guardrail: both passwords must be provided via -v.
-- ---------------------------------------------------------------------------
\if :{?migrate_pw}
\else
    \warn 'ERROR: -v migrate_pw=<password> is required'
    \q
\endif
\if :{?app_pw}
\else
    \warn 'ERROR: -v app_pw=<password> is required'
    \q
\endif

-- ---------------------------------------------------------------------------
-- operations_migrate: SUPERUSER + LOGIN + password.
-- SUPERUSER because migration 0006 needs to ALTER ROLE on itself.
-- Uses \gexec so we can build the DDL string outside any dollar-quoted
-- block (psql variable substitution doesn't happen inside $$...$$).
-- ---------------------------------------------------------------------------
SELECT CASE
    WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_migrate')
        THEN format('ALTER ROLE operations_migrate WITH SUPERUSER LOGIN PASSWORD %L', :'migrate_pw')
        ELSE format('CREATE ROLE operations_migrate WITH SUPERUSER LOGIN PASSWORD %L', :'migrate_pw')
END AS ddl
\gexec

-- ---------------------------------------------------------------------------
-- operations_app: runtime role. LOGIN + password. RLS DOES apply (no
-- BYPASSRLS). Grants for the operations.* tables are applied by
-- migration 0006.
-- ---------------------------------------------------------------------------
SELECT CASE
    WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_app')
        THEN format('ALTER ROLE operations_app WITH LOGIN PASSWORD %L', :'app_pw')
        ELSE format('CREATE ROLE operations_app WITH LOGIN PASSWORD %L', :'app_pw')
END AS ddl
\gexec

-- ---------------------------------------------------------------------------
-- operations_migrate needs CREATE on the target database so migration
-- 0001_initial can create the `operations` schema.
-- ---------------------------------------------------------------------------
GRANT CREATE ON DATABASE ninja TO operations_migrate;

-- ---------------------------------------------------------------------------
-- Pre-create the schema owned by operations_migrate so migration 0001's
-- CREATE SCHEMA IF NOT EXISTS is a no-op with correct ownership.
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS operations AUTHORIZATION operations_migrate;
