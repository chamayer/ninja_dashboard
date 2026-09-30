"""Add fenced cooperative-cancellation APIs for v1 Jobs workers."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE FUNCTION operations.jobs_should_cancel_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_claim_token UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_requested BOOLEAN;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL
    THEN RAISE EXCEPTION 'Jobs cancellation check is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    SELECT cancellation_requested_at IS NOT NULL INTO v_requested
      FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant_id AND id = p_run_id AND contract_version = 1
       AND status = 'running' AND claim_token = p_claim_token;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs cancellation check is unavailable or fenced'; END IF;
    RETURN v_requested;
END
$function$;

CREATE FUNCTION operations.jobs_finish_cancelled_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_claim_token UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL
    THEN RAISE EXCEPTION 'Jobs cancellation finish is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.operator_job_runs
       SET status = 'cancelled', stage = 'Cancelled',
           stage_detail = 'Stopped at a safe worker checkpoint.', stage_updated_at = now(),
           heartbeat_at = now(), completed_at = now(), lease_expires_at = NULL,
           terminal_reason = 'cancelled'
     WHERE tenant_id = p_tenant_id AND id = p_run_id AND contract_version = 1
       AND status = 'running' AND claim_token = p_claim_token
       AND cancellation_requested_at IS NOT NULL;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs cancellation finish is unavailable or fenced'; END IF;
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = 'cancelled'
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
       AND claim_token = p_claim_token AND state = 'held';
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, p_run_id, 'cancelled', 'Cancelled', 'Stopped at a safe worker checkpoint.');
END
$function$;

ALTER FUNCTION operations.jobs_should_cancel_v1(BIGINT, UUID, UUID) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_finish_cancelled_v1(BIGINT, UUID, UUID) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_should_cancel_v1(BIGINT, UUID, UUID),
    operations.jobs_finish_cancelled_v1(BIGINT, UUID, UUID)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_should_cancel_v1(BIGINT, UUID, UUID),
    operations.jobs_finish_cancelled_v1(BIGINT, UUID, UUID) TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0216_jobs_retry_lineage_api"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
