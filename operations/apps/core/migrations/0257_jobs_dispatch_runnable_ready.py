"""Promote only Jobs that can actually obtain their declared resources."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.jobs_dispatch_ready_v1(p_tenant_id BIGINT)
RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_ready INTEGER;
    v_promoted INTEGER := 0;
    v_run operations.operator_job_runs%ROWTYPE;
    v_examined UUID[] := ARRAY[]::UUID[];
    v_metadata JSONB;
    v_templates TEXT[];
    v_template TEXT;
    v_identity TEXT;
    v_capacity SMALLINT;
    v_active_claims BIGINT;
    v_available BOOLEAN;
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
        SELECT run.* INTO v_run
          FROM operations.operator_job_runs run
         WHERE run.tenant_id = p_tenant_id AND run.status = 'queued'
           AND run.wait_category IS NOT NULL
           AND NOT run.id = ANY(v_examined)
           AND NOT EXISTS (
               SELECT 1 FROM operations.job_dependencies dependency
                WHERE dependency.tenant_id = run.tenant_id
                  AND dependency.dependent_run_id = run.id
                  AND dependency.state <> 'released'
           )
         ORDER BY LEAST(100, run.priority + floor(EXTRACT(EPOCH FROM (now() - run.requested_at)) / 300)::integer) DESC,
                  run.requested_at, run.id
         FOR UPDATE SKIP LOCKED LIMIT 1;
        EXIT WHEN v_run.id IS NULL;
        v_examined := array_append(v_examined, v_run.id);
        SELECT metadata INTO v_metadata FROM operations.job_definition_versions
         WHERE definition_key = v_run.job_key AND definition_digest = v_run.definition_digest;
        IF jsonb_typeof(v_metadata->'resource_keys') <> 'array' THEN
            RAISE EXCEPTION 'Jobs definition resource policy is invalid';
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
        v_available := TRUE;
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
                v_available := FALSE;
                EXIT;
            END IF;
        END LOOP;
        IF NOT v_available THEN
            CONTINUE;
        END IF;
        UPDATE operations.operator_job_runs
           SET wait_category = NULL, wait_reason = NULL, stage = 'Ready',
               stage_detail = 'Ready to start when a worker is available.', stage_updated_at = now()
         WHERE tenant_id = p_tenant_id AND id = v_run.id;
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, v_run.id, 'ready', 'Ready', 'Ready to start through the Jobs dispatcher.');
        v_ready := v_ready + 1;
        v_promoted := v_promoted + 1;
        v_run := NULL;
    END LOOP;
    RETURN v_promoted;
END
$function$;
ALTER FUNCTION operations.jobs_dispatch_ready_v1(BIGINT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_dispatch_ready_v1(BIGINT)
FROM PUBLIC, operations_app, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_dispatch_ready_v1(BIGINT) TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0256_jobs_waiting_stage_truth"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
