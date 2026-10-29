"""Guarded findings writers and namespace-aware state (PLAN-003 M3, part 1).

Part of the coordinated M2-M4 artifact.

* ``finding_contract`` holds the findings contract generation the database
  accepts; ``finding_contract_version()`` reads it. This migration records 3
  (common ledger, not yet verified); M4 publishes 4 after its exact-set checks.
* Every write to findings, condition assessments and condition participants
  must come from a transaction that already holds the exclusive tenant guard
  for the session tenant and declares the matching contract in
  ``operations.finding_contract``. Statement-level triggers check the guard and
  contract before any row lock; row-level triggers reject a row of another
  tenant. Triggers apply to every role, including superusers: production ingest
  connects as a superuser, so revoking privileges could not enforce this.
  Migrations running as ``operations_migrate`` are exempt.
* State is computed for both namespaces: an assessment or participant counts
  only when its ``row_kind`` matches its finding's ``condition_namespace``.
  Admin findings get state for the first time.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_state = importlib.import_module("apps.core.migrations.0301_finding_state")
_skip = importlib.import_module("apps.core.migrations.0302_finding_state_skip_unchanged")
_cover = importlib.import_module("apps.core.migrations.0304_finding_cover_is_live")


def _function(sql: str, name: str) -> str:
    """One ``CREATE OR REPLACE FUNCTION operations.<name>`` definition from earlier SQL."""
    start = sql.index(f"CREATE OR REPLACE FUNCTION operations.{name}(")
    end = sql.index("$function$;", start) + len("$function$;")
    return sql[start:end] + "\n"


def _compute_sql() -> str:
    body = _function(_cover.FORWARD_SQL, "compute_finding_state")
    replacements = (
        (
            "SELECT f.id, f.tenant_id, f.finding_type_id, f.status, f.subject_type, f.subject_id",
            "SELECT f.id, f.tenant_id, f.finding_type_id, f.status, f.subject_type, f.subject_id,\n"
            "               f.condition_namespace",
        ),
        (
            "cp.row_kind = 'entity' AND cp.finding_id = t.id",
            "cp.row_kind = t.condition_namespace AND cp.finding_id = t.id",
        ),
        ("WHERE a.row_kind = 'entity'", "WHERE a.row_kind = t.condition_namespace"),
    )
    for old, new in replacements:
        assert body.count(old) == 1, old
        body = body.replace(old, new)
    return body


FORWARD_SQL = (
    r"""
CREATE TABLE operations.finding_contract (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL CHECK (version > 0),
    published_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO operations.finding_contract (version) VALUES (3);
REVOKE ALL ON operations.finding_contract FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.finding_contract
    FROM operations_app, ninja_ingest, operations_readonly;
GRANT SELECT ON operations.finding_contract TO operations_app, operations_readonly, ninja_ingest;
INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture)
VALUES ('finding_contract', 'exempt', 'contract generation; changed only by migrations',
        '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, TRUE, NULL)
ON CONFLICT (table_name) DO NOTHING;

CREATE FUNCTION operations.finding_contract_version() RETURNS integer
LANGUAGE sql STABLE
SET search_path = pg_catalog, operations
AS $fn$ SELECT version FROM operations.finding_contract $fn$;
REVOKE ALL ON FUNCTION operations.finding_contract_version() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.finding_contract_version()
    TO operations_app, operations_readonly, ninja_ingest;

-- Before any row is touched: the writer holds the exclusive tenant guard and
-- was built for the current contract.
CREATE FUNCTION operations.assert_findings_writer() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_tenant bigint := nullif(current_setting('operations.tenant_id', true), '')::bigint;
    v_contract text := nullif(current_setting('operations.finding_contract', true), '');
BEGIN
    IF session_user = 'operations_migrate' THEN
        RETURN NULL;
    END IF;
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION '% on operations.% needs the session tenant', TG_OP, TG_TABLE_NAME;
    END IF;
    PERFORM operations.assert_tenant_guard(v_tenant, 'exclusive');
    IF v_contract IS DISTINCT FROM operations.finding_contract_version()::text THEN
        RAISE EXCEPTION 'findings writer contract % does not match database contract %',
                        coalesce(v_contract, 'none'), operations.finding_contract_version();
    END IF;
    RETURN NULL;
END
$fn$;

-- Each written row belongs to the guarded session tenant.
CREATE FUNCTION operations.assert_findings_row_tenant() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_tenant bigint;
BEGIN
    IF session_user = 'operations_migrate' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    v_tenant := nullif(current_setting('operations.tenant_id', true), '')::bigint;
    IF TG_OP <> 'INSERT' AND OLD.tenant_id IS DISTINCT FROM v_tenant THEN
        RAISE EXCEPTION '% on operations.% touches a row of tenant %, session tenant is %',
                        TG_OP, TG_TABLE_NAME, OLD.tenant_id, v_tenant;
    END IF;
    IF TG_OP <> 'DELETE' AND NEW.tenant_id IS DISTINCT FROM v_tenant THEN
        RAISE EXCEPTION '% on operations.% writes a row of tenant %, session tenant is %',
                        TG_OP, TG_TABLE_NAME, NEW.tenant_id, v_tenant;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$fn$;

DO $triggers$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['findings', 'condition_assessments', 'condition_participants'] LOOP
        EXECUTE format(
            'CREATE TRIGGER assert_findings_writer BEFORE INSERT OR UPDATE OR DELETE
               ON operations.%I FOR EACH STATEMENT
               EXECUTE FUNCTION operations.assert_findings_writer()', t);
        EXECUTE format(
            'CREATE TRIGGER assert_findings_row_tenant BEFORE INSERT OR UPDATE OR DELETE
               ON operations.%I FOR EACH ROW
               EXECUTE FUNCTION operations.assert_findings_row_tenant()', t);
    END LOOP;
END
$triggers$;
"""
    + _compute_sql()
    + r"""
ALTER FUNCTION operations.compute_finding_state(uuid[]) SET jit = off;

CREATE OR REPLACE FUNCTION operations.finding_state_after_assessments()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
BEGIN
    PERFORM operations.refresh_finding_state((
        SELECT array_agg(DISTINCT n.finding_id) FROM new_rows n WHERE n.finding_id IS NOT NULL));
    RETURN NULL;
END
$function$;

CREATE OR REPLACE FUNCTION operations.finding_state_after_participants()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM operations.refresh_finding_state((
            SELECT array_agg(DISTINCT o.finding_id) FROM old_rows o WHERE o.finding_id IS NOT NULL));
    ELSE
        PERFORM operations.refresh_finding_state((
            SELECT array_agg(DISTINCT n.finding_id) FROM new_rows n WHERE n.finding_id IS NOT NULL));
    END IF;
    RETURN NULL;
END
$function$;

CREATE OR REPLACE FUNCTION operations.finding_state_after_assessment_update()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
DECLARE
    changed uuid[];
    unchanged uuid[];
BEGIN
    SELECT array_agg(DISTINCT n.finding_id) INTO changed
      FROM new_rows n
      JOIN old_rows o
        ON o.tenant_id = n.tenant_id AND o.row_kind = n.row_kind AND o.finding_id = n.finding_id
       AND o.participant_kind = n.participant_kind AND o.participant_id = n.participant_id
       AND o.participant_role = n.participant_role
     WHERE n.finding_id IS NOT NULL
       AND (n.response IS DISTINCT FROM o.response
            OR n.policy_version IS DISTINCT FROM o.policy_version);
    SELECT array_agg(DISTINCT n.finding_id) INTO unchanged
      FROM new_rows n
     WHERE n.finding_id IS NOT NULL
       AND NOT (n.finding_id = ANY(COALESCE(changed, ARRAY[]::uuid[])));
    PERFORM operations.refresh_finding_state(changed);
    PERFORM operations.touch_finding_state(unchanged);
    RETURN NULL;
END
$function$;

-- Admin findings get their state now that it is namespace-aware.
SELECT operations.refresh_finding_state(array_agg(id))
  FROM operations.findings WHERE condition_namespace = 'admin';
"""
)

REVERSE_SQL = (
    r"""
DO $triggers$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['findings', 'condition_assessments', 'condition_participants'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS assert_findings_writer ON operations.%I', t);
        EXECUTE format('DROP TRIGGER IF EXISTS assert_findings_row_tenant ON operations.%I', t);
    END LOOP;
END
$triggers$;
DROP FUNCTION IF EXISTS operations.assert_findings_row_tenant();
DROP FUNCTION IF EXISTS operations.assert_findings_writer();
DROP FUNCTION IF EXISTS operations.finding_contract_version();
DELETE FROM operations.change_history_registry WHERE table_name = 'finding_contract';
DROP TABLE IF EXISTS operations.finding_contract;
"""
    + _function(_cover.FORWARD_SQL, "compute_finding_state")
    + _function(_state.FORWARD_SQL, "finding_state_after_assessments")
    + _function(_state.FORWARD_SQL, "finding_state_after_participants")
    + _function(_skip.FORWARD_SQL, "finding_state_after_assessment_update")
    + r"""
ALTER FUNCTION operations.compute_finding_state(uuid[]) SET jit = off;
"""
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0364_findings_admin_conversion"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
