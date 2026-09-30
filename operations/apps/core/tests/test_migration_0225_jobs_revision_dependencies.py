import importlib


def test_workflow_edges_publish_and_recheck_named_scoped_revisions():
    migration = importlib.import_module(
        "apps.core.migrations.0225_jobs_revision_dependencies"
    )
    sql = migration.FORWARD_SQL

    assert "jobs_add_revision_dependency_v1" in sql
    assert "'dependency_kind', 'workflow'" in sql
    assert "'revision_name', p_revision_name" in sql
    assert "'scope_identity', p_scope_identity" in sql
    assert "jsonb_array_elements" in sql
    assert "definition.metadata->'successors'" in sql
    assert "edge.contract->>'successor' = dependent.job_key" in sql
    assert "'condition', v_contract->>'condition'" in sql
    assert "'coalescing', v_contract->>'coalescing'" in sql
    assert "conflicts with the existing edge" in sql
    assert "p_revision_name IS NULL" in sql
    assert "p_required_revision IS NULL" in sql
    assert "p_required_revision !~ '^[0-9a-f]{64}$'" in sql
    assert "prerequisite.output_revisions->>" in sql
    assert "= dependency.required_output_revision" in sql
    assert "jsonb_object_agg(revision_name, required_output_revision)" in sql
    assert "output_revisions = COALESCE(output_revisions" in sql
    assert "required_input_revisions->>'dependency_kind' = 'workflow'" in sql
