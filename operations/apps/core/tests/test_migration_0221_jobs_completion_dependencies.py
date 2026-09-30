import importlib


def test_completion_dependencies_release_or_block_descendants():
    migration = importlib.import_module(
        "apps.core.migrations.0221_jobs_completion_dependencies"
    )
    sql = migration.FORWARD_SQL

    assert "jobs_add_completion_dependency_v1" in sql
    assert "jobs_propagate_dependency_terminal_v1" in sql
    assert "WITH RECURSIVE blocked" in sql
    assert "terminal_reason = 'prerequisite_failed'" in sql
    assert "dependency_released" in sql
    assert "dependency_blocked" in sql
    assert "PERFORM operations.jobs_propagate_dependency_terminal_v1" in sql
    assert "CREATE OR REPLACE FUNCTION operations.jobs_contain_expired_v1" in sql
    assert "CREATE OR REPLACE FUNCTION operations.jobs_cancel_v1" in sql
