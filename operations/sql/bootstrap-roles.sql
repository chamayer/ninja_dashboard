-- One-time Postgres role bootstrap for the Operations service.
--
-- Chicken-and-egg problem: migration 0006_rls_roles_policies_grants runs
-- CREATE ROLE for all six operations roles, but that migration is executed
-- BY operations_migrate — which doesn't exist yet on a fresh Postgres.
-- This script pre-creates operations_migrate so the first migrate can run.
--
-- Run once on a fresh Postgres, as the ninja superuser, BEFORE the
-- operations container's first migrate:
--
--   docker exec -i ninja-postgres psql -U ninja -d ninja \
--     -v migrate_pw="'<OPERATIONS_MIGRATE_DB_PASSWORD from .env>'" \
--     < operations/sql/bootstrap-roles.sql
--
-- After this runs, migration 0006 idempotently creates the other five roles
-- (operations_app, operations_readonly, operations_health, metabase_ro,
-- ninja_ingest) and applies RLS policies + grants.
--
-- Safe to re-run: refreshes the password on operations_migrate if the role
-- already exists. If you rotate OPERATIONS_MIGRATE_DB_PASSWORD in .env,
-- re-invoke this script to sync.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_migrate') THEN
        EXECUTE format(
            'CREATE ROLE operations_migrate LOGIN CREATEROLE BYPASSRLS PASSWORD %L',
            :'migrate_pw'
        );
    ELSE
        EXECUTE format(
            'ALTER ROLE operations_migrate WITH LOGIN CREATEROLE BYPASSRLS PASSWORD %L',
            :'migrate_pw'
        );
    END IF;
END $$;
