"""Make configured source bindings the durable unit of collection."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
/* A binding already identifies one configured source and collector.  Its
 * existing schedule is now authoritative and uses the simple persisted form
 * ``interval:<minutes>``.  These defaults reproduce the established cadence
 * without retaining capability-bucket scheduler jobs. */
UPDATE operations.source_bindings binding
   SET schedule = CASE source.name
       WHEN 'Ninja' THEN 'interval:60'
       WHEN 'Hudu' THEN 'interval:240'
       ELSE 'interval:240'
   END
  FROM operations.source_instances instance
  JOIN operations.sources source ON source.id = instance.source_id
 WHERE binding.source_instance_id = instance.id
   AND binding.enabled AND COALESCE(binding.schedule, '') = '';

UPDATE operations.job_schedules
   SET enabled = FALSE,
       capability_reason = 'Replaced by the configured source schedule.',
       next_due_at = NULL
 WHERE tenant_id = 1
   AND definition_key IN ('patches', 'agent-observations', 'documentation-observations');

ALTER TABLE operations.job_resource_limits
    DROP CONSTRAINT IF EXISTS job_resource_limits_resource_template_check;
ALTER TABLE operations.job_resource_limits
    ADD CONSTRAINT job_resource_limits_resource_template_check CHECK (
        resource_template IN (
            'execution:deployment', 'execution:emergency-child',
            'capacity:external-io', 'capacity:processing', 'capacity:control',
            'tenant:{tenant_id}:state', 'global:intel-cve-corpus',
            'global:software-catalog', 'tenant:{tenant_id}:software-inventory',
            'tenant:{tenant_id}:software-findings', 'tenant:{tenant_id}:notification-delivery',
            'tenant:{tenant_id}:legacy-agent-compliance', 'tenant:{tenant_id}:ninja-source',
            'tenant:{tenant_id}:agent-sources', 'tenant:{tenant_id}:documentation-source',
            'tenant:{tenant_id}:source-binding:{scope_identity}',
            'tenant:{tenant_id}:software-state', 'tenant:{tenant_id}:patch-state',
            'tenant:{tenant_id}:platform-findings', 'tenant:{tenant_id}:cmdb-findings',
            'tenant:{tenant_id}:identity-state', 'tenant:{tenant_id}:parity-state',
            'tenant:{tenant_id}:software-cve-match', 'tenant:{tenant_id}:threat-intelligence',
            'tenant:{tenant_id}:history-retention', 'tenant:{tenant_id}:source-actions',
            'tenant:{tenant_id}:source-demand', 'tenant:{tenant_id}:run-history',
            'tenant:{tenant_id}:platform-health', 'tenant:{tenant_id}:reporting'
        )
    );
INSERT INTO operations.job_resource_limits
    (resource_template, capacity, policy_revision, policy_kind)
VALUES ('tenant:{tenant_id}:source-binding:{scope_identity}', 1,
        'd621955059270b5d5faf9eb7a3c829f7f3142d8f6acb998c95ff41dd736c0e4b', 'domain_lock')
ON CONFLICT (resource_template) DO UPDATE SET
    capacity = EXCLUDED.capacity, policy_revision = EXCLUDED.policy_revision,
    policy_kind = EXCLUDED.policy_kind;

CREATE TABLE IF NOT EXISTS operations.source_refresh_outputs (
    tenant_id BIGINT NOT NULL,
    run_id UUID NOT NULL PRIMARY KEY REFERENCES operations.operator_job_runs(id)
        ON DELETE RESTRICT,
    source_binding_id UUID NOT NULL REFERENCES operations.source_bindings(id)
        ON DELETE RESTRICT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rows_touched INTEGER NULL CHECK (rows_touched IS NULL OR rows_touched >= 0),
    UNIQUE (tenant_id, run_id),
    FOREIGN KEY (tenant_id, source_binding_id)
        REFERENCES operations.source_bindings(tenant_id, id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_source_refresh_outputs_binding_published
    ON operations.source_refresh_outputs (tenant_id, source_binding_id, published_at DESC);
ALTER TABLE operations.source_refresh_outputs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS source_refresh_outputs_tenant_policy ON operations.source_refresh_outputs;
CREATE POLICY source_refresh_outputs_tenant_policy ON operations.source_refresh_outputs
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::BIGINT)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::BIGINT);
REVOKE ALL ON operations.source_refresh_outputs FROM PUBLIC, operations_app,
    ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.source_refresh_outputs TO operations_app, operations_readonly;

/* Different source scopes may now be queued or execute at the same time.
 * Coalescing remains exact to definition plus scope. */
DROP INDEX IF EXISTS operations.jobs_one_queued_successor;
DROP INDEX IF EXISTS operations.jobs_one_executing_run;
CREATE UNIQUE INDEX jobs_one_queued_successor
    ON operations.operator_job_runs (tenant_id, job_key, scope_identity)
    WHERE status = 'queued';
CREATE UNIQUE INDEX jobs_one_executing_run
    ON operations.operator_job_runs (tenant_id, job_key, scope_identity)
    WHERE status = 'running' AND wait_category IS DISTINCT FROM 'workflow';

CREATE OR REPLACE FUNCTION operations.jobs_request(
    p_tenant_id BIGINT, p_definition_key TEXT, p_definition_digest TEXT,
    p_scope_identity TEXT, p_request_identity TEXT, p_trigger_kind TEXT,
    p_actor_id INTEGER DEFAULT NULL, p_payload JSONB DEFAULT '{}'::jsonb,
    p_input_revisions JSONB DEFAULT '{}'::jsonb,
    p_correlation_id UUID DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT; v_run_id UUID; v_existing_digest TEXT;
    v_existing_scope TEXT; v_existing_version SMALLINT; v_lane TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::BIGINT;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_scope_identity IS NULL OR length(p_scope_identity) NOT BETWEEN 1 AND 256
       OR p_request_identity IS NULL OR p_request_identity !~ '^[0-9a-f]{64}$'
       OR p_trigger_kind NOT IN ('automatic', 'operator', 'dependency', 'recovery')
       OR p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object'
       OR p_input_revisions IS NULL OR jsonb_typeof(p_input_revisions) <> 'object'
       OR octet_length(p_payload::text) > 65536 OR octet_length(p_input_revisions::text) > 65536
       OR (p_trigger_kind = 'operator' AND p_actor_id IS NULL)
    THEN RAISE EXCEPTION 'Jobs request is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS key(key)
               WHERE key ~* '(token|secret|password|authorization|credential)')
    THEN RAISE EXCEPTION 'Jobs request payload contains a reserved key'; END IF;
    IF NOT EXISTS (SELECT 1 FROM operations.job_definition_versions
                   WHERE definition_key = p_definition_key AND definition_digest = p_definition_digest)
    THEN RAISE EXCEPTION 'Jobs definition snapshot is not registered'; END IF;
    IF p_actor_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM operations.users
        WHERE id = p_actor_id AND tenant_id = p_tenant_id)
    THEN RAISE EXCEPTION 'Jobs request actor is outside the tenant'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'operations.jobs.request:' || p_tenant_id || ':' || p_definition_key || ':' || p_scope_identity, 0));
    SELECT run_id INTO v_run_id FROM operations.job_requests
     WHERE tenant_id = p_tenant_id AND definition_key = p_definition_key
       AND definition_digest = p_definition_digest AND scope_identity = p_scope_identity
       AND request_identity = p_request_identity;
    IF v_run_id IS NOT NULL THEN RETURN v_run_id; END IF;
    SELECT metadata->>'lane' INTO v_lane FROM operations.job_definition_versions
     WHERE definition_key = p_definition_key AND definition_digest = p_definition_digest;
    INSERT INTO operations.operator_job_runs (
        id, tenant_id, job_key, lane, requested_by_id, contract_version, definition_digest,
        trigger_kind, scope_identity, request_payload, coalescing_key, correlation_id, input_revisions
    ) VALUES (gen_random_uuid(), p_tenant_id, p_definition_key, v_lane, p_actor_id, 1,
        p_definition_digest, p_trigger_kind, p_scope_identity, p_payload,
        p_definition_key || ':' || p_scope_identity, p_correlation_id, p_input_revisions)
    ON CONFLICT (tenant_id, job_key, scope_identity) WHERE status = 'queued'
    DO NOTHING RETURNING id INTO v_run_id;
    IF v_run_id IS NULL THEN
        SELECT id, definition_digest, scope_identity, contract_version
          INTO v_run_id, v_existing_digest, v_existing_scope, v_existing_version
          FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id AND job_key = p_definition_key
           AND scope_identity = p_scope_identity AND status = 'queued'
         ORDER BY requested_at DESC, id DESC FOR UPDATE LIMIT 1;
        IF v_existing_version <> 1 OR v_existing_digest IS DISTINCT FROM p_definition_digest
           OR v_existing_scope IS DISTINCT FROM p_scope_identity
        THEN RAISE EXCEPTION 'Conflicting queued Job is unavailable'; END IF;
    END IF;
    INSERT INTO operations.job_requests (
        tenant_id, definition_key, definition_digest, scope_identity, request_identity,
        run_id, actor_id, trigger_kind, requested_input_revisions
    ) VALUES (p_tenant_id, p_definition_key, p_definition_digest, p_scope_identity,
        p_request_identity, v_run_id, p_actor_id, p_trigger_kind, p_input_revisions);
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, v_run_id, 'requested', 'Queued', 'Admitted through the Jobs request API.');
    RETURN v_run_id;
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_source_refresh_context_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_claim_token UUID
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_scope TEXT; v_binding UUID;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::BIGINT;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL THEN
        RAISE EXCEPTION 'Source refresh context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    SELECT scope_identity INTO v_scope FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant_id AND id = p_run_id AND job_key = 'source-refresh'
       AND status = 'running' AND claim_token = p_claim_token;
    IF v_scope !~ '^source-binding:[0-9a-fA-F-]{36}$' THEN
        RAISE EXCEPTION 'Source refresh scope is invalid';
    END IF;
    v_binding := substring(v_scope FROM 16)::UUID;
    IF NOT EXISTS (
        SELECT 1 FROM operations.source_bindings
         WHERE tenant_id = p_tenant_id AND id = v_binding AND enabled
    ) THEN RAISE EXCEPTION 'Configured source binding is unavailable'; END IF;
    RETURN v_binding;
END
$function$;

/* A completion marker is inserted only inside the fenced terminal transition.
 * Failed/incomplete source collection therefore cannot wake downstream work. */
CREATE OR REPLACE FUNCTION operations.jobs_finish_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_claim_token UUID, p_status TEXT,
    p_rows_touched INTEGER DEFAULT NULL, p_error TEXT DEFAULT '',
    p_result JSONB DEFAULT '{}'::jsonb
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT; v_stage TEXT; v_detail TEXT;
    v_published_revisions JSONB := '{}'::jsonb; v_job_key TEXT; v_scope TEXT;
    v_binding UUID;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::BIGINT;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL
       OR p_status NOT IN ('completed', 'failed')
       OR p_rows_touched IS NOT NULL AND p_rows_touched < 0
       OR p_error IS NULL OR length(p_error) > 2000
       OR p_result IS NULL OR jsonb_typeof(p_result) <> 'object'
       OR octet_length(p_result::text) > 65536
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_result) AS key(key)
                   WHERE key ~* '(token|secret|password|authorization|credential)')
    THEN RAISE EXCEPTION 'Jobs finish context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    SELECT job_key, scope_identity INTO v_job_key, v_scope
      FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant_id AND id = p_run_id AND contract_version = 1
       AND status = 'running' AND claim_token = p_claim_token FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs finish is unavailable or fenced'; END IF;
    IF p_status = 'completed' THEN
        SELECT COALESCE(jsonb_object_agg(revision_name, required_output_revision), '{}'::jsonb)
          INTO v_published_revisions
          FROM (
              SELECT DISTINCT dependency.required_input_revisions->>'revision_name' AS revision_name,
                     dependency.required_output_revision
                FROM operations.job_dependencies dependency
               WHERE dependency.tenant_id = p_tenant_id
                 AND dependency.prerequisite_run_id = p_run_id
                 AND dependency.required_input_revisions->>'dependency_kind' = 'workflow'
          ) revisions;
        IF v_job_key = 'source-refresh' THEN
            IF v_scope !~ '^source-binding:[0-9a-fA-F-]{36}$'
               OR p_result->'source_refresh'->>'binding_id' IS DISTINCT FROM substring(v_scope FROM 16)
            THEN RAISE EXCEPTION 'Source refresh completion is invalid'; END IF;
            v_binding := substring(v_scope FROM 16)::UUID;
            INSERT INTO operations.source_refresh_outputs
                (tenant_id, run_id, source_binding_id, rows_touched)
            VALUES (p_tenant_id, p_run_id, v_binding, p_rows_touched);
        END IF;
    END IF;
    v_stage := CASE WHEN p_status = 'completed' THEN 'Completed' ELSE 'Failed' END;
    v_detail := CASE WHEN p_status = 'completed' THEN 'Finished.' ELSE 'Review the recorded error.' END;
    UPDATE operations.operator_job_runs
       SET status = p_status, stage = v_stage, stage_detail = v_detail,
           stage_updated_at = now(), heartbeat_at = now(), completed_at = now(),
           lease_expires_at = NULL, deadline_at = NULL, rows_touched = p_rows_touched,
           error = p_error, result = p_result,
           output_revisions = COALESCE(output_revisions, '{}'::jsonb) || v_published_revisions,
           wait_category = NULL, wait_reason = NULL, terminal_reason = p_status
     WHERE tenant_id = p_tenant_id AND id = p_run_id;
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = p_status
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
       AND claim_token = p_claim_token AND state = 'held';
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, p_run_id, p_status, v_stage, v_detail);
    PERFORM operations.jobs_propagate_dependency_terminal_v1(p_tenant_id, p_run_id, p_status);
END
$function$;

ALTER FUNCTION operations.jobs_source_refresh_context_v1(BIGINT, UUID, UUID)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_source_refresh_context_v1(BIGINT, UUID, UUID)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_source_refresh_context_v1(BIGINT, UUID, UUID)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0262_jobs_software_writer_capacity")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
