"""Maintenance cadence in the database, and retired schedules stop reporting failures.

Measured 2026-10-19:

* The resolver's hourly maintenance (roaming records, 0318; shadow naming,
  0322) was throttled in process memory. Every Jobs run is a new child
  process, so both ran on every resolver run (about 30 a day).
  ``operations.maintenance_cadence`` holds, per tenant and component, when the
  work last started and completed; ``claim_maintenance`` takes the slot
  atomically, so at most one run per interval does the work.
* 0244 retired the resolver, platform-evaluate, software-classify-only and
  intel-matcher schedules (and software-classify-full) with outcome
  ``retired``, but the terminal-outcome trigger of 0227 kept writing the
  outcome of their last run onto them (``stalled``, ``cancelled``,
  ``completed``), and ``schedule_failure`` health (0259) reported disabled
  schedules. The trigger now writes only to enabled schedules, the retired
  schedules are repaired, and health measures enabled schedules only for
  failures and leaves retired schedules out of ``required_disabled`` (a
  genuinely required schedule that is switched off is still reported).
  ``last_outcome`` is run bookkeeping outside the recorded columns of
  ``job_schedules`` (0306), so the repair leaves no change history.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.maintenance_cadence (
    tenant_id bigint NOT NULL,
    component varchar(64) NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz NULL,
    last_seconds numeric(10, 3) NULL,
    PRIMARY KEY (tenant_id, component)
);
ALTER TABLE operations.maintenance_cadence ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.maintenance_cadence FOR SELECT
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.maintenance_cadence FROM PUBLIC;
GRANT SELECT ON operations.maintenance_cadence TO operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES (
    'maintenance_cadence', 'exempt', 'maintenance run bookkeeping',
    '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL
) ON CONFLICT (table_name) DO NOTHING;

-- Both functions bypass row security, so they act only for the tenant the
-- session is set to (operations.tenant_id) and refuse anything else.
CREATE FUNCTION operations.maintenance_context_valid(p_tenant bigint, p_component text)
RETURNS boolean
LANGUAGE sql STABLE
SET search_path = pg_catalog, operations
AS $fn$
    -- coalesce: an unset tenant must fail the check, not yield NULL.
    SELECT coalesce(
               p_tenant = nullif(current_setting('operations.tenant_id', true), '')::bigint
               AND coalesce(p_component, '') <> ''
               AND length(p_component) <= 64,
               false)
$fn$;

-- Takes the component's slot when it is free (never run, or started longer
-- than p_interval ago). The row lock makes concurrent claims exclusive. A
-- claim that rolls back with its transaction frees the slot again.
CREATE FUNCTION operations.claim_maintenance(p_tenant bigint, p_component text, p_interval interval)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_claimed boolean;
BEGIN
    IF NOT operations.maintenance_context_valid(p_tenant, p_component)
       OR p_interval IS NULL OR p_interval <= interval '0' THEN
        RAISE EXCEPTION 'claim_maintenance needs the session tenant, a component of 1 to 64 characters and a positive interval';
    END IF;
    INSERT INTO operations.maintenance_cadence AS c (tenant_id, component, started_at)
    VALUES (p_tenant, p_component, now())
    ON CONFLICT (tenant_id, component) DO UPDATE
       SET started_at = now(), completed_at = NULL
     WHERE c.started_at < now() - p_interval
    RETURNING true INTO v_claimed;
    RETURN coalesce(v_claimed, false);
END
$fn$;

CREATE FUNCTION operations.complete_maintenance(p_tenant bigint, p_component text, p_seconds numeric)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF NOT operations.maintenance_context_valid(p_tenant, p_component) THEN
        RAISE EXCEPTION 'complete_maintenance needs the session tenant and a component of 1 to 64 characters';
    END IF;
    UPDATE operations.maintenance_cadence
       SET completed_at = now(), last_seconds = round(p_seconds, 3)
     WHERE tenant_id = p_tenant AND component = p_component;
END
$fn$;

REVOKE ALL ON FUNCTION operations.maintenance_context_valid(bigint, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.claim_maintenance(bigint, text, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.complete_maintenance(bigint, text, numeric) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.claim_maintenance(bigint, text, interval),
                          operations.complete_maintenance(bigint, text, numeric) TO ninja_ingest;

-- A disabled schedule keeps its outcome (0244 set it to retired).
CREATE OR REPLACE FUNCTION operations.jobs_record_schedule_terminal_outcome_v1()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
BEGIN
    IF NEW.tenant_id <> 1
       OR NEW.status NOT IN ('completed', 'failed', 'stalled', 'cancelled')
       OR OLD.status IS NOT DISTINCT FROM NEW.status
    THEN
        RETURN NEW;
    END IF;

    UPDATE operations.job_schedules AS schedule
       SET last_outcome = NEW.status
     WHERE schedule.tenant_id = NEW.tenant_id
       AND schedule.last_run_id = NEW.id
       AND schedule.enabled;
    RETURN NEW;
END
$function$;

UPDATE operations.job_schedules
   SET last_outcome = 'retired'
 WHERE tenant_id = 1
   AND NOT enabled
   AND capability_reason = 'Managed by its operation entry point.'
   AND last_outcome IS DISTINCT FROM 'retired';

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
     WHERE schedule.tenant_id = p_tenant_id AND schedule.enabled
       AND schedule.last_outcome IN ('failed', 'stalled', 'cancelled');

    RETURN QUERY SELECT 'required_disabled', jsonb_build_object(
        'schedule_id', schedule.id, 'job_key', schedule.definition_key,
        'capability_reason', schedule.capability_reason, 'configuration_revision', schedule.configuration_revision
    ) FROM operations.job_schedules schedule
      JOIN operations.job_definition_versions definition_version
        ON definition_version.definition_key = schedule.definition_key
       AND definition_version.definition_digest = schedule.definition_digest
     WHERE schedule.tenant_id = p_tenant_id AND NOT schedule.enabled
       AND schedule.last_outcome IS DISTINCT FROM 'retired'
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
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0322_record_names_and_shadow_naming"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
