"""Activate completion dependencies and propagate prerequisite terminal state."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION operations.jobs_propagate_dependency_terminal_v1(
    p_tenant_id BIGINT, p_prerequisite_run_id UUID, p_status TEXT
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_count BIGINT := 0;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_prerequisite_run_id IS NULL
       OR p_status NOT IN ('completed', 'failed', 'cancelled', 'stalled')
    THEN RAISE EXCEPTION 'Jobs dependency terminal context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    IF p_status = 'completed' THEN
        WITH released AS (
            UPDATE operations.job_dependencies
               SET state = 'released', reason = '', resolved_at = now()
             WHERE tenant_id = p_tenant_id
               AND prerequisite_run_id = p_prerequisite_run_id
               AND state = 'waiting'
               AND required_output_revision = repeat('0', 64)
         RETURNING dependent_run_id
        ), ready AS (
            UPDATE operations.operator_job_runs run
               SET wait_category = NULL, wait_reason = NULL
             WHERE run.tenant_id = p_tenant_id
               AND run.id IN (SELECT dependent_run_id FROM released)
               AND NOT EXISTS (
                   SELECT 1 FROM operations.job_dependencies dependency
                    WHERE dependency.tenant_id = p_tenant_id
                      AND dependency.dependent_run_id = run.id
                      AND dependency.state <> 'released'
               )
         RETURNING run.id
        ), events AS (
            INSERT INTO operations.operator_job_events (
                tenant_id, job_id, event_type, stage, detail
            )
            SELECT p_tenant_id, id, 'dependency_released', 'Queued',
                   'Required prerequisite completed.' FROM ready
        )
        SELECT count(*) INTO v_count FROM released;
        RETURN v_count;
    END IF;

    WITH RECURSIVE blocked(run_id) AS (
        SELECT dependency.dependent_run_id
          FROM operations.job_dependencies dependency
         WHERE dependency.tenant_id = p_tenant_id
           AND dependency.prerequisite_run_id = p_prerequisite_run_id
           AND dependency.state = 'waiting'
        UNION
        SELECT dependency.dependent_run_id
          FROM operations.job_dependencies dependency
          JOIN blocked ON blocked.run_id = dependency.prerequisite_run_id
         WHERE dependency.tenant_id = p_tenant_id
           AND dependency.state = 'waiting'
    ), blocked_edges AS (
        UPDATE operations.job_dependencies dependency
           SET state = 'blocked',
               reason = 'A required prerequisite did not complete successfully.',
               resolved_at = now()
         WHERE dependency.tenant_id = p_tenant_id
           AND dependency.dependent_run_id IN (SELECT run_id FROM blocked)
           AND dependency.state = 'waiting'
     RETURNING dependency.dependent_run_id
    ), terminal AS (
        UPDATE operations.operator_job_runs run
           SET status = 'stalled', stage = 'Needs attention',
               stage_detail = 'A required prerequisite did not complete successfully.',
               stage_updated_at = now(), completed_at = now(),
               wait_category = 'dependency',
               wait_reason = 'A required prerequisite did not complete successfully.',
               terminal_reason = 'prerequisite_failed'
         WHERE run.tenant_id = p_tenant_id AND run.status = 'queued'
           AND run.id IN (SELECT run_id FROM blocked)
     RETURNING run.id
    ), events AS (
        INSERT INTO operations.operator_job_events (
            tenant_id, job_id, event_type, stage, detail
        )
        SELECT p_tenant_id, id, 'dependency_blocked', 'Needs attention',
               'A required prerequisite did not complete successfully.' FROM terminal
    )
    SELECT count(*) INTO v_count FROM terminal;
    RETURN v_count;
END
$function$;

CREATE FUNCTION operations.jobs_add_completion_dependency_v1(
    p_tenant_id BIGINT, p_dependent_run_id UUID, p_prerequisite_run_id UUID
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_dependency_id UUID;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_dependent_run_id IS NULL OR p_prerequisite_run_id IS NULL
    THEN RAISE EXCEPTION 'Jobs completion dependency context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    SELECT id INTO v_dependency_id
      FROM operations.job_dependencies
     WHERE tenant_id = p_tenant_id
       AND dependent_run_id = p_dependent_run_id
       AND prerequisite_run_id = p_prerequisite_run_id;
    IF v_dependency_id IS NOT NULL THEN RETURN v_dependency_id; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id AND id = p_dependent_run_id
           AND contract_version = 1 AND status = 'queued'
    ) OR NOT EXISTS (
        SELECT 1 FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id AND id = p_prerequisite_run_id
           AND contract_version = 1 AND status IN ('queued', 'running')
    ) THEN RAISE EXCEPTION 'Jobs completion dependency requires active converted runs'; END IF;
    v_dependency_id := operations.jobs_add_dependency_v1(
        p_tenant_id, p_dependent_run_id, p_prerequisite_run_id,
        '{}'::jsonb, repeat('0', 64)
    );
    UPDATE operations.operator_job_runs
       SET wait_category = 'dependency',
           wait_reason = 'Waiting for a required prerequisite to complete.',
           parent_run_id = COALESCE(parent_run_id, p_prerequisite_run_id),
           root_run_id = COALESCE(
               root_run_id,
               (SELECT COALESCE(root_run_id, id)
                  FROM operations.operator_job_runs
                 WHERE tenant_id = p_tenant_id AND id = p_prerequisite_run_id)
           )
     WHERE tenant_id = p_tenant_id AND id = p_dependent_run_id AND status = 'queued';
    INSERT INTO operations.operator_job_events (
        tenant_id, job_id, event_type, stage, detail
    ) VALUES (
        p_tenant_id, p_dependent_run_id, 'dependency_wait', 'Queued',
        'Waiting for a required prerequisite to complete.'
    );
    RETURN v_dependency_id;
END
$function$;

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
           lease_expires_at = NULL, rows_touched = p_rows_touched, error = p_error,
           result = p_result,
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

CREATE OR REPLACE FUNCTION operations.jobs_finish_cancelled_v1(
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
    PERFORM operations.jobs_propagate_dependency_terminal_v1(
        p_tenant_id, p_run_id, 'cancelled'
    );
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_contain_expired_v1(
    p_tenant_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_count BIGINT := 0; v_run RECORD;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
    THEN RAISE EXCEPTION 'Jobs timeout context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    FOR v_run IN
        UPDATE operations.operator_job_runs
           SET status = 'stalled', stage = 'Needs attention',
               stage_detail = 'Execution exceeded its safety deadline; resources remain contained.',
               stage_updated_at = now(), completed_at = now(), lease_expires_at = NULL,
               error = 'Execution exceeded the safety deadline. Verify the worker before retrying.',
               terminal_reason = 'timeout'
         WHERE tenant_id = p_tenant_id AND contract_version = 1
           AND status = 'running' AND deadline_at <= now()
     RETURNING id, claim_token
    LOOP
        UPDATE operations.job_resource_claims
           SET state = 'contained', release_reason = 'timeout contained'
         WHERE tenant_id = p_tenant_id AND run_id = v_run.id
           AND claim_token = v_run.claim_token AND state = 'held';
        INSERT INTO operations.operator_job_events (
            tenant_id, job_id, event_type, stage, detail
        ) VALUES (
            p_tenant_id, v_run.id, 'timeout', 'Needs attention',
            'Execution exceeded its safety deadline; resources remain contained.'
        );
        PERFORM operations.jobs_propagate_dependency_terminal_v1(
            p_tenant_id, v_run.id, 'stalled'
        );
        v_count := v_count + 1;
    END LOOP;
    RETURN v_count;
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_cancel_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_actor_id INTEGER, p_reason TEXT DEFAULT ''
) RETURNS TEXT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_actor_id IS NULL OR length(p_reason) > 500
       OR NOT EXISTS (
           SELECT 1 FROM operations.users
            WHERE tenant_id = p_tenant_id AND id = p_actor_id
       )
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
        PERFORM operations.jobs_propagate_dependency_terminal_v1(
            p_tenant_id, p_run_id, 'cancelled'
        );
        RETURN 'cancelled';
    END IF;
    UPDATE operations.operator_job_runs
       SET cancellation_requested_by_id = p_actor_id, cancellation_requested_at = now(),
           cancellation_reason = p_reason,
           stage_detail = 'Cancellation requested; worker will stop at a safe checkpoint.',
           stage_updated_at = now()
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running';
    IF FOUND THEN
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (
            p_tenant_id, p_run_id, 'cancellation_requested', 'Cancellation requested',
            'Worker termination is not permitted until a reviewed safe checkpoint.'
        );
        RETURN 'requested';
    END IF;
    RETURN '';
END
$function$;

ALTER FUNCTION operations.jobs_propagate_dependency_terminal_v1(BIGINT, UUID, TEXT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_add_completion_dependency_v1(BIGINT, UUID, UUID)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_finish_cancelled_v1(BIGINT, UUID, UUID)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_contain_expired_v1(BIGINT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_cancel_v1(BIGINT, UUID, INTEGER, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION
    operations.jobs_propagate_dependency_terminal_v1(BIGINT, UUID, TEXT),
    operations.jobs_add_completion_dependency_v1(BIGINT, UUID, UUID)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_add_completion_dependency_v1(BIGINT, UUID, UUID)
    TO operations_app, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0220_jobs_v0_cutover"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
