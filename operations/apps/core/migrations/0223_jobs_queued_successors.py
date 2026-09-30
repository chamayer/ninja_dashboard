"""Allow one queued successor while the same Job definition is executing."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
DROP INDEX operations.uq_operator_job_runs_active;
CREATE UNIQUE INDEX jobs_one_queued_successor
    ON operations.operator_job_runs (tenant_id, job_key)
    WHERE status = 'queued';
CREATE UNIQUE INDEX jobs_one_executing_run
    ON operations.operator_job_runs (tenant_id, job_key)
    WHERE status = 'running' AND wait_category IS DISTINCT FROM 'workflow';

CREATE OR REPLACE FUNCTION operations.jobs_request(
    p_tenant_id BIGINT, p_definition_key TEXT, p_definition_digest TEXT,
    p_scope_identity TEXT, p_request_identity TEXT, p_trigger_kind TEXT,
    p_actor_id INTEGER DEFAULT NULL, p_payload JSONB DEFAULT '{}'::jsonb,
    p_input_revisions JSONB DEFAULT '{}'::jsonb,
    p_correlation_id UUID DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT; v_run_id UUID; v_existing_definition_digest TEXT;
    v_existing_scope TEXT; v_existing_version SMALLINT; v_lane TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
    THEN RAISE EXCEPTION 'Jobs request tenant context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF p_scope_identity IS NULL OR length(p_scope_identity) NOT BETWEEN 1 AND 256
       OR p_request_identity IS NULL OR p_request_identity !~ '^[0-9a-f]{64}$'
       OR p_trigger_kind IS NULL
       OR p_trigger_kind NOT IN ('automatic', 'operator', 'dependency', 'recovery')
       OR p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object'
       OR p_input_revisions IS NULL OR jsonb_typeof(p_input_revisions) <> 'object'
       OR octet_length(p_payload::text) > 65536
       OR octet_length(p_input_revisions::text) > 65536
       OR (p_trigger_kind = 'operator' AND p_actor_id IS NULL)
    THEN RAISE EXCEPTION 'Jobs request is invalid'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_payload) AS payload_key(key)
         WHERE key ~* '(token|secret|password|authorization|credential)'
    ) THEN RAISE EXCEPTION 'Jobs request payload contains a reserved key'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM operations.job_definition_versions
         WHERE definition_key = p_definition_key
           AND definition_digest = p_definition_digest
    ) THEN RAISE EXCEPTION 'Jobs definition snapshot is not registered'; END IF;
    IF p_actor_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM operations.users
         WHERE id = p_actor_id AND tenant_id = p_tenant_id
    ) THEN RAISE EXCEPTION 'Jobs request actor is outside the tenant'; END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'operations.jobs.request:' || p_tenant_id || ':'
        || p_definition_key || ':' || p_scope_identity, 0
    ));
    SELECT run_id INTO v_run_id
      FROM operations.job_requests
     WHERE tenant_id = p_tenant_id AND definition_key = p_definition_key
       AND definition_digest = p_definition_digest
       AND scope_identity = p_scope_identity AND request_identity = p_request_identity;
    IF v_run_id IS NOT NULL THEN RETURN v_run_id; END IF;

    SELECT metadata->>'lane' INTO v_lane
      FROM operations.job_definition_versions
     WHERE definition_key = p_definition_key AND definition_digest = p_definition_digest;
    INSERT INTO operations.operator_job_runs (
        id, tenant_id, job_key, lane, requested_by_id, contract_version,
        definition_digest, trigger_kind, scope_identity, request_payload,
        coalescing_key, correlation_id, input_revisions
    ) VALUES (
        gen_random_uuid(), p_tenant_id, p_definition_key, v_lane, p_actor_id, 1,
        p_definition_digest, p_trigger_kind, p_scope_identity, p_payload,
        p_definition_key || ':' || p_scope_identity, p_correlation_id, p_input_revisions
    )
    ON CONFLICT (tenant_id, job_key) WHERE status = 'queued'
    DO NOTHING RETURNING id INTO v_run_id;

    IF v_run_id IS NULL THEN
        SELECT id, definition_digest, scope_identity, contract_version
          INTO v_run_id, v_existing_definition_digest, v_existing_scope, v_existing_version
          FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id AND job_key = p_definition_key
           AND status = 'queued'
         ORDER BY requested_at DESC, id DESC FOR UPDATE LIMIT 1;
        IF v_existing_version <> 1
           OR v_existing_definition_digest IS DISTINCT FROM p_definition_digest
           OR v_existing_scope IS DISTINCT FROM p_scope_identity
        THEN RAISE EXCEPTION 'Conflicting differently scoped queued Job must drain first'; END IF;
    END IF;
    INSERT INTO operations.job_requests (
        tenant_id, definition_key, definition_digest, scope_identity,
        request_identity, run_id, actor_id, trigger_kind, requested_input_revisions
    ) VALUES (
        p_tenant_id, p_definition_key, p_definition_digest, p_scope_identity,
        p_request_identity, v_run_id, p_actor_id, p_trigger_kind, p_input_revisions
    );
    INSERT INTO operations.operator_job_events (
        tenant_id, job_id, event_type, stage, detail
    ) VALUES (
        p_tenant_id, v_run_id, 'requested', 'Queued',
        'Admitted through the Jobs request API.'
    );
    RETURN v_run_id;
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_request_software_v1(
    p_tenant_id BIGINT, p_definition_key TEXT, p_definition_digest TEXT,
    p_scope_identity TEXT, p_request_identity TEXT, p_trigger_kind TEXT,
    p_actor_id INTEGER DEFAULT NULL, p_payload JSONB DEFAULT '{}'::jsonb,
    p_input_revisions JSONB DEFAULT '{}'::jsonb,
    p_correlation_id UUID DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT; v_metadata JSONB; v_rank INTEGER;
    v_existing_run UUID; v_active_run UUID; v_superseded_runs UUID[];
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_scope_identity IS NULL OR length(p_scope_identity) NOT BETWEEN 1 AND 256
       OR p_request_identity IS NULL OR p_request_identity !~ '^[0-9a-f]{64}$'
       OR p_trigger_kind IS NULL
       OR p_trigger_kind NOT IN ('automatic', 'operator', 'dependency', 'recovery')
       OR p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object'
       OR p_input_revisions IS NULL OR jsonb_typeof(p_input_revisions) <> 'object'
       OR octet_length(p_payload::text) > 65536
       OR octet_length(p_input_revisions::text) > 65536
       OR (p_trigger_kind = 'operator' AND p_actor_id IS NULL)
    THEN RAISE EXCEPTION 'Jobs Software request is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_payload) AS payload_key(key)
         WHERE key ~* '(token|secret|password|authorization|credential)'
    ) THEN RAISE EXCEPTION 'Jobs Software request payload contains a reserved key'; END IF;
    IF p_actor_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM operations.users WHERE id = p_actor_id AND tenant_id = p_tenant_id
    ) THEN RAISE EXCEPTION 'Jobs Software request actor is outside the tenant'; END IF;
    SELECT metadata INTO v_metadata FROM operations.job_definition_versions
     WHERE definition_key = p_definition_key AND definition_digest = p_definition_digest;
    IF v_metadata IS NULL
       OR v_metadata->>'supersession_family' <> 'software-classifier'
       OR v_metadata->>'supersession_rank' !~ '^[1-9][0-9]*$'
    THEN RAISE EXCEPTION 'Jobs Software definition snapshot is invalid'; END IF;
    v_rank := (v_metadata->>'supersession_rank')::integer;
    IF v_rank NOT BETWEEN 1 AND 3
    THEN RAISE EXCEPTION 'Jobs Software definition rank is invalid'; END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.jobs.software-classifier:' || p_tenant_id, 0)
    );

    SELECT run_id INTO v_existing_run FROM operations.job_requests
     WHERE tenant_id = p_tenant_id AND definition_key = p_definition_key
       AND definition_digest = p_definition_digest AND scope_identity = p_scope_identity
       AND request_identity = p_request_identity;
    IF v_existing_run IS NOT NULL THEN RETURN v_existing_run; END IF;

    SELECT job.id INTO v_active_run
      FROM operations.operator_job_runs job
      JOIN operations.job_definition_versions definition_version
        ON definition_version.definition_key = job.job_key
       AND definition_version.definition_digest = job.definition_digest
     WHERE job.tenant_id = p_tenant_id AND job.contract_version = 1
       AND job.status = 'queued'
       AND definition_version.metadata->>'supersession_family' = 'software-classifier'
       AND CASE
             WHEN definition_version.metadata->>'supersession_rank' ~ '^[1-9][0-9]*$'
             THEN (definition_version.metadata->>'supersession_rank')::integer ELSE 0
           END >= v_rank
     ORDER BY job.requested_at, job.id FOR UPDATE LIMIT 1;
    IF v_active_run IS NOT NULL THEN
        INSERT INTO operations.job_requests (
            tenant_id, definition_key, definition_digest, scope_identity,
            request_identity, run_id, actor_id, trigger_kind, requested_input_revisions
        ) VALUES (
            p_tenant_id, p_definition_key, p_definition_digest, p_scope_identity,
            p_request_identity, v_active_run, p_actor_id, p_trigger_kind, p_input_revisions
        );
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (
            p_tenant_id, v_active_run, 'coalesced', 'Queued',
            'A broader queued Software request already covers this request.'
        );
        RETURN v_active_run;
    END IF;

    WITH superseded AS (
        UPDATE operations.operator_job_runs job
           SET status = 'cancelled', stage = 'Superseded',
               stage_detail = 'Superseded by a broader Software classifier run.',
               stage_updated_at = now(), completed_at = now(),
               terminal_reason = 'superseded-before-claim',
               error = 'Superseded before work started.'
          FROM operations.job_definition_versions definition_version
         WHERE job.tenant_id = p_tenant_id AND job.contract_version = 1
           AND job.status = 'queued' AND job.job_key = definition_version.definition_key
           AND job.definition_digest = definition_version.definition_digest
           AND definition_version.metadata->>'supersession_family' = 'software-classifier'
           AND CASE
                 WHEN definition_version.metadata->>'supersession_rank' ~ '^[1-9][0-9]*$'
                 THEN (definition_version.metadata->>'supersession_rank')::integer ELSE 0
               END < v_rank
         RETURNING job.id
    )
    SELECT array_agg(id) INTO v_superseded_runs FROM superseded;

    v_active_run := operations.jobs_request(
        p_tenant_id, p_definition_key, p_definition_digest, p_scope_identity,
        p_request_identity, p_trigger_kind, p_actor_id, p_payload,
        p_input_revisions, p_correlation_id
    );
    IF v_superseded_runs IS NOT NULL THEN
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        SELECT p_tenant_id, id, 'superseded', 'Superseded',
               'Superseded by a broader Software classifier request.'
          FROM unnest(v_superseded_runs) AS id;
        DELETE FROM operations.job_dependencies old_edge
         WHERE old_edge.tenant_id = p_tenant_id
           AND old_edge.dependent_run_id = ANY(v_superseded_runs)
           AND EXISTS (
               SELECT 1 FROM operations.job_dependencies new_edge
                WHERE new_edge.tenant_id = old_edge.tenant_id
                  AND new_edge.dependent_run_id = v_active_run
                  AND new_edge.prerequisite_run_id = old_edge.prerequisite_run_id
           );
        UPDATE operations.job_dependencies
           SET dependent_run_id = v_active_run,
               reason = 'Waiting for the broader Software classifier successor.'
         WHERE tenant_id = p_tenant_id
           AND dependent_run_id = ANY(v_superseded_runs);
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (
            p_tenant_id, v_active_run, 'dependency_rewired', 'Queued',
            'Inherited workflow prerequisites from a superseded Software run.'
        );
    END IF;
    RETURN v_active_run;
END
$function$;

ALTER FUNCTION operations.jobs_request(
    BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB, JSONB, UUID
) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_request_software_v1(
    BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB, JSONB, UUID
) OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0222_jobs_workflow_root_completion"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
