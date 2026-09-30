"""Fence interrupted worker children and retain their resource containment."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION operations.jobs_interrupt_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_claim_token UUID, p_reason TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL
       OR p_reason IS NULL OR length(p_reason) NOT BETWEEN 1 AND 500
    THEN RAISE EXCEPTION 'Jobs interruption context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.operator_job_runs
       SET status = 'stalled', stage = 'Needs attention',
           stage_detail = 'Worker stopped before the handler reported a terminal result.',
           stage_updated_at = now(), completed_at = now(), lease_expires_at = NULL,
           deadline_at = NULL, heartbeat_at = NULL,
           error = p_reason, terminal_reason = 'worker_interrupted',
           worker_incarnation = NULL, claim_token = NULL
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running'
       AND claim_token = p_claim_token AND wait_category IS DISTINCT FROM 'workflow';
    IF NOT FOUND THEN RETURN FALSE; END IF;
    UPDATE operations.job_resource_claims
       SET state = 'contained', release_reason = 'worker interrupted: manual verification required'
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
       AND claim_token = p_claim_token AND state = 'held';
    INSERT INTO operations.operator_job_events (
        tenant_id, job_id, event_type, stage, detail
    ) VALUES (
        p_tenant_id, p_run_id, 'worker_interrupted', 'Needs attention',
        'Worker stopped before the handler reported a terminal result; resources remain contained.'
    );
    PERFORM operations.jobs_propagate_dependency_terminal_v1(
        p_tenant_id, p_run_id, 'stalled'
    );
    RETURN TRUE;
END
$function$;

ALTER FUNCTION operations.jobs_interrupt_v1(BIGINT, UUID, UUID, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_interrupt_v1(BIGINT, UUID, UUID, TEXT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_interrupt_v1(BIGINT, UUID, UUID, TEXT)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0223_jobs_queued_successors"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
