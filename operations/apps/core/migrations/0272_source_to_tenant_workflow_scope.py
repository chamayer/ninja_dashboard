"""Allow declared source-bound refreshes to start tenant-wide analysis."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.jobs_add_revision_dependency_v1(
    p_tenant_id BIGINT, p_dependent_run_id UUID, p_prerequisite_run_id UUID,
    p_revision_name TEXT, p_scope_identity TEXT, p_required_revision TEXT
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    v_context_tenant BIGINT;
    v_dependency_id UUID;
    v_contract JSONB;
    v_existing operations.job_dependencies%ROWTYPE;
    v_prerequisite_scope TEXT;
    v_dependent_scope TEXT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_dependent_run_id IS NULL OR p_prerequisite_run_id IS NULL
       OR p_revision_name IS NULL
       OR p_revision_name !~ '^[a-z0-9][a-z0-9._-]{2,119}$'
       OR p_scope_identity IS NULL OR length(p_scope_identity) NOT BETWEEN 1 AND 256
       OR p_required_revision IS NULL
       OR p_required_revision !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'Jobs revision dependency context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    SELECT scope_identity INTO v_prerequisite_scope
      FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant_id AND id = p_prerequisite_run_id;
    SELECT scope_identity INTO v_dependent_scope
      FROM operations.operator_job_runs
     WHERE tenant_id = p_tenant_id AND id = p_dependent_run_id;
    IF v_prerequisite_scope IS NULL OR v_dependent_scope IS NULL
       OR v_dependent_scope IS DISTINCT FROM p_scope_identity
    THEN RAISE EXCEPTION 'Jobs revision dependency context is invalid'; END IF;

    SELECT edge.contract
      INTO v_contract
      FROM operations.operator_job_runs prerequisite
      JOIN operations.job_definition_versions definition
        ON definition.definition_key = prerequisite.job_key
       AND definition.definition_digest = prerequisite.definition_digest
      JOIN operations.operator_job_runs dependent
        ON dependent.tenant_id = prerequisite.tenant_id
       AND dependent.id = p_dependent_run_id
      CROSS JOIN LATERAL jsonb_array_elements(
          COALESCE(definition.metadata->'successors', '[]'::jsonb)
      ) AS edge(contract)
     WHERE prerequisite.tenant_id = p_tenant_id
       AND prerequisite.id = p_prerequisite_run_id
       AND edge.contract->>'successor' = dependent.job_key
       AND edge.contract->>'revision_name' = p_revision_name
       AND edge.contract->>'scope_mode' IN ('inherit', 'tenant')
       AND edge.contract->>'failure_rule' = 'block';
    IF v_contract IS NULL
       OR (v_contract->>'scope_mode' = 'inherit'
           AND v_prerequisite_scope IS DISTINCT FROM p_scope_identity)
       OR (v_contract->>'scope_mode' = 'tenant'
           AND p_scope_identity IS DISTINCT FROM ('tenant:' || p_tenant_id::text))
    THEN RAISE EXCEPTION 'Jobs revision dependency context is invalid'; END IF;

    SELECT * INTO v_existing
      FROM operations.job_dependencies
     WHERE tenant_id = p_tenant_id
       AND dependent_run_id = p_dependent_run_id
       AND prerequisite_run_id = p_prerequisite_run_id;
    IF FOUND THEN
        IF v_existing.required_output_revision IS DISTINCT FROM p_required_revision
           OR v_existing.required_input_revisions->>'dependency_kind' IS DISTINCT FROM 'workflow'
           OR v_existing.required_input_revisions->>'revision_name' IS DISTINCT FROM p_revision_name
           OR v_existing.required_input_revisions->>'scope_identity' IS DISTINCT FROM p_scope_identity
           OR v_existing.required_input_revisions->>'condition' IS DISTINCT FROM v_contract->>'condition'
           OR v_existing.required_input_revisions->>'scope_mode' IS DISTINCT FROM v_contract->>'scope_mode'
           OR v_existing.required_input_revisions->>'coalescing' IS DISTINCT FROM v_contract->>'coalescing'
           OR v_existing.failure_rule IS DISTINCT FROM v_contract->>'failure_rule'
        THEN RAISE EXCEPTION 'Jobs revision dependency conflicts with the existing edge'; END IF;
        RETURN v_existing.id;
    END IF;

    v_dependency_id := operations.jobs_add_completion_dependency_v1(
        p_tenant_id, p_dependent_run_id, p_prerequisite_run_id
    );
    UPDATE operations.job_dependencies
       SET required_input_revisions = jsonb_build_object(
               'dependency_kind', 'workflow', 'revision_name', p_revision_name,
               'scope_identity', p_scope_identity, 'condition', v_contract->>'condition',
               'scope_mode', v_contract->>'scope_mode', 'coalescing', v_contract->>'coalescing'
           ),
           failure_rule = v_contract->>'failure_rule',
           required_output_revision = p_required_revision,
           reason = 'Waiting for required ' || p_revision_name || ' revision.'
     WHERE tenant_id = p_tenant_id AND id = v_dependency_id;
    UPDATE operations.operator_job_runs
       SET wait_reason = 'Waiting for required ' || p_revision_name || ' revision.'
     WHERE tenant_id = p_tenant_id AND id = p_dependent_run_id AND status = 'queued';
    RETURN v_dependency_id;
END
$function$;

ALTER FUNCTION operations.jobs_add_revision_dependency_v1(
    BIGINT, UUID, UUID, TEXT, TEXT, TEXT
) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_add_revision_dependency_v1(
    BIGINT, UUID, UUID, TEXT, TEXT, TEXT
) FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_add_revision_dependency_v1(
    BIGINT, UUID, UUID, TEXT, TEXT, TEXT
) TO operations_app, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0271_jobs_contained_capacity_release"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
