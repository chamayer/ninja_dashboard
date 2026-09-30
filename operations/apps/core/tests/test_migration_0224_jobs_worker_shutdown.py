import importlib


def test_worker_interruption_is_fenced_and_resources_stay_contained():
    migration = importlib.import_module(
        "apps.core.migrations.0224_jobs_worker_shutdown"
    )
    sql = migration.FORWARD_SQL

    assert "jobs_interrupt_v1" in sql
    assert "terminal_reason = 'worker_interrupted'" in sql
    assert "claim_token = p_claim_token" in sql
    assert "state = 'contained'" in sql
    assert "manual verification required" in sql
    assert "jobs_propagate_dependency_terminal_v1" in sql
    assert "GRANT EXECUTE" in sql
