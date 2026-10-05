"""Restore revision publication removed by operation-entry-point completion."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
/*
 * 0244 made a completed step terminal, but unintentionally omitted the
 * revision-publication portion of jobs_finish_v1.  Revision dependencies use
 * that immutable output evidence to release their successors.  Restore it
 * without bringing back coordinator-style running rows.
 */
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
    v_published_revisions JSONB := '{}'::jsonb;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_id IS NULL OR p_claim_token IS NULL
       OR p_status NOT IN ('completed', 'failed')
       OR p_rows_touched IS NOT NULL AND p_rows_touched < 0
       OR p_error IS NULL OR length(p_error) > 2000
       OR p_result IS NULL OR jsonb_typeof(p_result) <> 'object'
       OR octet_length(p_result::text) > 65536
       OR EXISTS (
           SELECT 1 FROM jsonb_object_keys(p_result) AS result_key(key)
            WHERE key ~* '(token|secret|password|authorization|credential)'
       )
    THEN RAISE EXCEPTION 'Jobs finish context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
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
    END IF;
    v_stage := CASE WHEN p_status = 'completed' THEN 'Completed' ELSE 'Failed' END;
    v_detail := CASE WHEN p_status = 'completed' THEN 'Finished.' ELSE 'Review the recorded error.' END;
    UPDATE operations.operator_job_runs
       SET status = p_status, stage = v_stage, stage_detail = v_detail,
           stage_updated_at = now(), heartbeat_at = now(), completed_at = now(),
           lease_expires_at = NULL, deadline_at = NULL,
           rows_touched = p_rows_touched, error = p_error, result = p_result,
           output_revisions = COALESCE(output_revisions, '{}'::jsonb) || v_published_revisions,
           wait_category = NULL, wait_reason = NULL,
           worker_incarnation = worker_incarnation, claim_token = claim_token,
           terminal_reason = CASE WHEN p_status = 'completed' THEN 'completed' ELSE 'failed' END
     WHERE tenant_id = p_tenant_id AND id = p_run_id
       AND contract_version = 1 AND status = 'running' AND claim_token = p_claim_token;
    IF NOT FOUND THEN RAISE EXCEPTION 'Jobs finish is unavailable or fenced'; END IF;
    UPDATE operations.job_resource_claims
       SET state = 'released', released_at = now(), release_reason = p_status
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
       AND claim_token = p_claim_token AND state = 'held';
    INSERT INTO operations.operator_job_events (tenant_id, job_id, event_type, stage, detail)
    VALUES (p_tenant_id, p_run_id, p_status, v_stage, v_detail);
    PERFORM operations.jobs_propagate_dependency_terminal_v1(p_tenant_id, p_run_id, p_status);
END
$function$;

/* Repair only successful prerequisites affected while 0244 was active.  The
 * values are the immutable revisions already recorded on their dependency
 * edges; no work is rerun and failed or unrelated historical runs are left
 * unchanged. */
SELECT set_config('operations.tenant_id', '1', TRUE);

WITH repaired AS (
    UPDATE operations.operator_job_runs prerequisite
       SET output_revisions = COALESCE(prerequisite.output_revisions, '{}'::jsonb)
                              || published.revisions
      FROM (
          SELECT dependency.tenant_id, dependency.prerequisite_run_id,
                 jsonb_object_agg(
                     dependency.required_input_revisions->>'revision_name',
                     dependency.required_output_revision
                 ) AS revisions
            FROM operations.job_dependencies dependency
            JOIN operations.operator_job_runs run
              ON run.tenant_id = dependency.tenant_id
             AND run.id = dependency.prerequisite_run_id
           WHERE dependency.tenant_id = 1
             AND dependency.state = 'waiting'
             AND dependency.required_input_revisions->>'dependency_kind' = 'workflow'
             AND run.status = 'completed'
           GROUP BY dependency.tenant_id, dependency.prerequisite_run_id
      ) published
     WHERE prerequisite.tenant_id = published.tenant_id
       AND prerequisite.id = published.prerequisite_run_id
    RETURNING prerequisite.tenant_id, prerequisite.id
)
SELECT operations.jobs_propagate_dependency_terminal_v1(tenant_id, id, 'completed')
  FROM repaired;

ALTER FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_finish_v1(BIGINT, UUID, UUID, TEXT, INTEGER, TEXT, JSONB)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0248_jobs_lane_capacity_policy"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
