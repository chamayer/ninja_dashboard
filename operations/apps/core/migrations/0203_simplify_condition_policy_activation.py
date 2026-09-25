"""Remove the mandatory review prerequisite from policy activation."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE FUNCTION operations.activate_condition_policy_version(p_version TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('operations.condition_policy_activation'));
    IF NOT EXISTS (SELECT 1 FROM operations.condition_policy_versions WHERE version = p_version)
       OR NOT EXISTS (SELECT 1 FROM operations.condition_policies WHERE policy_version = p_version) THEN
        RAISE EXCEPTION 'Unknown or invalid condition policy version: %', p_version;
    END IF;
    UPDATE operations.condition_policy_versions SET active = FALSE WHERE active;
    UPDATE operations.condition_policy_versions SET active = TRUE WHERE version = p_version;
    UPDATE operations.condition_assessments
       SET response = response || jsonb_build_object(
               'may_evaluate', false,
               'may_notify', false,
               'may_execute', false,
               'may_clear', false
           ),
           currentness = currentness || jsonb_build_object(
               'invalidated_reason', 'policy_activated',
               'invalidated_by_policy', p_version,
               'invalidated_at', now()
           )
     WHERE policy_version <> p_version;
END
$$;
ALTER FUNCTION operations.activate_condition_policy_version(TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.activate_condition_policy_version(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.activate_condition_policy_version(TEXT) TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0202_client_mapping_legacy_alias_bridge"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
