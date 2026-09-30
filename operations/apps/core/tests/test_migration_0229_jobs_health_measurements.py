import importlib


def test_jobs_health_measurements_are_governed_and_bounded():
    migration = importlib.import_module("apps.core.migrations.0229_jobs_health_measurements")
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [("operations", "0228_jobs_health_finding_policy")]
    assert "CREATE FUNCTION operations.jobs_health_measurements_v1" in sql
    assert "SECURITY DEFINER" in sql
    assert "Jobs health measurement context is invalid" in sql
    assert "GRANT EXECUTE ON FUNCTION operations.jobs_health_measurements_v1(BIGINT) TO ninja_ingest" in sql
    for measurement in (
        "schedule_failure",
        "required_disabled",
        "queue_backlog",
        "repeated_failure",
        "timeout",
        "unmet_dependency",
        "control_snapshot",
    ):
        assert measurement in sql
