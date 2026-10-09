"""Keep durable tenant schedules aligned with the declared Jobs catalog."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION operations.jobs_disable_retired_tenant_schedules_v1(
    p_tenant_id BIGINT,
    p_declared_keys TEXT[]
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; DECLARE v_count INTEGER;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_declared_keys IS NULL
       OR EXISTS (
            SELECT 1 FROM unnest(p_declared_keys) AS key
             WHERE key IS NULL OR key !~ '^[a-z0-9][a-z0-9-]{1,119}$'
       )
    THEN RAISE EXCEPTION 'Jobs schedule retirement is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.job_schedules AS schedule
       SET enabled = FALSE,
           next_due_at = NULL,
           capability_reason = 'Disabled — this Job starts after its prerequisite.'
     WHERE schedule.tenant_id = p_tenant_id
       AND schedule.scope_identity = 'tenant:1'
       AND schedule.enabled
       AND NOT (schedule.definition_key = ANY(p_declared_keys));
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$function$;

ALTER FUNCTION operations.jobs_disable_retired_tenant_schedules_v1(BIGINT, TEXT[])
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_disable_retired_tenant_schedules_v1(BIGINT, TEXT[])
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_disable_retired_tenant_schedules_v1(BIGINT, TEXT[])
TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0273_repair_derived_projection_contracts"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
