import importlib


def test_jobs_runtime_health_and_admin_diagnostics_are_governed():
    migration = importlib.import_module(
        "apps.core.migrations.0226_jobs_runtime_diagnostics"
    )
    sql = migration.FORWARD_SQL

    assert "CREATE TABLE operations.job_runtime_heartbeats" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "jobs_runtime_heartbeat_v1" in sql
    assert "jobs_runtime_stop_v1" in sql
    assert "jobs_admin_diagnostics_v1" in sql
    assert "p_limit NOT BETWEEN 1 AND 100" in sql
    assert "p_offset NOT BETWEEN 0 AND 1000000" in sql
    for section in (
        "definition_versions",
        "schedules",
        "schedule_events",
        "requests",
        "runs",
        "events",
        "dependencies",
        "domain_attempts",
        "lane_limits",
        "resource_limits",
        "resource_claims",
    ):
        assert f"p_section = '{section}'" in sql
    assert "TO operations_app" in sql
    assert "TO ninja_ingest" in sql
    assert "GRANT SELECT ON operations.job_runtime_heartbeats" not in sql
    assert "input_revisions, output_revisions, request_payload" in sql
    assert "input_revisions, output_revisions, requested_input" not in sql


def test_current_jobs_lifecycle_is_derived_without_duplicate_storage():
    migration = importlib.import_module("apps.core.migrations.0259_jobs_current_lifecycle")
    sql = migration.FORWARD_SQL
    assert "jobs_current_lifecycle_v1" in sql
    assert "wait_category" in sql
    assert "waiting_for_capacity" in sql
    assert "waiting_for_protected_update" in sql
    assert "ready_runs" in sql
    assert "waiting_runs" in sql
    assert "'queued_runs'" not in sql
    assert "CREATE TABLE" not in sql
