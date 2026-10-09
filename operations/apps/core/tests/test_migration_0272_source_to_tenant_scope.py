import importlib


def test_declared_source_to_tenant_transition_is_allowed_but_other_cross_scope_edges_are_not():
    migration = importlib.import_module(
        "apps.core.migrations.0272_source_to_tenant_workflow_scope"
    )
    sql = migration.FORWARD_SQL

    assert "edge.contract->>'scope_mode' IN ('inherit', 'tenant')" in sql
    assert "v_prerequisite_scope IS DISTINCT FROM p_scope_identity" in sql
    assert "p_scope_identity IS DISTINCT FROM ('tenant:' || p_tenant_id::text)" in sql
    assert "v_dependent_scope IS DISTINCT FROM p_scope_identity" in sql
