"""Fence Software overview publication with existing Jobs claims and inputs.

No input log or receipt table is added. Uncertified results remain withheld.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
-- Latest owner lookups must not read the entire retained Jobs history.
CREATE INDEX software_overview_owner_checkpoint
    ON operations.operator_job_runs (tenant_id, job_key, requested_at DESC, id DESC);

CREATE FUNCTION operations.software_overview_inputs(p_tenant bigint)
RETURNS jsonb LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    WITH owners(job_key) AS (
        VALUES ('software-classify'), ('software-classify-only'),
               ('software-classify-full'), ('software-enqueue-orgs'),
               ('software-queue-drain'), ('software-catalog'), ('intel-matcher'), ('intel-nvd'),
               ('intel-cpe-dict'), ('intel-kev'), ('intel-epss'),
               ('intel-winget'), ('intel-chocolatey'), ('intel-capability'),
               ('intel-lolrmm'), ('intel-otx'), ('intel-abusech'),
               ('intel-endoflife'), ('intel-category'), ('source-refresh'),
               ('resolver'), ('platform-evaluate'),
               ('computer-client-ownership'), ('computer-client-ownership-sweep')
    ), latest AS MATERIALIZED (
        SELECT owner.job_key, run.id, run.status, run.wait_category,
               run.terminal_reason, run.output_revisions, run.requested_at,
               completion.event_at AS handler_completed_at
          FROM owners owner
          LEFT JOIN LATERAL (
              SELECT r.* FROM operations.operator_job_runs r
               WHERE r.tenant_id = p_tenant AND (
                   r.job_key = owner.job_key OR (
                       owner.job_key IN ('software-classify', 'software-classify-only', 'software-classify-full')
                       AND r.job_key IN ('software-classify', 'software-classify-only', 'software-classify-full')))
               ORDER BY r.requested_at DESC, r.id DESC LIMIT 1
          ) run ON true
          LEFT JOIN LATERAL (
              SELECT e.event_at FROM operations.operator_job_events e
               WHERE e.tenant_id = p_tenant AND e.job_id = run.id
                 AND e.event_type IN ('completed', 'handler_completed')
               ORDER BY e.event_at, e.id LIMIT 1
          ) completion ON true
    )
    SELECT jsonb_build_object(
        'owners', (SELECT jsonb_object_agg(job_key, jsonb_build_object(
            'run_id', id, 'requested_at', requested_at,
            'handler_completed_at', handler_completed_at,
            'output_revisions', coalesce(output_revisions, '{}'::jsonb),
            -- Missing history is recorded as unknown, never certification.
            'observed', id IS NOT NULL,
            'ready', id IS NULL OR status = 'completed' OR
                (status = 'running' AND wait_category = 'workflow'
                 AND terminal_reason = 'handler_completed')
        )) FROM latest),
        'overview_requests', (SELECT coalesce(jsonb_object_agg(r.id, jsonb_build_object(
                'count', requests.request_count, 'last_requested_at', requests.last_requested_at
            )), '{}'::jsonb)
            FROM operations.operator_job_runs r
            CROSS JOIN LATERAL (
                SELECT count(*) AS request_count, max(q.requested_at) AS last_requested_at
                  FROM operations.job_requests q
                 WHERE q.tenant_id = r.tenant_id AND q.run_id = r.id
            ) requests
            WHERE r.tenant_id = p_tenant AND r.job_key = 'software-overview'
              AND r.status IN ('queued', 'running')),
        'ownership_pending', EXISTS (
            SELECT 1 FROM operations.computer_client_ownership
             WHERE tenant_id = p_tenant AND state = 'dirty'),
        'active', (SELECT coalesce(jsonb_agg(r.id ORDER BY r.id), '[]'::jsonb)
            FROM operations.operator_job_runs r
            WHERE r.tenant_id = p_tenant
              AND r.job_key IN (SELECT job_key FROM owners)
              AND r.status = 'running'
              AND NOT (r.wait_category IS NOT DISTINCT FROM 'workflow'
                       AND r.terminal_reason IS NOT DISTINCT FROM 'handler_completed'))
    );
$fn$;
ALTER FUNCTION operations.software_overview_inputs(bigint) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.software_overview_inputs(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;

CREATE FUNCTION operations.begin_software_overview(p_tenant bigint, p_run uuid, p_claim uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE inputs jsonb;
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint
        OR p_run IS NULL OR p_claim IS NULL THEN
        RAISE EXCEPTION 'Software overview preparation context is invalid';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.software.overview:' || p_tenant::text, 0));
    PERFORM 1 FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND id = p_run AND job_key = 'software-overview'
       AND scope_identity = 'tenant:1' AND contract_version = 1
       AND status = 'running' AND claim_token = p_claim
       AND cancellation_requested_at IS NULL
       AND lease_expires_at > clock_timestamp() AND deadline_at > clock_timestamp();
    IF NOT FOUND THEN RAISE EXCEPTION 'Software overview preparation is fenced'; END IF;
    inputs := operations.software_overview_inputs(p_tenant);
    IF (inputs->>'ownership_pending')::boolean OR inputs->'active' <> '[]'::jsonb
       OR EXISTS (SELECT 1 FROM jsonb_each(inputs->'owners') owner
                   WHERE NOT (owner.value->>'ready')::boolean) THEN
        RAISE EXCEPTION 'Software overview preparation inputs are pending or failed';
    END IF;
    RETURN inputs;
END
$fn$;
ALTER FUNCTION operations.begin_software_overview(bigint, uuid, uuid) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.begin_software_overview(bigint, uuid, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.begin_software_overview(bigint, uuid, uuid) TO ninja_ingest;

CREATE FUNCTION operations.publish_software_overview(
    p_tenant bigint, p_run uuid, p_claim uuid, p_prepared_inputs jsonb
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_inputs jsonb;
    v_dependencies jsonb;
    v_generation uuid;
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint
        OR p_run IS NULL OR p_claim IS NULL
        OR current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Software overview publication context is invalid';
    END IF;
    -- Serialize calculation, not just the final row replacement. A queued
    -- successor is a different Jobs row and remains admissible throughout.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('operations.software.overview:' || p_tenant::text, 0));
    PERFORM 1 FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND id = p_run AND job_key = 'software-overview'
       AND scope_identity = 'tenant:1' AND contract_version = 1
       AND status = 'running' AND claim_token = p_claim
       AND cancellation_requested_at IS NULL
       AND lease_expires_at > clock_timestamp() AND deadline_at > clock_timestamp();
    IF NOT FOUND THEN RAISE EXCEPTION 'Software overview publisher is fenced'; END IF;

    IF EXISTS (
        SELECT 1 FROM operations.job_dependencies d
         LEFT JOIN operations.operator_job_runs prerequisite
           ON prerequisite.tenant_id = d.tenant_id AND prerequisite.id = d.prerequisite_run_id
         WHERE d.tenant_id = p_tenant AND d.dependent_run_id = p_run
           AND (d.state <> 'released' OR prerequisite.id IS NULL OR
                prerequisite.output_revisions->>(d.required_input_revisions->>'revision_name')
                    IS DISTINCT FROM d.required_output_revision)
    ) THEN RAISE EXCEPTION 'Software overview prerequisite is incomplete'; END IF;

    v_inputs := operations.software_overview_inputs(p_tenant);
    IF p_prepared_inputs IS NULL OR v_inputs IS DISTINCT FROM p_prepared_inputs THEN
        RAISE EXCEPTION 'Software inputs changed during preparation' USING ERRCODE = '40001';
    END IF;
    IF (v_inputs->>'ownership_pending')::boolean OR v_inputs->'active' <> '[]'::jsonb OR EXISTS (
        SELECT 1 FROM jsonb_each(v_inputs->'owners') owner
         WHERE NOT (owner.value->>'ready')::boolean
    ) THEN RAISE EXCEPTION 'Software overview inputs are pending or failed'; END IF;
    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'run_id', d.prerequisite_run_id,
        'revision_name', d.required_input_revisions->>'revision_name',
        'output_revision', d.required_output_revision
    ) ORDER BY d.prerequisite_run_id, d.id), '[]'::jsonb)
      INTO v_dependencies FROM operations.job_dependencies d
     WHERE d.tenant_id = p_tenant AND d.dependent_run_id = p_run;

    -- 0407 computes every metric from one statement snapshot and replaces
    -- one row. A failure below rolls that replacement back as well.
    v_generation := operations.refresh_software_overview(p_tenant);

    IF operations.software_overview_inputs(p_tenant) IS DISTINCT FROM v_inputs THEN
        RAISE EXCEPTION 'Software overview inputs changed during publication'
            USING ERRCODE = '40001';
    END IF;
    -- Lock only at publication: a revocation during calculation must win.
    -- Hold this fence until commit, and use wall time rather than txn time.
    PERFORM 1 FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant AND id = p_run AND job_key = 'software-overview'
       AND scope_identity = 'tenant:1' AND contract_version = 1
       AND status = 'running' AND claim_token = p_claim
       AND cancellation_requested_at IS NULL
       AND lease_expires_at > clock_timestamp() AND deadline_at > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Software overview publisher was revoked or expired'; END IF;
    UPDATE operations.software_overview_current
       SET input_watermarks = jsonb_build_object(
               'publication_run_id', p_run,
               'owners', v_inputs->'owners', 'dependencies', v_dependencies,
               'overview_requests', v_inputs->'overview_requests'),
           published_at = clock_timestamp()
     WHERE tenant_id = p_tenant AND generation = v_generation;
    IF NOT FOUND THEN RAISE EXCEPTION 'Software overview generation was replaced'; END IF;
    RETURN v_generation;
END
$fn$;
ALTER FUNCTION operations.publish_software_overview(bigint, uuid, uuid, jsonb)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.publish_software_overview(bigint, uuid, uuid, jsonb)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.publish_software_overview(bigint, uuid, uuid, jsonb) TO ninja_ingest;
REVOKE EXECUTE ON FUNCTION operations.refresh_software_overview(bigint) FROM ninja_ingest;

-- Retry an already requested publication after a failed attempt, including
-- bootstrap failure. A migration alone never starts an initial build.
CREATE OR REPLACE FUNCTION operations.software_overview_refresh_due(p_tenant bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'Software overview expiry context is invalid';
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM operations.software_overview_current
         WHERE tenant_id = p_tenant
           AND (window_expires_at <= statement_timestamp()
                OR exposure_expires_at <= statement_timestamp())
    ) OR coalesce((
        SELECT status = 'failed' FROM operations.operator_job_runs
         WHERE tenant_id = p_tenant AND job_key = 'software-overview'
         ORDER BY requested_at DESC, id DESC LIMIT 1
    ), false);
END
$fn$;
"""

REVERSE_SQL = r"""
DROP FUNCTION operations.publish_software_overview(bigint, uuid, uuid, jsonb);
DROP FUNCTION operations.begin_software_overview(bigint, uuid, uuid);
DROP FUNCTION operations.software_overview_inputs(bigint);
DROP INDEX operations.software_overview_owner_checkpoint;
GRANT EXECUTE ON FUNCTION operations.refresh_software_overview(bigint) TO ninja_ingest;
CREATE OR REPLACE FUNCTION operations.software_overview_refresh_due(p_tenant bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS DISTINCT FROM 1 OR p_tenant IS DISTINCT FROM
        nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'Software overview expiry context is invalid';
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM operations.software_overview_current
         WHERE tenant_id = p_tenant
           AND (window_expires_at <= statement_timestamp()
                OR exposure_expires_at <= statement_timestamp())
    );
END
$fn$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0408_software_overview_expiry"),
    ]
    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
