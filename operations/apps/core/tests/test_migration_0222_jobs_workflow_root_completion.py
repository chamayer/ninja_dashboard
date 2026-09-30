import importlib


def test_workflow_roots_wait_without_holding_worker_resources():
    migration = importlib.import_module(
        "apps.core.migrations.0222_jobs_workflow_root_completion"
    )
    sql = migration.FORWARD_SQL

    assert "jobs_reconcile_workflow_ancestors_v1" in sql
    assert "terminal_reason = 'handler_completed'" in sql
    assert "wait_category = CASE WHEN v_coordinates THEN 'workflow'" in sql
    assert "lease_expires_at = NULL, deadline_at = NULL" in sql
    assert "state = 'released'" in sql
    assert "workflow_completed" in sql
    assert "workflow_blocked" in sql
    assert "required_child_failed" in sql
    assert "coordinator.status = 'running'" in sql
    assert "coordinator.wait_category = 'workflow'" in sql
    assert "v_iteration := v_iteration + v_changed" in sql
