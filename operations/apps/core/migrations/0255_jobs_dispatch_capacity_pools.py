"""Replace Jobs lane admission with pool-aware database dispatch."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
ALTER TABLE operations.job_resource_limits
    ADD COLUMN IF NOT EXISTS policy_kind TEXT NOT NULL DEFAULT 'domain_lock'
    CHECK (policy_kind IN ('execution_pool', 'domain_lock', 'legacy_compatibility'));

/* The emergency child fuse is four.  Pool limits remain stricter and are
 * validated by the API below. */
ALTER TABLE operations.job_resource_limits
    DROP CONSTRAINT IF EXISTS job_resource_limits_capacity_check;
ALTER TABLE operations.job_resource_limits
    ADD CONSTRAINT job_resource_limits_capacity_check CHECK (capacity BETWEEN 1 AND 4);

ALTER TABLE operations.job_resource_limits
    DROP CONSTRAINT IF EXISTS job_resource_limits_resource_template_check;
ALTER TABLE operations.job_resource_limits
    ADD CONSTRAINT job_resource_limits_resource_template_check CHECK (
        resource_template IN (
            'execution:deployment', 'execution:emergency-child',
            'capacity:external-io', 'capacity:processing', 'capacity:control',
            'tenant:{tenant_id}:state', 'global:intel-cve-corpus',
            'global:software-catalog', 'tenant:{tenant_id}:software-inventory',
            'tenant:{tenant_id}:notification-delivery',
            'tenant:{tenant_id}:legacy-agent-compliance',
            'tenant:{tenant_id}:ninja-source', 'tenant:{tenant_id}:agent-sources',
            'tenant:{tenant_id}:documentation-source', 'tenant:{tenant_id}:software-state',
            'tenant:{tenant_id}:patch-state', 'tenant:{tenant_id}:platform-findings',
            'tenant:{tenant_id}:cmdb-findings', 'tenant:{tenant_id}:identity-state',
            'tenant:{tenant_id}:parity-state', 'tenant:{tenant_id}:software-cve-match',
            'tenant:{tenant_id}:threat-intelligence', 'tenant:{tenant_id}:history-retention',
            'tenant:{tenant_id}:source-actions', 'tenant:{tenant_id}:source-demand',
            'tenant:{tenant_id}:run-history', 'tenant:{tenant_id}:platform-health',
            'tenant:{tenant_id}:reporting'
        )
    );

UPDATE operations.job_resource_limits
   SET policy_kind = CASE WHEN resource_template = 'execution:deployment'
                          THEN 'legacy_compatibility' ELSE 'domain_lock' END;
INSERT INTO operations.job_resource_limits (resource_template, capacity, policy_revision, policy_kind)
VALUES
    ('capacity:external-io', 2, '5b0385558bd57b2e8d2c793d62c0df6df51ca12fdbe4a55ba0541a9ba7598c1f', 'execution_pool'),
    ('capacity:processing', 1, '5b0385558bd57b2e8d2c793d62c0df6df51ca12fdbe4a55ba0541a9ba7598c1f', 'execution_pool'),
    ('capacity:control', 1, '5b0385558bd57b2e8d2c793d62c0df6df51ca12fdbe4a55ba0541a9ba7598c1f', 'execution_pool'),
    ('execution:emergency-child', 4, '5b0385558bd57b2e8d2c793d62c0df6df51ca12fdbe4a55ba0541a9ba7598c1f', 'execution_pool')
ON CONFLICT (resource_template) DO UPDATE
    SET capacity = EXCLUDED.capacity, policy_revision = EXCLUDED.policy_revision,
        policy_kind = EXCLUDED.policy_kind;

/* Historical immutable definitions keep the prior lane/global policy while
 * they drain. New definitions carry capacity_keys and bypass these rows. */
UPDATE operations.job_lane_limits SET capacity = 1, policy_revision = '79919520a72b23f2d1803fc23389fce4b9c260b4505b896023b8b95f7cc47b9f'
 WHERE tenant_id = 1;
UPDATE operations.job_resource_limits SET capacity = 2, policy_revision = '79919520a72b23f2d1803fc23389fce4b9c260b4505b896023b8b95f7cc47b9f'
 WHERE resource_template = 'execution:deployment';

UPDATE operations.operator_job_runs run
   SET wait_category = 'capacity',
       wait_reason = 'Waiting for available Jobs capacity.',
       stage = 'Waiting for capacity',
       stage_detail = 'This work is ready when capacity is available.',
       stage_updated_at = now()
 WHERE run.tenant_id = 1 AND run.status = 'queued'
   AND run.wait_category IS NULL
   AND NOT EXISTS (
       SELECT 1 FROM operations.job_dependencies dependency
        WHERE dependency.tenant_id = run.tenant_id
          AND dependency.dependent_run_id = run.id
          AND dependency.state <> 'released'
   );

CREATE OR REPLACE FUNCTION operations.jobs_default_waiting_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations AS $$
BEGIN
    /* Only the dispatcher may create Ready work.  Dependency release and
     * admission both return work to Waiting so the two-item Ready window is
     * never briefly bypassed between worker loops. */
    IF NEW.contract_version = 1 AND NEW.status = 'queued' AND NEW.wait_category IS NULL
       AND current_setting('operations.jobs_ready_promotion', TRUE) IS DISTINCT FROM 'on' THEN
        NEW.wait_category := 'capacity';
        NEW.wait_reason := 'Waiting for available Jobs capacity.';
        NEW.stage := 'Waiting for capacity';
        NEW.stage_detail := 'This work is ready when capacity is available.';
        NEW.stage_updated_at := now();
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS jobs_default_waiting_before_write ON operations.operator_job_runs;
DROP TRIGGER IF EXISTS jobs_default_waiting_before_insert ON operations.operator_job_runs;
CREATE TRIGGER jobs_default_waiting_before_write
BEFORE INSERT OR UPDATE ON operations.operator_job_runs
FOR EACH ROW EXECUTE FUNCTION operations.jobs_default_waiting_v1();

CREATE OR REPLACE FUNCTION operations.jobs_dispatch_ready_v1(p_tenant_id BIGINT)
RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_ready INTEGER;
    v_promoted INTEGER := 0;
    v_run_id UUID;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs dispatch context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    PERFORM set_config('operations.jobs_ready_promotion', 'on', TRUE);
    PERFORM pg_advisory_xact_lock(hashtextextended('operations.jobs.ready-window:' || p_tenant_id, 0));
    SELECT count(*) INTO v_ready FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant_id AND status = 'queued' AND wait_category IS NULL;
    WHILE v_ready < 2 LOOP
        SELECT run.id INTO v_run_id
          FROM operations.operator_job_runs run
         WHERE run.tenant_id = p_tenant_id AND run.status = 'queued'
           AND run.wait_category IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM operations.job_dependencies dependency
                WHERE dependency.tenant_id = run.tenant_id
                  AND dependency.dependent_run_id = run.id
                  AND dependency.state <> 'released'
           )
         ORDER BY LEAST(100, run.priority + floor(EXTRACT(EPOCH FROM (now() - run.requested_at)) / 300)::integer) DESC,
                  run.requested_at, run.id
         FOR UPDATE SKIP LOCKED LIMIT 1;
        EXIT WHEN v_run_id IS NULL;
        UPDATE operations.operator_job_runs
           SET wait_category = NULL, wait_reason = NULL, stage = 'Ready',
               stage_detail = 'Ready to start when a worker is available.', stage_updated_at = now()
         WHERE tenant_id = p_tenant_id AND id = v_run_id;
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, v_run_id, 'ready', 'Ready', 'Ready to start through the Jobs dispatcher.');
        v_ready := v_ready + 1;
        v_promoted := v_promoted + 1;
        v_run_id := NULL;
    END LOOP;
    RETURN v_promoted;
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_claim_next_v6(
    p_tenant_id BIGINT, p_worker_incarnation UUID
) RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)
LANGUAGE plpgsql SECURITY DEFINER
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
    v_token UUID;
    v_timeout_minutes INTEGER;
    v_blocked BOOLEAN;
    v_block_reason TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_worker_incarnation IS NULL THEN
        RAISE EXCEPTION 'Jobs claim context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    FOR v_run IN
        SELECT run.* FROM operations.operator_job_runs run
         WHERE run.tenant_id = p_tenant_id AND run.contract_version = 1
           AND run.status = 'queued' AND run.wait_category IS NULL
         ORDER BY LEAST(100, run.priority + floor(EXTRACT(EPOCH FROM (now() - run.requested_at)) / 300)::integer) DESC,
                  run.requested_at, run.id
         FOR UPDATE SKIP LOCKED
    LOOP
        SELECT metadata INTO v_metadata FROM operations.job_definition_versions
         WHERE definition_key = v_run.job_key AND definition_digest = v_run.definition_digest;
        IF jsonb_typeof(v_metadata->'resource_keys') <> 'array' THEN
            RAISE EXCEPTION 'Jobs definition resource policy is invalid';
        END IF;
        SELECT COALESCE((v_metadata->>'timeout_minutes')::integer, 90) INTO v_timeout_minutes;
        IF v_timeout_minutes NOT BETWEEN 1 AND 1440 THEN
            RAISE EXCEPTION 'Jobs definition timeout contract is invalid';
        END IF;
        IF jsonb_typeof(v_metadata->'capacity_keys') = 'array' THEN
            SELECT array_agg(DISTINCT item ORDER BY item) INTO v_templates FROM (
                SELECT 'execution:emergency-child'::text AS item
                UNION ALL SELECT jsonb_array_elements_text(v_metadata->'capacity_keys')
                UNION ALL SELECT jsonb_array_elements_text(v_metadata->'resource_keys')
            ) policies;
        ELSE
            SELECT array_agg(DISTINCT item ORDER BY item) INTO v_templates FROM (
                SELECT 'execution:deployment'::text AS item
                UNION ALL SELECT 'lane:' || v_run.lane
                UNION ALL SELECT jsonb_array_elements_text(v_metadata->'resource_keys')
            ) policies;
        END IF;
        v_blocked := FALSE;
        v_block_reason := 'resource';
        FOREACH v_template IN ARRAY v_templates LOOP
            v_identity := replace(v_template, '{tenant_id}', p_tenant_id::text);
            PERFORM pg_advisory_xact_lock(hashtextextended('operations.jobs.resource:' || v_identity, 0));
            IF v_template LIKE 'lane:%' THEN
                SELECT capacity INTO v_capacity FROM operations.job_lane_limits
                 WHERE tenant_id = p_tenant_id AND lane = substring(v_template FROM 6);
            ELSE
                SELECT capacity INTO v_capacity FROM operations.job_resource_limits
                 WHERE resource_template = v_template;
            END IF;
            IF v_capacity IS NULL THEN RAISE EXCEPTION 'Jobs resource policy is unavailable'; END IF;
            SELECT count(*) INTO v_active_claims FROM operations.job_resource_claims
             WHERE resource_identity = v_identity AND state IN ('held', 'contained');
            IF v_active_claims >= v_capacity THEN
                v_blocked := TRUE;
                IF v_template LIKE 'capacity:%' OR v_template = 'execution:emergency-child' THEN
                    v_block_reason := 'capacity';
                END IF;
                EXIT;
            END IF;
        END LOOP;
        IF v_blocked THEN
            UPDATE operations.operator_job_runs
               SET wait_category = v_block_reason,
                   wait_reason = CASE WHEN v_block_reason = 'capacity'
                       THEN 'Waiting for available Jobs capacity.'
                       ELSE 'Waiting for protected work to finish.' END,
                   stage = CASE WHEN v_block_reason = 'capacity' THEN 'Waiting for capacity'
                                ELSE 'Waiting for protected work' END,
                   stage_detail = '', stage_updated_at = now()
             WHERE tenant_id = p_tenant_id AND id = v_run.id;
            CONTINUE;
        END IF;
        v_token := gen_random_uuid();
        v_generation := COALESCE(v_run.claim_generation, 0) + 1;
        FOREACH v_template IN ARRAY v_templates LOOP
            INSERT INTO operations.job_resource_claims
                (tenant_id, run_id, claim_token, claim_generation, resource_template, resource_identity, state)
            VALUES (p_tenant_id, v_run.id, v_token, v_generation, v_template,
                    replace(v_template, '{tenant_id}', p_tenant_id::text), 'held');
        END LOOP;
        UPDATE operations.operator_job_runs
           SET status = 'running', stage = 'Starting', stage_detail = '', stage_updated_at = now(),
               started_at = now(), heartbeat_at = now(),
               deadline_at = now() + make_interval(mins => v_timeout_minutes),
               worker_incarnation = p_worker_incarnation, claim_token = v_token,
               claim_generation = v_generation, attempts = attempts + 1,
               wait_category = NULL, wait_reason = NULL
         WHERE tenant_id = p_tenant_id AND id = v_run.id AND status = 'queued';
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, v_run.id, 'claimed', 'Starting', 'Claimed through the Jobs dispatcher.');
        run_id := v_run.id; claim_token := v_token; job_key := v_run.job_key;
        RETURN NEXT; RETURN;
    END LOOP;
    RETURN;
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_set_execution_pool_capacity_v1(
    p_tenant_id BIGINT, p_key TEXT, p_capacity SMALLINT
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = operations, pg_temp AS $$
BEGIN
    IF p_tenant_id <> 1
       OR (p_key = 'capacity:external-io' AND p_capacity NOT BETWEEN 1 AND 3)
       OR (p_key IN ('capacity:processing', 'capacity:control') AND p_capacity NOT BETWEEN 1 AND 2)
       OR p_key NOT IN ('capacity:external-io', 'capacity:processing', 'capacity:control') THEN
        RAISE EXCEPTION 'Invalid Jobs execution capacity policy';
    END IF;
    UPDATE job_resource_limits SET capacity = p_capacity,
           policy_revision = 'bce1e549e0042c069df3e2a4dcfe310eec0b4b2e7a10b12f6b12dcb2c4e0586f'
     WHERE resource_template = p_key AND policy_kind = 'execution_pool';
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs execution capacity policy is unavailable'; END IF;
END $$;

CREATE OR REPLACE FUNCTION operations.jobs_resource_policy_diagnostics_v1(
    p_tenant_id BIGINT, p_section TEXT, p_limit INTEGER, p_offset INTEGER
) RETURNS TABLE (total_count BIGINT, item JSONB)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations AS $$
DECLARE
    v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_section <> 'resource_limits' OR p_limit NOT BETWEEN 1 AND 100
       OR p_offset NOT BETWEEN 0 AND 1000000 THEN
        RAISE EXCEPTION 'Jobs resource policy diagnostics context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    RETURN QUERY
    SELECT count(*) OVER (), jsonb_build_object(
        'resource_template', policy.resource_template,
        'capacity', policy.capacity,
        'policy_revision', policy.policy_revision,
        'policy_kind', policy.policy_kind
    )
    FROM operations.job_resource_limits policy
    ORDER BY policy.resource_template
    LIMIT p_limit OFFSET p_offset;
END $$;

ALTER FUNCTION operations.jobs_dispatch_ready_v1(BIGINT) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_claim_next_v6(BIGINT, UUID) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_set_execution_pool_capacity_v1(BIGINT, TEXT, SMALLINT) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_resource_policy_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_default_waiting_v1() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_dispatch_ready_v1(BIGINT),
    operations.jobs_claim_next_v6(BIGINT, UUID),
    operations.jobs_set_execution_pool_capacity_v1(BIGINT, TEXT, SMALLINT),
    operations.jobs_resource_policy_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_dispatch_ready_v1(BIGINT),
    operations.jobs_claim_next_v6(BIGINT, UUID) TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.jobs_set_execution_pool_capacity_v1(BIGINT, TEXT, SMALLINT)
    TO operations_app;
GRANT EXECUTE ON FUNCTION operations.jobs_resource_policy_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
    TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0254_jobs_capacity_three")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
