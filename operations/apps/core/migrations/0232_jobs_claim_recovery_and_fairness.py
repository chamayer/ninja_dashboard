"""Repair Jobs claim recovery, fairness, and schedule deferral behavior."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
WITH reconciled AS (
    UPDATE operations.job_resource_claims AS claim
       SET state = 'contained',
           release_reason = 'terminal Job retained a held claim; administrator verification required'
      FROM operations.operator_job_runs AS run
     WHERE claim.tenant_id = run.tenant_id
       AND claim.run_id = run.id
       AND claim.state = 'held'
       AND run.contract_version = 1
       AND run.status = 'stalled'
    RETURNING claim.tenant_id, claim.run_id
)
INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
SELECT DISTINCT tenant_id, run_id, 'claim_contained', 'Needs attention',
       'A terminal Job retained a claim from an earlier worker transition; it is contained pending administrator verification.'
  FROM reconciled;

CREATE FUNCTION operations.jobs_claim_next_v5(
    p_tenant_id BIGINT, p_lane TEXT, p_worker_incarnation UUID
) RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)
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
    v_token UUID;
    v_timeout_minutes INTEGER;
    v_blocked BOOLEAN;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_lane NOT IN ('collection', 'evaluation', 'software', 'intelligence', 'service')
       OR p_worker_incarnation IS NULL
    THEN RAISE EXCEPTION 'Jobs claim context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    PERFORM 1 FROM operations.job_lane_limits
     WHERE tenant_id = p_tenant_id AND lane = p_lane FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs lane policy is unavailable'; END IF;

    FOR v_run IN
        SELECT job.*
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
                      job.priority + floor(EXTRACT(EPOCH FROM (now() - job.requested_at)) / 300)::integer
                  ) DESC,
                  job.requested_at, job.id
         FOR UPDATE SKIP LOCKED
    LOOP
        SELECT metadata INTO v_metadata
          FROM operations.job_definition_versions
         WHERE definition_key = v_run.job_key
           AND definition_digest = v_run.definition_digest;
        IF jsonb_typeof(v_metadata->'resource_keys') <> 'array' THEN
            RAISE EXCEPTION 'Jobs definition resource policy is invalid';
        END IF;
        SELECT COALESCE((v_metadata->>'timeout_minutes')::integer, 90)
          INTO v_timeout_minutes;
        IF v_timeout_minutes NOT BETWEEN 1 AND 1440 THEN
            RAISE EXCEPTION 'Jobs definition timeout contract is invalid';
        END IF;
        SELECT array_agg(DISTINCT resource_template ORDER BY resource_template)
          INTO v_templates
          FROM (
              SELECT unnest(ARRAY['execution:deployment', 'lane:' || p_lane]) AS resource_template
              UNION ALL
              SELECT jsonb_array_elements_text(v_metadata->'resource_keys')
          ) AS resources;

        v_blocked := FALSE;
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
            IF v_capacity IS NULL THEN RAISE EXCEPTION 'Jobs resource policy is unavailable'; END IF;
            SELECT count(*) INTO v_active_claims
              FROM operations.job_resource_claims
             WHERE resource_identity = v_identity AND state IN ('held', 'contained');
            IF v_active_claims >= v_capacity THEN
                v_blocked := TRUE;
                EXIT;
            END IF;
        END LOOP;
        IF v_blocked THEN
            UPDATE operations.operator_job_runs
               SET wait_category = 'resource',
                   wait_reason = 'Waiting for a protected resource held by earlier work.'
             WHERE tenant_id = p_tenant_id AND id = v_run.id
               AND wait_category IS DISTINCT FROM 'resource';
            CONTINUE;
        END IF;

        v_token := gen_random_uuid();
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
               deadline_at = now() + make_interval(mins => v_timeout_minutes),
               worker_incarnation = p_worker_incarnation, claim_token = v_token,
               claim_generation = v_generation, attempts = attempts + 1,
               wait_category = NULL, wait_reason = NULL
         WHERE tenant_id = p_tenant_id AND id = v_run.id AND status = 'queued';
        INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
        VALUES (p_tenant_id, v_run.id, 'claimed', 'Starting', 'Claimed through the fair Jobs resource API.');
        run_id := v_run.id;
        claim_token := v_token;
        job_key := v_run.job_key;
        RETURN NEXT;
        RETURN;
    END LOOP;
    RETURN;
END
$function$;

CREATE OR REPLACE FUNCTION operations.jobs_claim_due_schedule(
    p_tenant_id BIGINT, p_schedule_id UUID, p_due_at TIMESTAMPTZ,
    p_next_due_at TIMESTAMPTZ, p_request_identity TEXT
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
    v_message TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_due_at IS NULL OR p_next_due_at IS NULL
       OR p_request_identity IS NULL OR p_request_identity !~ '^[0-9a-f]{64}$'
       OR p_next_due_at <= p_due_at
    THEN RAISE EXCEPTION 'Jobs schedule request is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    SELECT * INTO v_schedule FROM operations.job_schedules
     WHERE id = p_schedule_id AND tenant_id = p_tenant_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs schedule is unavailable'; END IF;
    IF NOT v_schedule.enabled OR v_schedule.next_due_at IS NULL OR v_schedule.next_due_at > p_due_at THEN
        RETURN NULL;
    END IF;
    SELECT run_id INTO v_existing_run FROM operations.job_schedule_events
     WHERE tenant_id = p_tenant_id AND schedule_id = p_schedule_id
       AND configuration_revision = v_schedule.configuration_revision AND due_at = p_due_at;
    IF v_existing_run IS NOT NULL THEN RETURN v_existing_run; END IF;
    BEGIN
        v_run_id := operations.jobs_request(
            p_tenant_id, v_schedule.definition_key, v_schedule.definition_digest,
            v_schedule.scope_identity, p_request_identity, 'automatic', NULL,
            '{}'::jsonb, '{}'::jsonb, NULL
        );
    EXCEPTION WHEN raise_exception THEN
        GET STACKED DIAGNOSTICS v_message = MESSAGE_TEXT;
        IF v_message NOT LIKE 'Conflicting%' THEN RAISE; END IF;
        INSERT INTO operations.job_schedule_events (
            tenant_id, schedule_id, definition_key, definition_digest,
            configuration_revision, due_at, outcome, consumed_ticks, reason
        ) VALUES (
            p_tenant_id, p_schedule_id, v_schedule.definition_key, v_schedule.definition_digest,
            v_schedule.configuration_revision, p_due_at, 'deferred', 1,
            'Deferred while an incompatible retained Job request drains.'
        );
        UPDATE operations.job_schedules
           SET last_consumed_due_at = p_due_at, last_outcome = 'deferred', next_due_at = p_next_due_at
         WHERE id = p_schedule_id AND tenant_id = p_tenant_id;
        RETURN NULL;
    END;
    INSERT INTO operations.job_schedule_events (
        tenant_id, schedule_id, definition_key, definition_digest,
        configuration_revision, due_at, outcome, consumed_ticks, reason, request_id, run_id
    )
    SELECT p_tenant_id, p_schedule_id, v_schedule.definition_key, v_schedule.definition_digest,
           v_schedule.configuration_revision, p_due_at, 'requested', 1,
           'Due schedule admitted through the Jobs schedule API.', request.id, v_run_id
      FROM operations.job_requests AS request
     WHERE request.tenant_id = p_tenant_id AND request.definition_key = v_schedule.definition_key
       AND request.definition_digest = v_schedule.definition_digest
       AND request.scope_identity = v_schedule.scope_identity
       AND request.request_identity = p_request_identity;
    UPDATE operations.job_schedules
       SET last_consumed_due_at = p_due_at, last_requested_at = now(),
           last_request_id = (SELECT id FROM operations.job_requests WHERE tenant_id = p_tenant_id
                              AND definition_key = v_schedule.definition_key
                              AND definition_digest = v_schedule.definition_digest
                              AND scope_identity = v_schedule.scope_identity
                              AND request_identity = p_request_identity),
           last_run_id = v_run_id, last_outcome = 'requested', next_due_at = p_next_due_at
     WHERE id = p_schedule_id AND tenant_id = p_tenant_id;
    RETURN v_run_id;
END
$function$;

CREATE FUNCTION operations.jobs_release_contained_claim_v1(
    p_tenant_id BIGINT, p_run_id UUID, p_actor_id INTEGER, p_reason TEXT
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_count BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_actor_id IS NULL OR p_reason IS NULL
       OR length(p_reason) NOT BETWEEN 12 AND 500
    THEN RAISE EXCEPTION 'Jobs contained-claim recovery is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF NOT EXISTS (SELECT 1 FROM operations.users WHERE tenant_id = p_tenant_id AND id = p_actor_id) THEN
        RAISE EXCEPTION 'Jobs recovery actor is outside the tenant';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM operations.operator_job_runs
                    WHERE tenant_id = p_tenant_id AND id = p_run_id AND status = 'stalled') THEN
        RAISE EXCEPTION 'Only a stalled Job can release contained claims';
    END IF;
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = p_reason
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id AND state = 'contained';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count = 0 THEN RAISE EXCEPTION 'No contained Jobs claim is available'; END IF;
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, p_run_id, 'claim_released_after_review', 'Needs attention',
            'An administrator verified recovery and released contained resource claims.');
    RETURN v_count;
END
$function$;

ALTER FUNCTION operations.jobs_claim_next_v5(BIGINT, TEXT, UUID) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_claim_due_schedule(BIGINT, UUID, TIMESTAMPTZ, TIMESTAMPTZ, TEXT) OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_release_contained_claim_v1(BIGINT, UUID, INTEGER, TEXT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_claim_next_v5(BIGINT, TEXT, UUID),
    operations.jobs_claim_due_schedule(BIGINT, UUID, TIMESTAMPTZ, TIMESTAMPTZ, TEXT),
    operations.jobs_release_contained_claim_v1(BIGINT, UUID, INTEGER, TEXT)
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v5(BIGINT, TEXT, UUID),
    operations.jobs_claim_due_schedule(BIGINT, UUID, TIMESTAMPTZ, TIMESTAMPTZ, TEXT)
TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.jobs_release_contained_claim_v1(BIGINT, UUID, INTEGER, TEXT)
TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0231_jobs_definition_priority_contract"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
