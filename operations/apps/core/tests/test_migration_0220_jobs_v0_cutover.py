import importlib


def test_v0_cutover_is_terminal_truthful_and_preserves_history():
    migration = importlib.import_module("apps.core.migrations.0220_jobs_v0_cutover")
    sql = migration.FORWARD_SQL

    assert "contract_version = 0" in sql
    assert "status IN ('queued', 'running')" in sql
    assert "legacy_cutover_cancelled" in sql
    assert "legacy_cutover_interrupted" in sql
    assert "INSERT INTO operations.operator_job_events" in sql
    assert "DELETE" not in sql
