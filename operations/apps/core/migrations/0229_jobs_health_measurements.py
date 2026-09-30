"""Expose bounded durable Jobs health measurements to the evaluator."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION operations.jobs_health_measurements_v1(p_tenant_id BIGINT)
RETURNS TABLE(kind TEXT, payload JSONB)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs health measurement context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    RETURN QUERY
    SELECT 'schedule_failure', jsonb_build_object(
        'schedule_id', schedule.id, 'job_key', schedule.definition_key,
        'job_run_id', schedule.last_run_id, 'last_outcome', schedule.last_outcome,
        'completed_at', run.completed_at, 'terminal_reason', run.terminal_reason
    )
      FROM operations.job_schedules schedule
      LEFT JOIN operations.operator_job_runs run
        ON run.tenant_id = schedule.tenant_id AND run.id = schedule.last_run_id
     WHERE schedule.tenant_id = p_tenant_id
       AND schedule.last_outcome IN ('failed', 'stalled', 'cancelled');

    RETURN QUERY
    SELECT 'required_disabled', jsonb_build_object(
        'schedule_id', schedule.id, 'job_key', schedule.definition_key,
        'capability_reason', schedule.capability_reason,
        'configuration_revision', schedule.configuration_revision
    )
      FROM operations.job_schedules schedule
      JOIN operations.job_definition_versions definition_version
        ON definition_version.definition_key = schedule.definition_key
       AND definition_version.definition_digest = schedule.definition_digest
     WHERE schedule.tenant_id = p_tenant_id AND NOT schedule.enabled
       AND definition_version.metadata ->> 'capability' = 'always';

    RETURN QUERY
    SELECT 'queue_backlog', jsonb_build_object(
        'queue_key', registry.queue_key,
        'pending_depth', metrics.pending_depth,
        'oldest_pending_minutes', round(metrics.oldest_pending_minutes::numeric, 1),
        'max_depth', registry.max_depth,
        'max_pending_age_m', registry.max_pending_age_m,
        'breached', to_jsonb(ARRAY_REMOVE(ARRAY[
            CASE WHEN registry.max_depth > 0 AND metrics.pending_depth > registry.max_depth THEN 'depth' END,
            CASE WHEN registry.max_pending_age_m > 0
                   AND metrics.oldest_pending_minutes > registry.max_pending_age_m THEN 'age' END
        ], NULL))
    )
      FROM operations.queue_registry registry
      CROSS JOIN LATERAL (
          SELECT count(*) FILTER (WHERE status = 'queued') AS pending_depth,
                 COALESCE(EXTRACT(EPOCH FROM (
                     now() - min(requested_at) FILTER (WHERE status = 'queued')
                 )) / 60, 0) AS oldest_pending_minutes
            FROM operations.operator_job_runs
           WHERE tenant_id = p_tenant_id
      ) metrics
     WHERE registry.queue_key = 'operator.jobs' AND registry.enabled;

    RETURN QUERY
    SELECT 'repeated_failure', jsonb_build_object(
        'job_key', run.job_key, 'failed_runs_24h', count(*),
        'max_failure_count', registry.max_failure_count,
        'job_run_id', (array_agg(run.id ORDER BY run.completed_at DESC))[1],
        'latest_failure_at', max(run.completed_at), 'window_hours', 24
    )
      FROM operations.operator_job_runs run
      JOIN operations.queue_registry registry ON registry.queue_key = 'operator.jobs'
     WHERE run.tenant_id = p_tenant_id
       AND run.status IN ('failed', 'stalled')
       AND run.completed_at >= now() - interval '24 hours'
     GROUP BY run.job_key, registry.max_failure_count
    HAVING count(*) > registry.max_failure_count;

    RETURN QUERY
    SELECT 'timeout', jsonb_build_object(
        'job_run_id', run.id, 'job_key', run.job_key,
        'completed_at', run.completed_at, 'terminal_reason', run.terminal_reason
    )
      FROM operations.operator_job_runs run
     WHERE run.tenant_id = p_tenant_id AND run.terminal_reason = 'timeout'
       AND run.completed_at >= now() - interval '24 hours';

    RETURN QUERY
    SELECT 'unmet_dependency', jsonb_build_object(
        'dependency_id', dependency.id, 'state', dependency.state,
        'reason', dependency.reason, 'created_at', dependency.created_at,
        'dependent_job_run_id', dependent.id, 'job_key', dependent.job_key,
        'prerequisite_job_run_id', prerequisite.id,
        'prerequisite_job_key', prerequisite.job_key,
        'max_pending_age_m', registry.max_pending_age_m
    )
      FROM operations.job_dependencies dependency
      JOIN operations.operator_job_runs dependent
        ON dependent.tenant_id = dependency.tenant_id AND dependent.id = dependency.dependent_run_id
      JOIN operations.operator_job_runs prerequisite
        ON prerequisite.tenant_id = dependency.tenant_id AND prerequisite.id = dependency.prerequisite_run_id
      JOIN operations.queue_registry registry ON registry.queue_key = 'operator.jobs'
     WHERE dependency.tenant_id = p_tenant_id
       AND (
           dependency.state = 'blocked'
           OR (dependency.state = 'waiting' AND registry.max_pending_age_m > 0
               AND dependency.created_at < now() - make_interval(mins => registry.max_pending_age_m))
       );

    RETURN QUERY
    SELECT 'control_snapshot', jsonb_build_object(
        'definition_versions', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'definition_key', definition_key, 'definition_digest', definition_digest
            )) FROM operations.job_definition_versions
        ), '[]'::jsonb),
        'schedules', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'definition_key', definition_key, 'definition_digest', definition_digest
            )) FROM operations.job_schedules WHERE tenant_id = p_tenant_id
        ), '[]'::jsonb),
        'lane_limits', COALESCE((
            SELECT jsonb_agg(jsonb_build_object('lane', lane, 'capacity', capacity))
              FROM operations.job_lane_limits WHERE tenant_id = p_tenant_id
        ), '[]'::jsonb),
        'resource_limits', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'resource_template', resource_template, 'capacity', capacity
            )) FROM operations.job_resource_limits
        ), '[]'::jsonb),
        'runtimes', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'runtime_kind', runtime_kind, 'registry_digest', registry_digest,
                'stopped_at', stopped_at, 'fresh', heartbeat_at >= now() - interval '3 minutes'
            )) FROM operations.job_runtime_heartbeats WHERE tenant_id = p_tenant_id
        ), '[]'::jsonb)
    );
END
$function$;

ALTER FUNCTION operations.jobs_health_measurements_v1(BIGINT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_health_measurements_v1(BIGINT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_health_measurements_v1(BIGINT) TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0228_jobs_health_finding_policy"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
