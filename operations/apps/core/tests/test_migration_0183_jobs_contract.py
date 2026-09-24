"""Static contract checks for the intentionally inert Jobs preparation migration."""

import importlib


def test_jobs_contract_preparation_is_additive_and_inert():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0183_jobs_contract_preparation"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0182_software_job_lane_and_operations_controls")
    ]
    assert "CREATE TABLE operations.job_definition_versions" in sql
    assert "CREATE TABLE operations.job_requests" in sql
    assert "CREATE TABLE operations.job_schedules" in sql
    assert "CREATE TABLE operations.job_schedule_events" in sql
    assert "jobs_contract_preparation_only CHECK (contract_version = 0)" in sql
    assert "jobs_schedule_preparation_only CHECK (NOT enabled)" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON operations.%I" in sql
    assert "GRANT " not in sql
    assert "DROP TABLE" not in sql


def test_jobs_contract_preparation_enforces_same_tenant_references_and_history():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0183_jobs_contract_preparation"
    )
    sql = migration.FORWARD_SQL

    assert "jobs_requester_tenant_reference" in sql
    assert "jobs_canceller_tenant_reference" in sql
    assert "jobs_parent_reference" in sql
    assert "jobs_root_reference" in sql
    assert "jobs_retry_reference" in sql
    assert "jobs_identity_reference_unique" in sql
    assert "immutable_job_definitions" in sql
    assert "immutable_job_requests" in sql
    assert "immutable_job_schedule_events" in sql
