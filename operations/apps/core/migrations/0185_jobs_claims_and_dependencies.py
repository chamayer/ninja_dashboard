"""Add constrained v1 Jobs claim, resource, and dependency primitives."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.job_lane_limits (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    lane TEXT NOT NULL CHECK (
        lane IN ('collection', 'evaluation', 'software', 'intelligence', 'service')
    ),
    capacity SMALLINT NOT NULL CHECK (capacity BETWEEN 1 AND 2),
    policy_revision TEXT NOT NULL CHECK (policy_revision ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (tenant_id, lane)
);

CREATE TABLE operations.job_resource_limits (
    resource_template TEXT PRIMARY KEY CHECK (
        resource_template IN (
            'execution:deployment', 'tenant:{tenant_id}:state',
            'global:intel-cve-corpus', 'global:software-catalog',
            'tenant:{tenant_id}:software-inventory',
            'tenant:{tenant_id}:notification-delivery',
            'tenant:{tenant_id}:legacy-agent-compliance'
        )
    ),
    capacity SMALLINT NOT NULL CHECK (capacity BETWEEN 1 AND 2),
    policy_revision TEXT NOT NULL CHECK (policy_revision ~ '^[0-9a-f]{64}$')
);

CREATE TABLE operations.job_resource_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    run_id UUID NOT NULL,
    claim_token UUID NOT NULL,
    claim_generation BIGINT NOT NULL CHECK (claim_generation > 0),
    resource_template TEXT NOT NULL CHECK (length(resource_template) BETWEEN 1 AND 120),
    resource_identity TEXT NOT NULL CHECK (length(resource_identity) BETWEEN 1 AND 240),
    state TEXT NOT NULL CHECK (state IN ('held', 'contained', 'released')),
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at TIMESTAMPTZ,
    release_reason TEXT NOT NULL DEFAULT '',
    UNIQUE (tenant_id, run_id, claim_generation, resource_template),
    UNIQUE (tenant_id, id),
    CHECK ((state = 'released') = (released_at IS NOT NULL)),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id)
);
CREATE INDEX jobs_resource_claims_active
    ON operations.job_resource_claims (resource_identity, state, claimed_at)
    WHERE state IN ('held', 'contained');

CREATE TABLE operations.job_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    dependent_run_id UUID NOT NULL,
    prerequisite_run_id UUID NOT NULL,
    required_input_revisions JSONB NOT NULL CHECK (
        jsonb_typeof(required_input_revisions) = 'object'
        AND octet_length(required_input_revisions::text) <= 65536
    ),
    required_output_revision TEXT NOT NULL CHECK (required_output_revision ~ '^[0-9a-f]{64}$'),
    failure_rule TEXT NOT NULL CHECK (failure_rule IN ('block')),
    state TEXT NOT NULL CHECK (state IN ('waiting', 'released', 'blocked')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    CHECK (dependent_run_id <> prerequisite_run_id),
    UNIQUE (tenant_id, dependent_run_id, prerequisite_run_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, dependent_run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id),
    FOREIGN KEY (tenant_id, prerequisite_run_id)
        REFERENCES operations.operator_job_runs (tenant_id, id)
);
CREATE INDEX jobs_dependencies_waiting
    ON operations.job_dependencies (tenant_id, dependent_run_id, state)
    WHERE state = 'waiting';

INSERT INTO operations.job_lane_limits (tenant_id, lane, capacity, policy_revision)
VALUES
    (1, 'collection', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    (1, 'evaluation', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    (1, 'software', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    (1, 'intelligence', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    (1, 'service', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275');
INSERT INTO operations.job_resource_limits (resource_template, capacity, policy_revision)
VALUES
    ('execution:deployment', 2, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    ('tenant:{tenant_id}:state', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    ('global:intel-cve-corpus', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    ('global:software-catalog', 1, '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    ('tenant:{tenant_id}:software-inventory', 1,
     '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    ('tenant:{tenant_id}:notification-delivery', 1,
     '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275'),
    ('tenant:{tenant_id}:legacy-agent-compliance', 1,
     '6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275');

DO $security$
DECLARE jobs_table TEXT;
BEGIN
    FOREACH jobs_table IN ARRAY ARRAY[
        'job_lane_limits', 'job_resource_claims', 'job_dependencies'
    ] LOOP
        EXECUTE format('ALTER TABLE operations.%I OWNER TO operations_migrate', jobs_table);
        EXECUTE format(
            'REVOKE ALL ON operations.%I FROM PUBLIC, operations_app, ninja_ingest, '
            'operations_readonly, metabase_ro', jobs_table
        );
        EXECUTE format('ALTER TABLE operations.%I ENABLE ROW LEVEL SECURITY', jobs_table);
        EXECUTE format('ALTER TABLE operations.%I FORCE ROW LEVEL SECURITY', jobs_table);
        EXECUTE format(
            'CREATE POLICY jobs_claim_tenant_isolation ON operations.%I '
            'USING (current_user = ''operations_migrate'' OR tenant_id = '
            'NULLIF(current_setting(''operations.tenant_id'', TRUE), '''')::bigint) '
            'WITH CHECK (current_user = ''operations_migrate'' OR tenant_id = '
            'NULLIF(current_setting(''operations.tenant_id'', TRUE), '''')::bigint)',
            jobs_table
        );
    END LOOP;
END
$security$;
ALTER TABLE operations.job_resource_limits OWNER TO operations_migrate;
REVOKE ALL ON operations.job_resource_limits
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

CREATE FUNCTION operations.jobs_claim_next_v1(
    p_tenant_id BIGINT,
    p_lane TEXT,
    p_worker_incarnation UUID
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_run operations.operator_job_runs%ROWTYPE;
    v_metadata JSONB;
    v_templates TEXT[];
    v_template TEXT;
    v_identity TEXT;
    v_capacity SMALLINT;
    v_active_claims BIGINT;
    v_generation BIGINT;
    v_token UUID := gen_random_uuid();
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_lane NOT IN ('collection', 'evaluation', 'software', 'intelligence', 'service')
       OR p_worker_incarnation IS NULL
    THEN
        RAISE EXCEPTION 'Jobs claim context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    PERFORM 1 FROM operations.job_lane_limits
     WHERE tenant_id = p_tenant_id AND lane = p_lane FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs lane policy is unavailable';
    END IF;

    SELECT job.* INTO v_run
      FROM operations.operator_job_runs AS job
     WHERE job.tenant_id = p_tenant_id
       AND job.contract_version = 1
       AND job.lane = p_lane
       AND job.status = 'queued'
       AND NOT EXISTS (
           SELECT 1 FROM operations.job_dependencies AS dependency
            WHERE dependency.tenant_id = p_tenant_id
              AND dependency.dependent_run_id = job.id
              AND dependency.state <> 'released'
       )
     ORDER BY LEAST(
                  100,
                  job.priority + floor(
                      EXTRACT(EPOCH FROM (now() - job.requested_at)) / 300
                  )::integer
              ) DESC,
              job.requested_at, job.id
     FOR UPDATE SKIP LOCKED
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT metadata INTO v_metadata
      FROM operations.job_definition_versions
     WHERE definition_key = v_run.job_key AND definition_digest = v_run.definition_digest;
    IF jsonb_typeof(v_metadata->'resource_keys') <> 'array' THEN
        RAISE EXCEPTION 'Jobs definition resource policy is invalid';
    END IF;
    SELECT array_agg(DISTINCT resource_template ORDER BY resource_template)
      INTO v_templates
      FROM (
          SELECT unnest(ARRAY['execution:deployment', 'lane:' || p_lane]) AS resource_template
          UNION ALL
          SELECT jsonb_array_elements_text(v_metadata->'resource_keys')
      ) AS resources;

    FOREACH v_template IN ARRAY v_templates LOOP
        v_identity := replace(v_template, '{tenant_id}', p_tenant_id::text);
        PERFORM pg_advisory_xact_lock(
            hashtextextended('operations.jobs.resource:' || v_identity, 0)
        );
        IF v_template LIKE 'lane:%' THEN
            SELECT capacity INTO v_capacity FROM operations.job_lane_limits
             WHERE tenant_id = p_tenant_id AND lane = substring(v_template FROM 6);
        ELSE
            SELECT capacity INTO v_capacity FROM operations.job_resource_limits
             WHERE resource_template = v_template;
        END IF;
        IF v_capacity IS NULL THEN
            RAISE EXCEPTION 'Jobs resource policy is unavailable';
        END IF;
        SELECT count(*) INTO v_active_claims
          FROM operations.job_resource_claims
         WHERE resource_identity = v_identity AND state IN ('held', 'contained');
        IF v_active_claims >= v_capacity THEN
            RETURN NULL;
        END IF;
    END LOOP;

    v_generation := COALESCE(v_run.claim_generation, 0) + 1;
    FOREACH v_template IN ARRAY v_templates LOOP
        INSERT INTO operations.job_resource_claims (
            tenant_id, run_id, claim_token, claim_generation,
            resource_template, resource_identity, state
        ) VALUES (
            p_tenant_id, v_run.id, v_token, v_generation,
            v_template, replace(v_template, '{tenant_id}', p_tenant_id::text), 'held'
        );
    END LOOP;
    UPDATE operations.operator_job_runs
       SET status = 'running', stage = 'Starting', stage_detail = '',
           stage_updated_at = now(), started_at = now(), heartbeat_at = now(),
           worker_incarnation = p_worker_incarnation, claim_token = v_token,
           claim_generation = v_generation
     WHERE tenant_id = p_tenant_id AND id = v_run.id AND status = 'queued';
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, v_run.id, 'claimed', 'Starting', 'Claimed through the Jobs resource API.');
    RETURN v_token;
END
$function$;

CREATE FUNCTION operations.jobs_release_dependencies_v1(
    p_tenant_id BIGINT,
    p_prerequisite_run_id UUID,
    p_output_revision TEXT
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_released BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_prerequisite_run_id IS NULL OR p_output_revision !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'Jobs dependency release is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF NOT EXISTS (
        SELECT 1 FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id AND id = p_prerequisite_run_id
           AND contract_version = 1 AND status = 'completed'
           AND output_revisions @> jsonb_build_object('revision', p_output_revision)
    ) THEN
        RAISE EXCEPTION 'Jobs prerequisite has not published the required output revision';
    END IF;
    UPDATE operations.job_dependencies
       SET state = 'released', reason = '', resolved_at = now()
     WHERE tenant_id = p_tenant_id AND prerequisite_run_id = p_prerequisite_run_id
       AND state = 'waiting' AND required_output_revision = p_output_revision;
    GET DIAGNOSTICS v_released = ROW_COUNT;
    RETURN v_released;
END
$function$;

CREATE FUNCTION operations.jobs_release_v1_claim(
    p_tenant_id BIGINT,
    p_run_id UUID,
    p_claim_token UUID,
    p_reason TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL OR length(p_reason) NOT BETWEEN 1 AND 500
    THEN
        RAISE EXCEPTION 'Jobs claim release context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = p_reason
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id AND claim_token = p_claim_token
       AND state = 'held';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Jobs claim is unavailable or fenced';
    END IF;
END
$function$;

CREATE FUNCTION operations.jobs_add_dependency_v1(
    p_tenant_id BIGINT,
    p_dependent_run_id UUID,
    p_prerequisite_run_id UUID,
    p_required_input_revisions JSONB,
    p_required_output_revision TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_dependency_id UUID := gen_random_uuid();
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_dependent_run_id IS NULL OR p_prerequisite_run_id IS NULL
       OR p_dependent_run_id = p_prerequisite_run_id
       OR jsonb_typeof(p_required_input_revisions) <> 'object'
       OR p_required_output_revision !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'Jobs dependency is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.jobs.dependencies:' || p_tenant_id, 0)
    );
    IF NOT EXISTS (
        SELECT 1 FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id AND id = p_dependent_run_id AND contract_version = 1
    ) OR NOT EXISTS (
        SELECT 1 FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant_id AND id = p_prerequisite_run_id AND contract_version = 1
    ) THEN
        RAISE EXCEPTION 'Jobs dependency requires converted Jobs';
    END IF;
    IF EXISTS (
        WITH RECURSIVE descendants(run_id) AS (
            SELECT p_prerequisite_run_id
            UNION
            SELECT dependency.dependent_run_id
              FROM operations.job_dependencies AS dependency
              JOIN descendants ON dependency.prerequisite_run_id = descendants.run_id
             WHERE dependency.tenant_id = p_tenant_id
        )
        SELECT 1 FROM descendants WHERE run_id = p_dependent_run_id
    ) THEN
        RAISE EXCEPTION 'Jobs dependency would create a cycle';
    END IF;
    INSERT INTO operations.job_dependencies (
        id, tenant_id, dependent_run_id, prerequisite_run_id,
        required_input_revisions, required_output_revision, failure_rule, state, reason
    ) VALUES (
        v_dependency_id, p_tenant_id, p_dependent_run_id, p_prerequisite_run_id,
        p_required_input_revisions, p_required_output_revision, 'block', 'waiting',
        'Waiting for the required prerequisite result.'
    );
    RETURN v_dependency_id;
END
$function$;

ALTER FUNCTION operations.jobs_claim_next_v1(BIGINT, TEXT, UUID) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_release_v1_claim(BIGINT, UUID, UUID, TEXT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_add_dependency_v1(BIGINT, UUID, UUID, JSONB, TEXT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_release_dependencies_v1(BIGINT, UUID, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_claim_next_v1(BIGINT, TEXT, UUID),
    operations.jobs_release_v1_claim(BIGINT, UUID, UUID, TEXT),
    operations.jobs_add_dependency_v1(BIGINT, UUID, UUID, JSONB, TEXT),
    operations.jobs_release_dependencies_v1(BIGINT, UUID, TEXT)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v1(BIGINT, TEXT, UUID),
    operations.jobs_release_v1_claim(BIGINT, UUID, UUID, TEXT),
    operations.jobs_add_dependency_v1(BIGINT, UUID, UUID, JSONB, TEXT),
    operations.jobs_release_dependencies_v1(BIGINT, UUID, TEXT)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0184_jobs_admission_and_schedule_apis"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
