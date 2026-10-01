"""Fix the Jobs activity relation API output-name collision."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.jobs_activity_relations_v1(
    p_tenant_id BIGINT, p_run_ids UUID[]
) RETURNS TABLE(run_id UUID, relation_kind TEXT, item JSONB)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_run_ids IS NULL OR cardinality(p_run_ids) NOT BETWEEN 1 AND 100
       OR EXISTS (SELECT 1 FROM unnest(p_run_ids) AS selected_run(id) WHERE selected_run.id IS NULL)
    THEN RAISE EXCEPTION 'Jobs activity relation context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    RETURN QUERY
    SELECT event.job_id, 'event'::text,
           jsonb_build_object('at', event.event_at, 'type', event.event_type,
                              'stage', event.stage, 'detail', event.detail)
      FROM operations.operator_job_events AS event
     WHERE event.tenant_id = p_tenant_id AND event.job_id = ANY(p_run_ids)
    UNION ALL
    SELECT dependency.dependent_run_id, 'dependency'::text,
           jsonb_build_object(
               'direction', 'prerequisite', 'id', dependency.prerequisite_run_id,
               'job_key', prerequisite.job_key, 'status', prerequisite.status,
               'state', dependency.state, 'reason', dependency.reason,
               'contract', dependency.required_input_revisions,
               'required_revision', dependency.required_output_revision,
               'failure_rule', dependency.failure_rule
           )
      FROM operations.job_dependencies AS dependency
      JOIN operations.operator_job_runs AS prerequisite
        ON prerequisite.tenant_id = dependency.tenant_id
       AND prerequisite.id = dependency.prerequisite_run_id
     WHERE dependency.tenant_id = p_tenant_id
       AND dependency.dependent_run_id = ANY(p_run_ids)
    UNION ALL
    SELECT dependency.prerequisite_run_id, 'dependency'::text,
           jsonb_build_object(
               'direction', 'dependent', 'id', dependency.dependent_run_id,
               'job_key', dependent.job_key, 'status', dependent.status,
               'state', dependency.state, 'reason', dependency.reason,
               'contract', dependency.required_input_revisions,
               'required_revision', dependency.required_output_revision,
               'failure_rule', dependency.failure_rule
           )
      FROM operations.job_dependencies AS dependency
      JOIN operations.operator_job_runs AS dependent
        ON dependent.tenant_id = dependency.tenant_id
       AND dependent.id = dependency.dependent_run_id
     WHERE dependency.tenant_id = p_tenant_id
       AND dependency.prerequisite_run_id = ANY(p_run_ids)
    UNION ALL
    SELECT attempt.job_run_id, 'domain_attempt'::text,
           jsonb_build_object('kind', attempt.domain_kind,
                              'record_id', attempt.domain_record_id,
                              'attempt', attempt.attempt_number,
                              'linked_at', attempt.linked_at)
      FROM operations.job_domain_attempts AS attempt
     WHERE attempt.tenant_id = p_tenant_id AND attempt.job_run_id = ANY(p_run_ids)
    UNION ALL
    SELECT claim.run_id, 'contained_claims'::text,
           jsonb_build_object('count', count(*))
      FROM operations.job_resource_claims AS claim
     WHERE claim.tenant_id = p_tenant_id AND claim.run_id = ANY(p_run_ids)
       AND claim.state = 'contained'
     GROUP BY claim.run_id;
END
$function$;

ALTER FUNCTION operations.jobs_activity_relations_v1(BIGINT, UUID[]) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_activity_relations_v1(BIGINT, UUID[])
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_activity_relations_v1(BIGINT, UUID[])
TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0233_jobs_activity_relations_api"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
