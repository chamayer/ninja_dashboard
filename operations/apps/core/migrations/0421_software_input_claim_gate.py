"""Keep every Software publication queued until its declared inputs are ready."""

from importlib import import_module

from django.db import migrations


READY_SQL = """
CREATE FUNCTION operations.software_overview_inputs_ready(p_tenant bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE inputs jsonb;
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'Software readiness context is invalid';
    END IF;
    inputs := operations.software_overview_inputs(p_tenant);
    IF jsonb_typeof(inputs->'owners') IS DISTINCT FROM 'object'
       OR inputs->'owners' = '{}'::jsonb THEN RETURN false; END IF;
    RETURN NOT coalesce((inputs->>'ownership_pending')::boolean, true)
       AND NOT coalesce((inputs->>'classification_pending')::boolean, true)
       AND coalesce(inputs->'active', 'null'::jsonb) = '[]'::jsonb
       AND NOT EXISTS (
           SELECT 1 FROM jsonb_each(inputs->'owners') owner
           WHERE (owner.value->>'ready')::boolean IS DISTINCT FROM true
       );
END
$function$;
ALTER FUNCTION operations.software_overview_inputs_ready(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.software_overview_inputs_ready(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.software_overview_inputs_ready(bigint)
    TO operations_app, ninja_ingest;
"""

OLD_CLAIM = import_module("apps.core.migrations.0405_jobs_claim_successor_guard").FORWARD_SQL
MARKER = "AND run.wait_category IS NULL"
assert OLD_CLAIM.count(MARKER) == 2
# v7 handles source-refresh, then delegates all other Jobs to v6. Gate only
# v6's Software candidate, before resources/claim acquisition; other Jobs pass.
NEW_CLAIM = OLD_CLAIM.replace(
    MARKER,
    MARKER + "\n           AND (run.job_key <> 'software-overview' OR "
    "operations.software_overview_inputs_ready(p_tenant_id))",
    1,
)


class Migration(migrations.Migration):
    dependencies = [("operations", "0420_ownership_recovery_authorities")]
    operations = [
        migrations.RunSQL(READY_SQL + NEW_CLAIM, OLD_CLAIM + "\nDROP FUNCTION operations.software_overview_inputs_ready(bigint);"),
    ]
