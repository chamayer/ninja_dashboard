"""Static contract checks for current Jobs activity access."""

import importlib


def test_current_work_activity_is_tenant_scoped_and_read_only_for_the_app():
    migration = importlib.import_module(
        "apps.core.migrations.0242_jobs_current_work_activity"
    )

    sql = migration.FORWARD_SQL
    assert migration.Migration.dependencies == [
        ("operations", "0241_jobs_otx_replay_safe_recovery")
    ]
    assert "CREATE FUNCTION operations.jobs_activity_current_v1" in sql
    assert "job.status IN ('queued', 'running')" in sql
    assert "claim.state = 'contained'" in sql
    assert "'recovery_assessment'" in sql
    assert "GRANT EXECUTE ON FUNCTION operations.jobs_activity_current_v1" in sql
    assert "TO operations_app" in sql
    assert "GRANT SELECT ON operations.job_resource_claims" not in sql
    assert "GRANT SELECT ON operations.job_recovery_assessments" not in sql
