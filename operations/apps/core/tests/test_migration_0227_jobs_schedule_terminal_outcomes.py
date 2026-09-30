import importlib


def test_terminal_job_states_update_only_their_own_schedule_outcome():
    migration = importlib.import_module(
        "apps.core.migrations.0227_jobs_schedule_terminal_outcomes"
    )
    sql = migration.FORWARD_SQL

    assert "jobs_record_schedule_terminal_outcome_v1" in sql
    assert "AFTER UPDATE OF status ON operations.operator_job_runs" in sql
    assert "schedule.last_run_id = NEW.id" in sql
    assert "NEW.status NOT IN ('completed', 'failed', 'stalled', 'cancelled')" in sql
    assert "SET last_outcome = NEW.status" in sql
    assert "schedule.last_run_id = run.id" in sql
    assert "SECURITY DEFINER" in sql
    assert "REVOKE ALL ON FUNCTION" in sql
