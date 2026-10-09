"""Allow a Jobs retry to use the current registered definition."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION operations.jobs_link_retry_v1(
    p_tenant_id BIGINT, p_new_run_id UUID, p_prior_run_id UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_new_run_id IS NULL OR p_prior_run_id IS NULL OR p_new_run_id = p_prior_run_id
    THEN RAISE EXCEPTION 'Jobs retry context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF NOT EXISTS (
        SELECT 1 FROM operations.operator_job_runs prior
         WHERE prior.tenant_id = p_tenant_id AND prior.id = p_prior_run_id
           AND prior.status IN ('failed', 'stalled', 'cancelled')
    ) THEN RAISE EXCEPTION 'Jobs retry requires a terminal prior run'; END IF;
    UPDATE operations.operator_job_runs fresh
       SET retry_of_run_id = p_prior_run_id
      FROM operations.operator_job_runs prior
     WHERE fresh.tenant_id = p_tenant_id AND fresh.id = p_new_run_id
       AND fresh.contract_version = 1 AND fresh.status = 'queued'
       AND prior.tenant_id = p_tenant_id AND prior.id = p_prior_run_id
       AND fresh.job_key = prior.job_key
       AND fresh.scope_identity IS NOT DISTINCT FROM prior.scope_identity
       AND fresh.retry_of_run_id IS NULL;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs retry lineage is incompatible or already set'; END IF;
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (
        p_tenant_id, p_new_run_id, 'retry', 'Queued',
        'Retry of a prior terminal run using the current Job definition.'
    );
END
$function$;

ALTER FUNCTION operations.jobs_link_retry_v1(BIGINT, UUID, UUID) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_link_retry_v1(BIGINT, UUID, UUID)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_link_retry_v1(BIGINT, UUID, UUID) TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0275_jobs_local_evaluation_recovery_authorities"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
