"""Keep workflow coordinators waiting until every required child succeeds."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION operations.jobs_reconcile_workflow_ancestors_v1(
    p_tenant_id BIGINT, p_run_id UUID
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_changed BIGINT; v_iteration BIGINT; v_total BIGINT := 0;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL
    THEN RAISE EXCEPTION 'Jobs workflow reconciliation context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    LOOP
        WITH RECURSIVE ancestors(run_id) AS (
            SELECT p_run_id
            UNION
            SELECT dependency.prerequisite_run_id
              FROM operations.job_dependencies dependency
              JOIN ancestors ON ancestors.run_id = dependency.dependent_run_id
             WHERE dependency.tenant_id = p_tenant_id
               AND dependency.required_output_revision = repeat('0', 64)
        ), blocked AS (
            UPDATE operations.operator_job_runs coordinator
               SET status = 'stalled', stage = 'Needs attention',
                   stage_detail = 'Required workflow work did not complete successfully.',
                   stage_updated_at = now(), completed_at = now(),
                   wait_category = 'dependency',
                   wait_reason = 'Required workflow work did not complete successfully.',
                   terminal_reason = 'required_child_failed', heartbeat_at = NULL,
                   worker_incarnation = NULL, claim_token = NULL
             WHERE coordinator.tenant_id = p_tenant_id
               AND coordinator.id IN (SELECT run_id FROM ancestors)
               AND coordinator.status = 'running'
               AND coordinator.wait_category = 'workflow'
               AND coordinator.terminal_reason = 'handler_completed'
               AND EXISTS (
                   SELECT 1
                     FROM operations.job_dependencies edge
                     JOIN operations.operator_job_runs child
                       ON child.tenant_id = edge.tenant_id
                      AND child.id = edge.dependent_run_id
                    WHERE edge.tenant_id = p_tenant_id
                      AND edge.prerequisite_run_id = coordinator.id
                      AND edge.required_output_revision = repeat('0', 64)
                      AND child.status IN ('failed', 'cancelled', 'stalled')
               )
         RETURNING coordinator.id
        ), events AS (
            INSERT INTO operations.operator_job_events (
                tenant_id, job_id, event_type, stage, detail
            )
            SELECT p_tenant_id, id, 'workflow_blocked', 'Needs attention',
                   'Required workflow work did not complete successfully.' FROM blocked
        )
        SELECT count(*) INTO v_changed FROM blocked;
        v_total := v_total + v_changed;
        v_iteration := v_changed;

        WITH RECURSIVE ancestors(run_id) AS (
            SELECT p_run_id
            UNION
            SELECT dependency.prerequisite_run_id
              FROM operations.job_dependencies dependency
              JOIN ancestors ON ancestors.run_id = dependency.dependent_run_id
             WHERE dependency.tenant_id = p_tenant_id
               AND dependency.required_output_revision = repeat('0', 64)
        ), ready AS (
            UPDATE operations.operator_job_runs coordinator
               SET status = 'completed', stage = 'Completed',
                   stage_detail = 'All required workflow work completed.',
                   stage_updated_at = now(), completed_at = now(),
                   wait_category = NULL, wait_reason = NULL,
                   terminal_reason = 'completed', heartbeat_at = NULL,
                   worker_incarnation = NULL, claim_token = NULL
             WHERE coordinator.tenant_id = p_tenant_id
               AND coordinator.id IN (SELECT run_id FROM ancestors)
               AND coordinator.status = 'running'
               AND coordinator.wait_category = 'workflow'
               AND coordinator.terminal_reason = 'handler_completed'
               AND EXISTS (
                   SELECT 1 FROM operations.job_dependencies edge
                    WHERE edge.tenant_id = p_tenant_id
                      AND edge.prerequisite_run_id = coordinator.id
                      AND edge.required_output_revision = repeat('0', 64)
               )
               AND NOT EXISTS (
                   SELECT 1
                     FROM operations.job_dependencies edge
                     JOIN operations.operator_job_runs child
                       ON child.tenant_id = edge.tenant_id
                      AND child.id = edge.dependent_run_id
                    WHERE edge.tenant_id = p_tenant_id
                      AND edge.prerequisite_run_id = coordinator.id
                      AND edge.required_output_revision = repeat('0', 64)
                      AND child.status <> 'completed'
               )
         RETURNING coordinator.id
        ), events AS (
            INSERT INTO operations.operator_job_events (
                tenant_id, job_id, event_type, stage, detail
            )
            SELECT p_tenant_id, id, 'workflow_completed', 'Completed',
                   'All required workflow work completed.' FROM ready
        )
        SELECT count(*) INTO v_changed FROM ready;
        v_total := v_total + v_changed;
        v_iteration := v_iteration + v_changed;
        EXIT WHEN v_iteration = 0;
    END LOOP;
    RETURN v_total;
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_propagate_dependency_terminal_v1(
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
               SET wait_category = NULL, wait_reason = NULL,
                   stage = 'Queued', stage_detail = 'Required prerequisites completed.',
                   stage_updated_at = now()
             WHERE run.tenant_id = p_tenant_id
               AND run.id IN (SELECT dependent_run_id FROM released)
               AND run.status = 'queued'
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
                   'Required prerequisites completed.' FROM ready
        )
        SELECT count(*) INTO v_count FROM released;
        PERFORM operations.jobs_reconcile_workflow_ancestors_v1(
            p_tenant_id, p_prerequisite_run_id
        );
        RETURN v_count;
    END IF;

    WITH RECURSIVE blocked(run_id) AS (
        SELECT dependency.dependent_run_id
          FROM operations.job_dependencies dependency
          JOIN operations.operator_job_runs dependent
            ON dependent.tenant_id = dependency.tenant_id
           AND dependent.id = dependency.dependent_run_id
         WHERE dependency.tenant_id = p_tenant_id
           AND dependency.prerequisite_run_id = p_prerequisite_run_id
           AND dependency.required_output_revision = repeat('0', 64)
           AND dependent.status <> 'completed'
        UNION
        SELECT dependency.dependent_run_id
          FROM operations.job_dependencies dependency
          JOIN blocked ON blocked.run_id = dependency.prerequisite_run_id
          JOIN operations.operator_job_runs dependent
            ON dependent.tenant_id = dependency.tenant_id
           AND dependent.id = dependency.dependent_run_id
         WHERE dependency.tenant_id = p_tenant_id
           AND dependency.required_output_revision = repeat('0', 64)
           AND dependent.status <> 'completed'
    ), blocked_edges AS (
        UPDATE operations.job_dependencies dependency
           SET state = 'blocked',
               reason = 'A required prerequisite did not complete successfully.',
               resolved_at = now()
         WHERE dependency.tenant_id = p_tenant_id
           AND dependency.dependent_run_id IN (SELECT run_id FROM blocked)
           AND dependency.required_output_revision = repeat('0', 64)
           AND dependency.state <> 'blocked'
     RETURNING dependency.dependent_run_id
    ), terminal AS (
        UPDATE operations.operator_job_runs run
           SET status = 'stalled', stage = 'Needs attention',
               stage_detail = 'A required prerequisite did not complete successfully.',
               stage_updated_at = now(), completed_at = now(),
               wait_category = 'dependency',
               wait_reason = 'A required prerequisite did not complete successfully.',
               terminal_reason = 'prerequisite_failed', heartbeat_at = NULL,
               worker_incarnation = NULL, claim_token = NULL, deadline_at = NULL
         WHERE run.tenant_id = p_tenant_id
           AND (run.status = 'queued' OR (
               run.status = 'running' AND run.wait_category = 'workflow'
               AND run.terminal_reason = 'handler_completed'
           ))
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
    PERFORM operations.jobs_reconcile_workflow_ancestors_v1(
        p_tenant_id, p_prerequisite_run_id
    );
    RETURN v_count;
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
DECLARE v_context_tenant BIGINT; v_stage TEXT; v_detail TEXT; v_coordinates BOOLEAN;
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
    SELECT p_status = 'completed' AND EXISTS (
        SELECT 1 FROM operations.job_dependencies
         WHERE tenant_id = p_tenant_id AND prerequisite_run_id = p_run_id
           AND required_output_revision = repeat('0', 64)
    ) INTO v_coordinates;
    v_stage := CASE WHEN v_coordinates THEN 'Waiting for required work'
                    WHEN p_status = 'completed' THEN 'Completed' ELSE 'Failed' END;
    v_detail := CASE WHEN v_coordinates THEN 'The handler finished; required workflow work is still running.'
                     WHEN p_status = 'completed' THEN 'Finished.' ELSE 'Review the recorded error.' END;
    UPDATE operations.operator_job_runs
       SET status = CASE WHEN v_coordinates THEN 'running' ELSE p_status END,
           stage = v_stage, stage_detail = v_detail, stage_updated_at = now(),
           heartbeat_at = CASE WHEN v_coordinates THEN NULL ELSE now() END,
           completed_at = CASE WHEN v_coordinates THEN NULL ELSE now() END,
           lease_expires_at = NULL, deadline_at = NULL,
           rows_touched = p_rows_touched, error = p_error, result = p_result,
           wait_category = CASE WHEN v_coordinates THEN 'workflow' ELSE NULL END,
           wait_reason = CASE WHEN v_coordinates THEN v_detail ELSE NULL END,
           worker_incarnation = CASE WHEN v_coordinates THEN NULL ELSE worker_incarnation END,
           claim_token = CASE WHEN v_coordinates THEN NULL ELSE claim_token END,
           terminal_reason = CASE WHEN v_coordinates THEN 'handler_completed'
                                  WHEN p_status = 'completed' THEN 'completed' ELSE 'failed' END
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running' AND claim_token = p_claim_token;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs finish is unavailable or fenced'; END IF;
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = p_status
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
       AND claim_token = p_claim_token AND state = 'held';
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (
        p_tenant_id, p_run_id,
        CASE WHEN v_coordinates THEN 'handler_completed' ELSE p_status END,
        v_stage, v_detail
    );
    PERFORM operations.jobs_propagate_dependency_terminal_v1(
        p_tenant_id, p_run_id, p_status
    );
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
           stage_detail = 'Cancelled while queued or waiting for required work.',
           stage_updated_at = now(), completed_at = now(), deadline_at = NULL,
           error = 'Cancelled while queued or waiting for required work.',
           terminal_reason = 'cancelled', cancellation_requested_by_id = p_actor_id,
           cancellation_requested_at = now(), cancellation_reason = p_reason,
           heartbeat_at = NULL, worker_incarnation = NULL, claim_token = NULL
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND (status = 'queued' OR (
           status = 'running' AND wait_category = 'workflow'
           AND terminal_reason = 'handler_completed'
       ));
    IF FOUND THEN
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (
            p_tenant_id, p_run_id, 'cancelled', 'Cancelled',
            'Cancelled while queued or waiting for required work.'
        );
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

ALTER FUNCTION operations.jobs_reconcile_workflow_ancestors_v1(BIGINT, UUID)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_propagate_dependency_terminal_v1(BIGINT, UUID, TEXT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_cancel_v1(BIGINT, UUID, INTEGER, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_reconcile_workflow_ancestors_v1(BIGINT, UUID)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0221_jobs_completion_dependencies"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
