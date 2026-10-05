"""Make each Jobs step terminal and retire schedules for dependent steps."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
/*
 * A run is one executable step, not a workflow coordinator.  The existing
 * parent/root lineage and immutable dependency edges remain the sequence
 * record.  This migration only retires the prior presentation state where a
 * finished parent was kept "running" until its follow-on work completed.
 */
CREATE OR REPLACE FUNCTION operations.jobs_finish_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_claim_token UUID, p_status TEXT,
    p_rows_touched INTEGER DEFAULT NULL, p_error TEXT DEFAULT '',
    p_result JSONB DEFAULT '{}'::jsonb
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_stage TEXT; v_detail TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL
       OR p_status NOT IN ('completed', 'failed')
       OR p_rows_touched IS NOT NULL AND p_rows_touched < 0
       OR p_error IS NULL OR length(p_error) > 2000
       OR p_result IS NULL OR jsonb_typeof(p_result) <> 'object'
       OR octet_length(p_result::text) > 65536
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_result) AS result_key(key)
            WHERE key ~* '(token|secret|password|authorization|credential)'
       )
    THEN RAISE EXCEPTION 'Jobs finish context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    v_stage := CASE WHEN p_status = 'completed' THEN 'Completed' ELSE 'Failed' END;
    v_detail := CASE WHEN p_status = 'completed' THEN 'Finished.' ELSE 'Review the recorded error.' END;
    UPDATE operations.operator_job_runs
       SET status = p_status, stage = v_stage, stage_detail = v_detail,
           stage_updated_at = now(), heartbeat_at = now(), completed_at = now(),
           lease_expires_at = NULL, deadline_at = NULL,
           rows_touched = p_rows_touched, error = p_error, result = p_result,
           wait_category = NULL, wait_reason = NULL,
           worker_incarnation = worker_incarnation, claim_token = claim_token,
           terminal_reason = CASE WHEN p_status = 'completed' THEN 'completed' ELSE 'failed' END
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running' AND claim_token = p_claim_token;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs finish is unavailable or fenced'; END IF;
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = p_status
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
       AND claim_token = p_claim_token AND state = 'held';
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, p_run_id, p_status, v_stage, v_detail);
    PERFORM operations.jobs_propagate_dependency_terminal_v1(
        p_tenant_id, p_run_id, p_status
    );
END
$function$;

/* Keep all schedule and event history, but prevent old dependent schedules
 * from starting a second copy of work that a meaningful entry operation owns.
 */
UPDATE operations.job_schedules
   SET enabled = FALSE,
       next_due_at = NULL,
       capability_reason = 'Managed by its operation entry point.',
       last_outcome = 'retired'
 WHERE tenant_id = 1
   AND definition_key IN (
       'resolver', 'platform-evaluate', 'software-classify-only',
       'software-classify-full', 'intel-matcher'
   )
   AND enabled;

/* Correct only prior pseudo-running coordinator rows.  Their handler had
 * already completed and their resource claims were already released.
 */
WITH corrected AS (
    UPDATE operations.operator_job_runs
       SET status = 'completed', stage = 'Completed', stage_detail = 'Finished.',
           stage_updated_at = now(), completed_at = COALESCE(completed_at, now()),
           wait_category = NULL, wait_reason = NULL, heartbeat_at = now(),
           terminal_reason = 'completed'
     WHERE tenant_id = 1 AND status = 'running'
       AND wait_category = 'workflow' AND terminal_reason = 'handler_completed'
 RETURNING id
)
INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
SELECT 1, id, 'workflow_coordinator_retired', 'Completed',
       'The step had already finished; follow-on work remains linked separately.'
  FROM corrected;

ALTER FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0243_jobs_abusech_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
