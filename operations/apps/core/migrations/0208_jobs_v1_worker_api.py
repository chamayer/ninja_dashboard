"""Provide fenced v1 worker claim and terminal-state APIs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION operations.jobs_claim_next_v3(
    p_tenant_id BIGINT,
    p_lane TEXT,
    p_worker_incarnation UUID
) RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_claim RECORD;
BEGIN
    SELECT * INTO v_claim
      FROM operations.jobs_claim_next_v2(p_tenant_id, p_lane, p_worker_incarnation);
    IF NOT FOUND THEN
        RETURN;
    END IF;
    UPDATE operations.operator_job_runs AS job
       SET attempts = attempts + 1
     WHERE tenant_id = p_tenant_id
       AND id = v_claim.run_id
       AND contract_version = 1
       AND claim_token = v_claim.claim_token
       AND worker_incarnation = p_worker_incarnation
       AND status = 'running'
     RETURNING job.job_key INTO job_key;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs claim result is unavailable or fenced';
    END IF;
    run_id := v_claim.run_id;
    claim_token := v_claim.claim_token;
    RETURN NEXT;
END
$function$;

CREATE FUNCTION operations.jobs_finish_v1(
    p_tenant_id BIGINT,
    p_run_id UUID,
    p_claim_token UUID,
    p_status TEXT,
    p_rows_touched INTEGER DEFAULT NULL,
    p_error TEXT DEFAULT '',
    p_result JSONB DEFAULT '{}'::jsonb
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
DECLARE v_stage TEXT;
DECLARE v_detail TEXT;
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
    THEN
        RAISE EXCEPTION 'Jobs finish context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    v_stage := CASE WHEN p_status = 'completed' THEN 'Completed' ELSE 'Failed' END;
    v_detail := CASE
        WHEN p_status = 'completed' THEN 'Finished.'
        ELSE 'Review the recorded error.'
    END;
    UPDATE operations.operator_job_runs
       SET status = p_status, stage = v_stage, stage_detail = v_detail,
           stage_updated_at = now(), heartbeat_at = now(), completed_at = now(),
           lease_expires_at = NULL, rows_touched = p_rows_touched, error = p_error,
           result = p_result,
           terminal_reason = CASE WHEN p_status = 'completed' THEN 'completed' ELSE 'failed' END
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running' AND claim_token = p_claim_token;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs finish is unavailable or fenced';
    END IF;
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = p_status
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
       AND claim_token = p_claim_token AND state = 'held';
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, p_run_id, p_status, v_stage, v_detail);
END
$function$;

ALTER FUNCTION operations.jobs_claim_next_v3(BIGINT, TEXT, UUID)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_claim_next_v3(BIGINT, TEXT, UUID),
    operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v3(BIGINT, TEXT, UUID),
    operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0207_jobs_claim_result_api"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
