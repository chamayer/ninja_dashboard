"""Claim source-refresh runs with their binding-specific data lock."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.jobs_claim_next_v7(
    p_tenant_id BIGINT, p_worker_incarnation UUID
) RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT; v_run operations.operator_job_runs%ROWTYPE;
    v_template TEXT; v_templates TEXT[] := ARRAY[
        'capacity:external-io', 'execution:emergency-child',
        'tenant:{tenant_id}:source-binding:{scope_identity}'
    ];
    v_identity TEXT; v_capacity SMALLINT; v_active_claims BIGINT;
    v_generation BIGINT; v_token UUID; v_blocked BOOLEAN;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::BIGINT;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_worker_incarnation IS NULL THEN
        RAISE EXCEPTION 'Jobs claim context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    FOR v_run IN
        SELECT run.* FROM operations.operator_job_runs run
         WHERE run.tenant_id = p_tenant_id AND run.contract_version = 1
           AND run.job_key = 'source-refresh' AND run.status = 'queued'
           AND run.wait_category IS NULL
         ORDER BY LEAST(100, run.priority + floor(EXTRACT(EPOCH FROM (now() - run.requested_at)) / 300)::INTEGER) DESC,
                  run.requested_at, run.id
         FOR UPDATE SKIP LOCKED
    LOOP
        v_blocked := FALSE;
        FOREACH v_template IN ARRAY v_templates LOOP
            v_identity := replace(replace(v_template, '{tenant_id}', p_tenant_id::text),
                                  '{scope_identity}', v_run.scope_identity);
            PERFORM pg_advisory_xact_lock(hashtextextended('operations.jobs.resource:' || v_identity, 0));
            SELECT capacity INTO v_capacity FROM operations.job_resource_limits
             WHERE resource_template = v_template;
            IF v_capacity IS NULL THEN RAISE EXCEPTION 'Jobs resource policy is unavailable'; END IF;
            SELECT count(*) INTO v_active_claims FROM operations.job_resource_claims
             WHERE resource_identity = v_identity AND state IN ('held', 'contained');
            IF v_active_claims >= v_capacity THEN v_blocked := TRUE; EXIT; END IF;
        END LOOP;
        IF v_blocked THEN
            UPDATE operations.operator_job_runs
               SET wait_category = 'capacity', wait_reason = 'Waiting for source connection capacity.',
                   stage = 'Waiting for capacity', stage_detail = '', stage_updated_at = now()
             WHERE tenant_id = p_tenant_id AND id = v_run.id;
            CONTINUE;
        END IF;
        v_token := gen_random_uuid();
        v_generation := COALESCE(v_run.claim_generation, 0) + 1;
        FOREACH v_template IN ARRAY v_templates LOOP
            v_identity := replace(replace(v_template, '{tenant_id}', p_tenant_id::text),
                                  '{scope_identity}', v_run.scope_identity);
            INSERT INTO operations.job_resource_claims
                (tenant_id, run_id, claim_token, claim_generation, resource_template, resource_identity, state)
            VALUES (p_tenant_id, v_run.id, v_token, v_generation, v_template, v_identity, 'held');
        END LOOP;
        UPDATE operations.operator_job_runs
           SET status = 'running', stage = 'Starting', stage_detail = '', stage_updated_at = now(),
               started_at = now(), heartbeat_at = now(), deadline_at = now() + INTERVAL '90 minutes',
               worker_incarnation = p_worker_incarnation, claim_token = v_token,
               claim_generation = v_generation, attempts = attempts + 1,
               wait_category = NULL, wait_reason = NULL
         WHERE tenant_id = p_tenant_id AND id = v_run.id AND status = 'queued';
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, v_run.id, 'claimed', 'Starting', 'Claimed for this configured source.');
        run_id := v_run.id; claim_token := v_token; job_key := v_run.job_key;
        RETURN NEXT; RETURN;
    END LOOP;
    RETURN QUERY SELECT * FROM operations.jobs_claim_next_v6(p_tenant_id, p_worker_incarnation);
END
$function$;

ALTER FUNCTION operations.jobs_claim_next_v7(BIGINT, UUID) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_claim_next_v7(BIGINT, UUID)
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v7(BIGINT, UUID) TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0263_source_refresh_contract")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
