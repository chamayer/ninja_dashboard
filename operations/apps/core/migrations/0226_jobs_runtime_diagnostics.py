"""Add durable Jobs runtime health and a read-only administrator projection."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE TABLE operations.job_runtime_heartbeats (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    runtime_kind TEXT NOT NULL CHECK (runtime_kind IN ('scheduler', 'worker')),
    runtime_identity UUID NOT NULL,
    registry_digest TEXT NOT NULL CHECK (registry_digest ~ '^[0-9a-f]{64}$'),
    metadata JSONB NOT NULL CHECK (
        jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 4096
    ),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    stopped_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, runtime_kind, runtime_identity)
);
CREATE INDEX jobs_runtime_heartbeats_current
    ON operations.job_runtime_heartbeats (tenant_id, runtime_kind, heartbeat_at DESC);
ALTER TABLE operations.job_runtime_heartbeats OWNER TO operations_migrate;
REVOKE ALL ON operations.job_runtime_heartbeats
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER TABLE operations.job_runtime_heartbeats ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.job_runtime_heartbeats FORCE ROW LEVEL SECURITY;
CREATE POLICY jobs_runtime_heartbeat_tenant_isolation
    ON operations.job_runtime_heartbeats
    USING (
        current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint
    )
    WITH CHECK (
        current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint
    );

CREATE FUNCTION operations.jobs_runtime_heartbeat_v1(
    p_tenant_id BIGINT, p_runtime_kind TEXT, p_runtime_identity UUID,
    p_registry_digest TEXT, p_metadata JSONB
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_runtime_kind IS NULL OR p_runtime_kind NOT IN ('scheduler', 'worker')
       OR p_runtime_identity IS NULL
       OR p_registry_digest IS NULL OR p_registry_digest !~ '^[0-9a-f]{64}$'
       OR p_metadata IS NULL OR jsonb_typeof(p_metadata) <> 'object'
       OR octet_length(p_metadata::text) > 4096
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_metadata) AS metadata_key(key)
            WHERE key ~* '(token|secret|password|authorization|credential)'
       )
    THEN RAISE EXCEPTION 'Jobs runtime heartbeat context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    INSERT INTO operations.job_runtime_heartbeats (
        tenant_id, runtime_kind, runtime_identity, registry_digest, metadata
    ) VALUES (
        p_tenant_id, p_runtime_kind, p_runtime_identity, p_registry_digest, p_metadata
    )
    ON CONFLICT (tenant_id, runtime_kind, runtime_identity) DO UPDATE SET
        registry_digest = EXCLUDED.registry_digest,
        metadata = EXCLUDED.metadata,
        heartbeat_at = now(),
        stopped_at = NULL;
END
$function$;

CREATE FUNCTION operations.jobs_runtime_stop_v1(
    p_tenant_id BIGINT, p_runtime_kind TEXT, p_runtime_identity UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_runtime_kind IS NULL OR p_runtime_kind NOT IN ('scheduler', 'worker')
       OR p_runtime_identity IS NULL
    THEN RAISE EXCEPTION 'Jobs runtime stop context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.job_runtime_heartbeats
       SET stopped_at = now(), heartbeat_at = now()
     WHERE tenant_id = p_tenant_id AND runtime_kind = p_runtime_kind
       AND runtime_identity = p_runtime_identity AND stopped_at IS NULL;
END
$function$;

CREATE FUNCTION operations.jobs_admin_diagnostics_v1(
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
        SELECT 1::bigint, jsonb_build_object(
            'queued_runs', (SELECT count(*) FROM operations.operator_job_runs
                             WHERE tenant_id = p_tenant_id AND status = 'queued'),
            'running_runs', (SELECT count(*) FROM operations.operator_job_runs
                              WHERE tenant_id = p_tenant_id AND status = 'running'),
            'stalled_runs', (SELECT count(*) FROM operations.operator_job_runs
                              WHERE tenant_id = p_tenant_id AND status = 'stalled'),
            'held_claims', (SELECT count(*) FROM operations.job_resource_claims
                             WHERE tenant_id = p_tenant_id AND state = 'held'),
            'contained_claims', (SELECT count(*) FROM operations.job_resource_claims
                                  WHERE tenant_id = p_tenant_id AND state = 'contained'),
            'waiting_dependencies', (SELECT count(*) FROM operations.job_dependencies
                                      WHERE tenant_id = p_tenant_id AND state = 'waiting'),
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

ALTER FUNCTION operations.jobs_runtime_heartbeat_v1(BIGINT, TEXT, UUID, TEXT, JSONB)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_runtime_stop_v1(BIGINT, TEXT, UUID)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_admin_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION
    operations.jobs_runtime_heartbeat_v1(BIGINT, TEXT, UUID, TEXT, JSONB),
    operations.jobs_runtime_stop_v1(BIGINT, TEXT, UUID),
    operations.jobs_admin_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_runtime_heartbeat_v1(BIGINT, TEXT, UUID, TEXT, JSONB),
    operations.jobs_runtime_stop_v1(BIGINT, TEXT, UUID)
TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.jobs_admin_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0225_jobs_revision_dependencies"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
