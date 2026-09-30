import importlib


def test_running_jobs_allow_one_distinct_queued_successor():
    migration = importlib.import_module(
        "apps.core.migrations.0223_jobs_queued_successors"
    )
    sql = migration.FORWARD_SQL

    assert "DROP INDEX operations.uq_operator_job_runs_active" in sql
    assert "CREATE UNIQUE INDEX jobs_one_queued_successor" in sql
    assert "WHERE status = 'queued'" in sql
    assert "CREATE UNIQUE INDEX jobs_one_executing_run" in sql
    assert "wait_category IS DISTINCT FROM 'workflow'" in sql
    assert "ON CONFLICT (tenant_id, job_key) WHERE status = 'queued'" in sql
    assert "AND job.status = 'queued'" in sql
    assert "broader queued Software request" in sql
    assert "SET dependent_run_id = v_active_run" in sql
    assert "dependency_rewired" in sql
