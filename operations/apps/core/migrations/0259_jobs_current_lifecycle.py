"""Provide the canonical current lifecycle over existing Jobs facts."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
-- This function is the shared interpretation of active durable run facts.  It
-- intentionally stores nothing: execution remains the authority for state.
CREATE FUNCTION operations.jobs_current_lifecycle_v1(p_tenant_id BIGINT)
RETURNS TABLE(lifecycle TEXT, run_count BIGINT, oldest_requested_at TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs lifecycle context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    RETURN QUERY
    SELECT CASE
        WHEN run.status = 'running' THEN 'running'
        WHEN run.status = 'queued' AND run.wait_category IS NULL THEN 'ready'
        WHEN run.status = 'queued' AND run.wait_category IN ('dependency', 'workflow') THEN 'waiting_for_data'
        WHEN run.status = 'queued' AND run.wait_category = 'resource' THEN 'waiting_for_protected_update'
        WHEN run.status = 'queued' AND run.wait_category = 'capacity' THEN 'waiting_for_capacity'
        ELSE 'waiting'
    END, count(*), min(run.requested_at)
    FROM operations.operator_job_runs run
    WHERE run.tenant_id = p_tenant_id AND run.status IN ('queued', 'running')
    GROUP BY 1;
END
$function$;
ALTER FUNCTION operations.jobs_current_lifecycle_v1(BIGINT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_current_lifecycle_v1(BIGINT)
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_current_lifecycle_v1(BIGINT) TO ninja_ingest;

CREATE OR REPLACE FUNCTION operations.jobs_admin_diagnostics_v1(
    p_tenant_id BIGINT, p_section TEXT, p_limit INTEGER, p_offset INTEGER
) RETURNS TABLE(total_count BIGINT, item JSONB)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_section IS NULL OR p_section NOT IN (
           'health', 'definition_versions', 'schedules', 'schedule_events', 'requests',
           'runs', 'events', 'dependencies', 'domain_attempts', 'lane_limits',
           'resource_limits', 'resource_claims', 'runtimes'
       )
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
       OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
    THEN RAISE EXCEPTION 'Jobs administrator diagnostics context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    IF p_section = 'health' THEN
        RETURN QUERY
        WITH lifecycle AS (
            SELECT lifecycle, run_count
              FROM operations.jobs_current_lifecycle_v1(p_tenant_id)
        )
        SELECT 1::bigint, jsonb_build_object(
            'ready_runs', COALESCE((SELECT run_count FROM lifecycle WHERE lifecycle = 'ready'), 0),
            'running_runs', COALESCE((SELECT run_count FROM lifecycle WHERE lifecycle = 'running'), 0),
            'waiting_for_data', COALESCE((SELECT run_count FROM lifecycle WHERE lifecycle = 'waiting_for_data'), 0),
            'waiting_for_protected_update', COALESCE((SELECT run_count FROM lifecycle WHERE lifecycle = 'waiting_for_protected_update'), 0),
            'waiting_for_capacity', COALESCE((SELECT run_count FROM lifecycle WHERE lifecycle = 'waiting_for_capacity'), 0),
            'waiting_runs', COALESCE((SELECT sum(run_count) FROM lifecycle WHERE lifecycle LIKE 'waiting%'), 0),
            'stalled_runs', (SELECT count(*) FROM operations.operator_job_runs
                             WHERE tenant_id = p_tenant_id AND status = 'stalled'),
            'held_claims', (SELECT count(*) FROM operations.job_resource_claims
                             WHERE tenant_id = p_tenant_id AND state = 'held'),
            'contained_claims', (SELECT count(*) FROM operations.job_resource_claims
                                  WHERE tenant_id = p_tenant_id AND state = 'contained'),
            'enabled_schedules', (SELECT count(*) FROM operations.job_schedules
                                  WHERE tenant_id = p_tenant_id AND enabled),
            'schedule_events', (SELECT count(*) FROM operations.job_schedule_events
                                WHERE tenant_id = p_tenant_id),
            'request_aliases', (SELECT count(*) FROM operations.job_requests
                                WHERE tenant_id = p_tenant_id)
        );
    ELSIF p_section = 'definition_versions' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, definition_key, definition_digest,
                   handler_version, metadata, created_at
              FROM operations.job_definition_versions
             ORDER BY created_at DESC, definition_key, definition_digest
             LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'schedules' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, definition_key, definition_digest,
                   scope_identity, enabled, capability_reason, cadence, anchor_at,
                   time_zone, next_due_at, last_consumed_due_at, last_requested_at,
                   last_request_id, last_run_id, last_outcome, configuration_revision
              FROM operations.job_schedules WHERE tenant_id = p_tenant_id
             ORDER BY definition_key, id LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'schedule_events' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, schedule_id, definition_key,
                   definition_digest, configuration_revision, due_at, recorded_at,
                   outcome, consumed_ticks, reason, request_id, run_id
              FROM operations.job_schedule_events WHERE tenant_id = p_tenant_id
             ORDER BY recorded_at DESC, id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'requests' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, definition_key, definition_digest,
                   scope_identity, request_identity, run_id, actor_id, trigger_kind,
                   requested_input_revisions, requested_at
              FROM operations.job_requests WHERE tenant_id = p_tenant_id
             ORDER BY requested_at DESC, id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'runs' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, job_key, status, lane,
                   contract_version, definition_digest, trigger_kind, scope_identity,
                   requested_at, started_at, completed_at, stage, stage_detail,
                   wait_category, wait_reason, attempts, rows_touched, terminal_reason,
                   correlation_id, parent_run_id, root_run_id, retry_of_run_id,
                   input_revisions, output_revisions, request_payload, result,
                   cancellation_requested_at, deadline_at, heartbeat_at,
                   worker_incarnation, claim_generation
              FROM operations.operator_job_runs WHERE tenant_id = p_tenant_id
             ORDER BY requested_at DESC, id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'events' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, job_id, event_at,
                   event_type, stage, detail
              FROM operations.operator_job_events WHERE tenant_id = p_tenant_id
             ORDER BY event_at DESC, id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'dependencies' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, dependent_run_id,
                   prerequisite_run_id, required_input_revisions,
                   required_output_revision, failure_rule, state, reason,
                   created_at, resolved_at
              FROM operations.job_dependencies WHERE tenant_id = p_tenant_id
             ORDER BY created_at DESC, id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'domain_attempts' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, domain_kind, domain_record_id,
                   attempt_number, job_run_id, linked_at
              FROM operations.job_domain_attempts WHERE tenant_id = p_tenant_id
             ORDER BY linked_at DESC, id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'lane_limits' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, lane, capacity, policy_revision
              FROM operations.job_lane_limits WHERE tenant_id = p_tenant_id
             ORDER BY lane LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'resource_limits' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, resource_template, capacity,
                   policy_revision
              FROM operations.job_resource_limits
             ORDER BY resource_template LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'resource_claims' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, id, run_id, claim_generation,
                   resource_template, resource_identity, state, claimed_at,
                   released_at, release_reason
              FROM operations.job_resource_claims WHERE tenant_id = p_tenant_id
             ORDER BY claimed_at DESC, id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    ELSE
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, runtime_kind, runtime_identity,
                   registry_digest, metadata, started_at, heartbeat_at, stopped_at
              FROM operations.job_runtime_heartbeats WHERE tenant_id = p_tenant_id
             ORDER BY heartbeat_at DESC, runtime_kind, runtime_identity
             LIMIT p_limit OFFSET p_offset
        ) page;
    END IF;
END
$function$;
ALTER FUNCTION operations.jobs_admin_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
    OWNER TO operations_migrate;

CREATE OR REPLACE FUNCTION operations.jobs_health_measurements_v1(p_tenant_id BIGINT)
RETURNS TABLE(kind TEXT, payload JSONB)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs health measurement context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    RETURN QUERY SELECT 'schedule_failure', jsonb_build_object(
        'schedule_id', schedule.id, 'job_key', schedule.definition_key,
        'job_run_id', schedule.last_run_id, 'last_outcome', schedule.last_outcome,
        'completed_at', run.completed_at, 'terminal_reason', run.terminal_reason
    ) FROM operations.job_schedules schedule
      LEFT JOIN operations.operator_job_runs run ON run.tenant_id = schedule.tenant_id AND run.id = schedule.last_run_id
     WHERE schedule.tenant_id = p_tenant_id AND schedule.last_outcome IN ('failed', 'stalled', 'cancelled');

    RETURN QUERY SELECT 'required_disabled', jsonb_build_object(
        'schedule_id', schedule.id, 'job_key', schedule.definition_key,
        'capability_reason', schedule.capability_reason, 'configuration_revision', schedule.configuration_revision
    ) FROM operations.job_schedules schedule
      JOIN operations.job_definition_versions definition_version
        ON definition_version.definition_key = schedule.definition_key
       AND definition_version.definition_digest = schedule.definition_digest
     WHERE schedule.tenant_id = p_tenant_id AND NOT schedule.enabled
       AND definition_version.metadata ->> 'capability' = 'always';

    RETURN QUERY
    SELECT 'queue_backlog', jsonb_build_object(
        'queue_key', registry.queue_key, 'pending_depth', metrics.pending_depth,
        'oldest_pending_minutes', round(metrics.oldest_pending_minutes::numeric, 1),
        'max_depth', registry.max_depth, 'max_pending_age_m', registry.max_pending_age_m,
        'breached', to_jsonb(ARRAY_REMOVE(ARRAY[
            CASE WHEN registry.max_depth > 0 AND metrics.pending_depth > registry.max_depth THEN 'depth' END,
            CASE WHEN registry.max_pending_age_m > 0 AND metrics.oldest_pending_minutes > registry.max_pending_age_m THEN 'age' END
        ], NULL))
    ) FROM operations.queue_registry registry
      CROSS JOIN LATERAL (
          SELECT COALESCE(max(run_count) FILTER (WHERE lifecycle = 'ready'), 0) AS pending_depth,
                 COALESCE(EXTRACT(EPOCH FROM (now() - min(oldest_requested_at) FILTER (WHERE lifecycle = 'ready'))) / 60, 0) AS oldest_pending_minutes
            FROM operations.jobs_current_lifecycle_v1(p_tenant_id)
      ) metrics
     WHERE registry.queue_key = 'operator.jobs' AND registry.enabled;

    RETURN QUERY SELECT 'repeated_failure', jsonb_build_object(
        'job_key', run.job_key, 'failed_runs_24h', count(*), 'max_failure_count', registry.max_failure_count,
        'job_run_id', (array_agg(run.id ORDER BY run.completed_at DESC))[1], 'latest_failure_at', max(run.completed_at), 'window_hours', 24
    ) FROM operations.operator_job_runs run JOIN operations.queue_registry registry ON registry.queue_key = 'operator.jobs'
     WHERE run.tenant_id = p_tenant_id AND run.status IN ('failed', 'stalled') AND run.completed_at >= now() - interval '24 hours'
     GROUP BY run.job_key, registry.max_failure_count HAVING count(*) > registry.max_failure_count;

    RETURN QUERY SELECT 'timeout', jsonb_build_object(
        'job_run_id', run.id, 'job_key', run.job_key, 'completed_at', run.completed_at, 'terminal_reason', run.terminal_reason
    ) FROM operations.operator_job_runs run
     WHERE run.tenant_id = p_tenant_id AND run.terminal_reason = 'timeout' AND run.completed_at >= now() - interval '24 hours';

    RETURN QUERY SELECT 'unmet_dependency', jsonb_build_object(
        'dependency_id', dependency.id, 'state', dependency.state, 'reason', dependency.reason, 'created_at', dependency.created_at,
        'dependent_job_run_id', dependent.id, 'job_key', dependent.job_key, 'prerequisite_job_run_id', prerequisite.id,
        'prerequisite_job_key', prerequisite.job_key, 'max_pending_age_m', registry.max_pending_age_m
    ) FROM operations.job_dependencies dependency
      JOIN operations.operator_job_runs dependent ON dependent.tenant_id = dependency.tenant_id AND dependent.id = dependency.dependent_run_id
      JOIN operations.operator_job_runs prerequisite ON prerequisite.tenant_id = dependency.tenant_id AND prerequisite.id = dependency.prerequisite_run_id
      JOIN operations.queue_registry registry ON registry.queue_key = 'operator.jobs'
     WHERE dependency.tenant_id = p_tenant_id
       AND (dependency.state = 'blocked' OR (dependency.state = 'waiting' AND registry.max_pending_age_m > 0
            AND dependency.created_at < now() - make_interval(mins => registry.max_pending_age_m)));

    RETURN QUERY SELECT 'control_snapshot', jsonb_build_object(
        'definition_versions', COALESCE((SELECT jsonb_agg(jsonb_build_object('definition_key', definition_key, 'definition_digest', definition_digest)) FROM operations.job_definition_versions), '[]'::jsonb),
        'schedules', COALESCE((SELECT jsonb_agg(jsonb_build_object('definition_key', definition_key, 'definition_digest', definition_digest)) FROM operations.job_schedules WHERE tenant_id = p_tenant_id), '[]'::jsonb),
        'lane_limits', COALESCE((SELECT jsonb_agg(jsonb_build_object('lane', lane, 'capacity', capacity)) FROM operations.job_lane_limits WHERE tenant_id = p_tenant_id), '[]'::jsonb),
        'resource_limits', COALESCE((SELECT jsonb_agg(jsonb_build_object('resource_template', resource_template, 'capacity', capacity)) FROM operations.job_resource_limits), '[]'::jsonb),
        'runtimes', COALESCE((SELECT jsonb_agg(jsonb_build_object('runtime_kind', runtime_kind, 'registry_digest', registry_digest, 'stopped_at', stopped_at, 'fresh', heartbeat_at >= now() - interval '3 minutes')) FROM operations.job_runtime_heartbeats WHERE tenant_id = p_tenant_id), '[]'::jsonb)
    );
END
$function$;
ALTER FUNCTION operations.jobs_health_measurements_v1(BIGINT) OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0258_jobs_recovery_contract")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
