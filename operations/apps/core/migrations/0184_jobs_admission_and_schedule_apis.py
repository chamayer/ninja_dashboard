"""Add constrained v1 Jobs admission and schedule coordination APIs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.operator_job_runs
    DROP CONSTRAINT jobs_contract_preparation_only,
    ADD CONSTRAINT jobs_contract_version_known CHECK (contract_version IN (0, 1));
ALTER TABLE operations.job_schedules
    DROP CONSTRAINT jobs_schedule_preparation_only;

CREATE FUNCTION operations.jobs_register_definition(
    p_definition_key TEXT,
    p_definition_digest TEXT,
    p_handler_version TEXT,
    p_metadata JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_existing JSONB;
BEGIN
    IF length(p_definition_key) NOT BETWEEN 1 AND 120
       OR p_definition_digest !~ '^[0-9a-f]{64}$'
       OR length(p_handler_version) NOT BETWEEN 1 AND 120
       OR jsonb_typeof(p_metadata) <> 'object'
       OR octet_length(p_metadata::text) > 65536
       OR p_metadata->>'key' IS DISTINCT FROM p_definition_key
       OR p_metadata->>'lane' NOT IN (
           'collection', 'evaluation', 'software', 'intelligence', 'service'
       )
    THEN
        RAISE EXCEPTION 'Invalid Jobs definition snapshot';
    END IF;

    INSERT INTO operations.job_definition_versions
        (definition_key, definition_digest, handler_version, metadata)
    VALUES (p_definition_key, p_definition_digest, p_handler_version, p_metadata)
    ON CONFLICT (definition_key, definition_digest) DO NOTHING;

    SELECT metadata INTO v_existing
      FROM operations.job_definition_versions
     WHERE definition_key = p_definition_key
       AND definition_digest = p_definition_digest;
    IF v_existing IS DISTINCT FROM p_metadata THEN
        RAISE EXCEPTION 'Definition digest conflicts with retained snapshot';
    END IF;
END
$function$;

CREATE FUNCTION operations.jobs_request(
    p_tenant_id BIGINT,
    p_definition_key TEXT,
    p_definition_digest TEXT,
    p_scope_identity TEXT,
    p_request_identity TEXT,
    p_trigger_kind TEXT,
    p_actor_id INTEGER DEFAULT NULL,
    p_payload JSONB DEFAULT '{}'::jsonb,
    p_input_revisions JSONB DEFAULT '{}'::jsonb,
    p_correlation_id UUID DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_run_id UUID;
    v_existing_definition_digest TEXT;
    v_existing_scope TEXT;
    v_existing_version SMALLINT;
    v_lane TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs request tenant context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF p_scope_identity IS NULL
       OR length(p_scope_identity) NOT BETWEEN 1 AND 256
       OR p_request_identity IS NULL
       OR p_request_identity !~ '^[0-9a-f]{64}$'
       OR p_trigger_kind IS NULL
       OR p_trigger_kind NOT IN ('automatic', 'operator', 'dependency', 'recovery')
       OR p_payload IS NULL
       OR jsonb_typeof(p_payload) <> 'object'
       OR p_input_revisions IS NULL
       OR jsonb_typeof(p_input_revisions) <> 'object'
       OR octet_length(p_payload::text) > 65536
       OR octet_length(p_input_revisions::text) > 65536
       OR (p_trigger_kind = 'operator' AND p_actor_id IS NULL)
    THEN
        RAISE EXCEPTION 'Jobs request is invalid';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_payload) AS payload_key(key)
        WHERE key ~* '(token|secret|password|authorization|credential)'
    ) THEN
        RAISE EXCEPTION 'Jobs request payload contains a reserved key';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM operations.job_definition_versions
        WHERE definition_key = p_definition_key AND definition_digest = p_definition_digest
    ) THEN
        RAISE EXCEPTION 'Jobs definition snapshot is not registered';
    END IF;
    IF p_actor_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM operations.users
        WHERE id = p_actor_id AND tenant_id = p_tenant_id
    ) THEN
        RAISE EXCEPTION 'Jobs request actor is outside the tenant';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'operations.jobs.request:' || p_tenant_id || ':'
            || p_definition_key || ':' || p_scope_identity,
            0
        )
    );

    SELECT run_id INTO v_run_id
      FROM operations.job_requests
     WHERE tenant_id = p_tenant_id
       AND definition_key = p_definition_key
       AND definition_digest = p_definition_digest
       AND scope_identity = p_scope_identity
       AND request_identity = p_request_identity;
    IF v_run_id IS NOT NULL THEN
        RETURN v_run_id;
    END IF;

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
    ON CONFLICT (tenant_id, job_key) WHERE status IN ('queued', 'running')
    DO NOTHING
    RETURNING id INTO v_run_id;

    IF v_run_id IS NULL THEN
        SELECT id, definition_digest, scope_identity, contract_version
          INTO v_run_id, v_existing_definition_digest, v_existing_scope, v_existing_version
          FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id
           AND job_key = p_definition_key
           AND status IN ('queued', 'running')
         ORDER BY requested_at DESC, id DESC
         FOR UPDATE
         LIMIT 1;
        IF v_existing_version <> 1
           OR v_existing_definition_digest IS DISTINCT FROM p_definition_digest
           OR v_existing_scope IS DISTINCT FROM p_scope_identity
        THEN
            RAISE EXCEPTION 'Conflicting legacy or differently scoped active Job must drain first';
        END IF;
    END IF;

    INSERT INTO operations.job_requests (
        tenant_id, definition_key, definition_digest, scope_identity, request_identity,
        run_id, actor_id, trigger_kind, requested_input_revisions
    ) VALUES (
        p_tenant_id, p_definition_key, p_definition_digest, p_scope_identity, p_request_identity,
        v_run_id, p_actor_id, p_trigger_kind, p_input_revisions
    );

    INSERT INTO operations.operator_job_events
        (tenant_id, job_id, event_type, stage, detail)
    VALUES (
        p_tenant_id, v_run_id, 'requested', 'Queued', 'Admitted through the Jobs request API.'
    );
    RETURN v_run_id;
END
$function$;

CREATE FUNCTION operations.jobs_try_schedule_leader()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT pg_try_advisory_lock(hashtextextended('operations.jobs.schedule_leader.v1', 0))
$function$;

CREATE FUNCTION operations.jobs_release_schedule_leader()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    SELECT pg_advisory_unlock(hashtextextended('operations.jobs.schedule_leader.v1', 0))
$function$;

CREATE FUNCTION operations.jobs_claim_due_schedule(
    p_tenant_id BIGINT,
    p_schedule_id UUID,
    p_due_at TIMESTAMPTZ,
    p_next_due_at TIMESTAMPTZ,
    p_request_identity TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_schedule operations.job_schedules%ROWTYPE;
    v_existing_run UUID;
    v_run_id UUID;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs schedule tenant context is invalid';
    END IF;
    IF p_due_at IS NULL
       OR p_next_due_at IS NULL
       OR p_request_identity IS NULL
       OR p_request_identity !~ '^[0-9a-f]{64}$'
       OR p_next_due_at <= p_due_at
    THEN
        RAISE EXCEPTION 'Jobs schedule request is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    SELECT * INTO v_schedule
      FROM operations.job_schedules
     WHERE id = p_schedule_id AND tenant_id = p_tenant_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs schedule is unavailable';
    END IF;
    IF NOT v_schedule.enabled OR v_schedule.next_due_at IS NULL
       OR v_schedule.next_due_at > p_due_at
    THEN
        RETURN NULL;
    END IF;

    SELECT run_id INTO v_existing_run
      FROM operations.job_schedule_events
     WHERE tenant_id = p_tenant_id
       AND schedule_id = p_schedule_id
       AND configuration_revision = v_schedule.configuration_revision
       AND due_at = p_due_at;
    IF v_existing_run IS NOT NULL THEN
        RETURN v_existing_run;
    END IF;

    v_run_id := operations.jobs_request(
        p_tenant_id, v_schedule.definition_key, v_schedule.definition_digest,
        v_schedule.scope_identity, p_request_identity, 'automatic', NULL,
        '{}'::jsonb, '{}'::jsonb, NULL
    );
    INSERT INTO operations.job_schedule_events (
        tenant_id, schedule_id, definition_key, definition_digest,
        configuration_revision, due_at, outcome, consumed_ticks, reason, request_id, run_id
    )
    SELECT p_tenant_id, p_schedule_id, v_schedule.definition_key, v_schedule.definition_digest,
           v_schedule.configuration_revision, p_due_at, 'requested', 1,
           'Due schedule admitted through the Jobs schedule API.', request.id, v_run_id
      FROM operations.job_requests AS request
     WHERE request.tenant_id = p_tenant_id
       AND request.definition_key = v_schedule.definition_key
       AND request.definition_digest = v_schedule.definition_digest
       AND request.scope_identity = v_schedule.scope_identity
       AND request.request_identity = p_request_identity;

    UPDATE operations.job_schedules
       SET last_consumed_due_at = p_due_at,
           last_requested_at = now(),
           last_request_id = (
               SELECT id FROM operations.job_requests
                WHERE tenant_id = p_tenant_id
                  AND definition_key = v_schedule.definition_key
                  AND definition_digest = v_schedule.definition_digest
                  AND scope_identity = v_schedule.scope_identity
                  AND request_identity = p_request_identity
           ),
           last_run_id = v_run_id,
           last_outcome = 'requested',
           next_due_at = p_next_due_at
     WHERE id = p_schedule_id AND tenant_id = p_tenant_id;
    RETURN v_run_id;
END
$function$;

ALTER FUNCTION operations.jobs_register_definition(TEXT, TEXT, TEXT, JSONB)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_request(
    BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB, JSONB, UUID
)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_try_schedule_leader() OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_release_schedule_leader() OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_claim_due_schedule(BIGINT, UUID, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
    OWNER TO operations_migrate;

REVOKE ALL ON FUNCTION operations.jobs_register_definition(TEXT, TEXT, TEXT, JSONB),
    operations.jobs_request(BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB, JSONB, UUID),
    operations.jobs_try_schedule_leader(), operations.jobs_release_schedule_leader(),
    operations.jobs_claim_due_schedule(BIGINT, UUID, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_register_definition(TEXT, TEXT, TEXT, JSONB)
    TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.jobs_request(
    BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB, JSONB, UUID
)
    TO operations_app, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.jobs_try_schedule_leader(),
    operations.jobs_release_schedule_leader(),
    operations.jobs_claim_due_schedule(BIGINT, UUID, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0183_jobs_contract_preparation"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
