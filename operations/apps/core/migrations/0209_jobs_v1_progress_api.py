"""Allow a fenced v1 worker to record factual progress and heartbeats."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION operations.jobs_record_v1_progress(
    p_tenant_id BIGINT,
    p_run_id UUID,
    p_claim_token UUID,
    p_stage TEXT DEFAULT NULL,
    p_detail TEXT DEFAULT NULL
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
       OR p_stage IS NOT NULL AND length(p_stage) NOT BETWEEN 1 AND 120
       OR p_detail IS NOT NULL AND length(p_detail) > 2000
    THEN
        RAISE EXCEPTION 'Jobs progress context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.operator_job_runs
       SET stage = COALESCE(p_stage, stage),
           stage_detail = COALESCE(p_detail, stage_detail),
           stage_updated_at = CASE WHEN p_stage IS NULL AND p_detail IS NULL
                               THEN stage_updated_at ELSE now() END,
           heartbeat_at = now(),
           lease_expires_at = now() + INTERVAL '90 minutes'
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running' AND claim_token = p_claim_token
     RETURNING stage, stage_detail INTO v_stage, v_detail;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs progress is unavailable or fenced';
    END IF;
    IF p_stage IS NOT NULL OR p_detail IS NOT NULL THEN
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, p_run_id, 'stage', v_stage, v_detail);
    END IF;
END
$function$;

ALTER FUNCTION operations.jobs_record_v1_progress(BIGINT, UUID, UUID, TEXT, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_record_v1_progress(BIGINT, UUID, UUID, TEXT, TEXT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_record_v1_progress(BIGINT, UUID, UUID, TEXT, TEXT)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0208_jobs_v1_worker_api"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
