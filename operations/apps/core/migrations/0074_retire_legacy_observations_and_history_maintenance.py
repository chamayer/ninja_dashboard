"""Retire the empty append store and repair history maintenance primitives."""

# ruff: noqa: I001, RUF012

from django.db import migrations


SQL = """
ALTER TABLE operations.asset_field_history
    ALTER COLUMN changed_at SET DEFAULT clock_timestamp();
ALTER TABLE operations.os_instance_field_history
    ALTER COLUMN changed_at SET DEFAULT clock_timestamp();
ALTER TABLE operations.agent_instance_field_history
    ALTER COLUMN changed_at SET DEFAULT clock_timestamp();

DROP FUNCTION IF EXISTS operations.refresh_software_installations_current(bigint);

CREATE OR REPLACE FUNCTION operations.purge_closed_observation_history(
    p_cutoff timestamptz
) RETURNS TABLE(generic_deleted bigint, software_deleted bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $$
DECLARE
    v_generic bigint;
    v_software bigint;
BEGIN
    DELETE FROM operations.entity_observation_history
     WHERE effective_to IS NOT NULL AND effective_to < p_cutoff;
    GET DIAGNOSTICS v_generic = ROW_COUNT;

    DELETE FROM operations.software_installation_history
     WHERE effective_to IS NOT NULL AND effective_to < p_cutoff;
    GET DIAGNOSTICS v_software = ROW_COUNT;
    RETURN QUERY SELECT v_generic, v_software;
END;
$$;
GRANT EXECUTE ON FUNCTION operations.purge_closed_observation_history(timestamptz)
    TO ninja_ingest, operations_app;

DROP TABLE IF EXISTS operations.entity_observations;
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0073_software_installation_history")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(SQL, migrations.RunSQL.noop)],
            state_operations=[migrations.DeleteModel(name="EntityObservation")],
        ),
    ]
