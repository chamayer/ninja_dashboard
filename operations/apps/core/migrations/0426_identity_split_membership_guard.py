"""Reject stale or incomplete selections before splitting Computer records."""

from importlib import import_module
from typing import ClassVar

from django.db import migrations

_original = import_module(
    "apps.core.migrations.0374_source_association_authority"
).CONVERTED_SQL
_start = _original.index("CREATE OR REPLACE FUNCTION operations.split_computer_records(")
_end = _original.index("\nCREATE OR REPLACE FUNCTION operations.move_client_source_group_v1", _start)
REVERSE_SQL = _original[_start:_end]
_anchor = "    PERFORM set_config('operations.tenant_id', d.tenant_id::text, true);\n"
if REVERSE_SQL.count(_anchor) != 1:
    raise RuntimeError("Unexpected Computer record split function")
_guard = """
    -- Association changes lock the subject row. Lock the selected subjects in
    -- stable order before checking their current membership and hold the locks
    -- until all selected associations have been changed.
    PERFORM subject.id
      FROM operations.source_record_subjects subject
      JOIN operations.entity_observation_current eo
        ON eo.tenant_id = subject.tenant_id
       AND eo.observation_id = subject.observation_id
     WHERE eo.tenant_id = d.tenant_id
       AND eo.observation_id = ANY(p_observation_ids)
     ORDER BY subject.id
     FOR UPDATE OF subject;

    -- Do not apply a saved proposal partly after its membership changed.
    IF p_observation_ids IS NULL OR cardinality(p_observation_ids) = 0
       OR array_position(p_observation_ids, NULL) IS NOT NULL
       OR cardinality(p_observation_ids) <> (
           SELECT count(DISTINCT selected.observation_id)
             FROM unnest(p_observation_ids) AS selected(observation_id)
       )
       OR EXISTS (
           SELECT 1
             FROM unnest(p_observation_ids) AS selected(observation_id)
            WHERE NOT EXISTS (
                SELECT 1
                  FROM operations.entity_observation_current eo
                  JOIN operations.source_record_subjects subject
                    ON subject.tenant_id = eo.tenant_id
                   AND subject.observation_id = eo.observation_id
                 WHERE eo.tenant_id = d.tenant_id AND eo.device_id = d.id
                   AND eo.observation_id = selected.observation_id
            )
       ) THEN
        RAISE EXCEPTION 'split_computer_records: selected records changed; review again';
    END IF;
"""
FORWARD_SQL = REVERSE_SQL.replace(_anchor, _anchor + _guard)

GENERATION_LOCK_SQL = """
CREATE FUNCTION operations.lock_source_record_generation(p_tenant bigint)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_generation bigint;
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'lock_source_record_generation: tenant mismatch';
    END IF;
    SELECT input_generation INTO v_generation
      FROM operations.source_record_tenant_state
     WHERE tenant_id = p_tenant FOR SHARE NOWAIT;
    RETURN v_generation;
EXCEPTION WHEN lock_not_available THEN
    RETURN NULL;
END
$fn$;
ALTER FUNCTION operations.lock_source_record_generation(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.lock_source_record_generation(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.lock_source_record_generation(bigint) TO ninja_ingest;
CREATE FUNCTION operations.lock_source_record_subject(p_tenant bigint, p_subject uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'lock_source_record_subject: tenant mismatch';
    END IF;
    PERFORM 1 FROM operations.source_record_subjects
     WHERE tenant_id = p_tenant AND id = p_subject FOR UPDATE NOWAIT;
    RETURN FOUND;
EXCEPTION WHEN lock_not_available THEN
    RETURN FALSE;
END
$fn$;
ALTER FUNCTION operations.lock_source_record_subject(bigint, uuid) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.lock_source_record_subject(bigint, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.lock_source_record_subject(bigint, uuid) TO ninja_ingest;
CREATE FUNCTION operations.lock_identity_reference_data(p_tenant bigint)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'lock_identity_reference_data: tenant mismatch';
    END IF;
    LOCK TABLE operations.entity_types, operations.identity_match_policies,
               operations.identity_value_rejections, operations.source_name_kinds,
               operations.source_record_lifecycle_mappings
        IN SHARE MODE NOWAIT;
    RETURN TRUE;
EXCEPTION WHEN lock_not_available THEN
    RETURN FALSE;
END
$fn$;
ALTER FUNCTION operations.lock_identity_reference_data(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.lock_identity_reference_data(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.lock_identity_reference_data(bigint) TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0425_coverage_boundary_expiry"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunSQL(
            GENERATION_LOCK_SQL,
            "DROP FUNCTION operations.lock_identity_reference_data(bigint); "
            "DROP FUNCTION operations.lock_source_record_subject(bigint, uuid); "
            "DROP FUNCTION operations.lock_source_record_generation(bigint)",
        ),
    ]
