"""Add governed cancellation transitions for durable Jobs runs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
CREATE FUNCTION operations.jobs_cancel_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_actor_id INTEGER, p_reason TEXT DEFAULT ''
) RETURNS TEXT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_status TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_actor_id IS NULL OR length(p_reason) > 500
       OR NOT EXISTS (SELECT 1 FROM operations.users WHERE tenant_id = p_tenant_id AND id = p_actor_id)
    THEN RAISE EXCEPTION 'Jobs cancellation context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.operator_job_runs
       SET status = 'cancelled', stage = 'Cancelled',
           stage_detail = 'Cancelled before work started.', stage_updated_at = now(),
           completed_at = now(), error = 'Cancelled before work started.',
           terminal_reason = 'cancelled', cancellation_requested_by_id = p_actor_id,
           cancellation_requested_at = now(), cancellation_reason = p_reason
     WHERE tenant_id = p_tenant_id AND id = p_run_id AND status = 'queued';
    IF FOUND THEN
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, p_run_id, 'cancelled', 'Cancelled', 'Cancelled before work started.');
        RETURN 'cancelled';
    END IF;
    UPDATE operations.operator_job_runs
       SET cancellation_requested_by_id = p_actor_id, cancellation_requested_at = now(),
           cancellation_reason = p_reason, stage_detail = 'Cancellation requested; worker will stop at a safe checkpoint.',
           stage_updated_at = now()
     WHERE tenant_id = p_tenant_id AND id = p_run_id AND contract_version = 1 AND status = 'running';
    IF FOUND THEN
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, p_run_id, 'cancellation_requested', 'Cancellation requested',
                'Worker termination is not permitted until the handler reaches a reviewed safe checkpoint.');
        RETURN 'requested';
    END IF;
    RETURN '';
END
$function$;
ALTER FUNCTION operations.jobs_cancel_v1(BIGINT, UUID, INTEGER, TEXT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_cancel_v1(BIGINT, UUID, INTEGER, TEXT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_cancel_v1(BIGINT, UUID, INTEGER, TEXT) TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0212_jobs_durable_schedule_runtime"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
