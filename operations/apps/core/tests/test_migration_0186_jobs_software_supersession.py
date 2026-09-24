"""Static checks for v1 Software cross-key supersession admission."""

import importlib


def test_software_supersession_allows_cross_definition_request_aliases_safely():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0186_jobs_software_supersession"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0185_jobs_claims_and_dependencies")
    ]
    assert "Expected Jobs request/run identity foreign key is unavailable" in sql
    assert "jobs_request_run_tenant_reference" in sql
    assert "FOREIGN KEY (tenant_id, run_id)" in sql
    assert "CREATE FUNCTION operations.jobs_request_software_v1" in sql
    assert "supersession_family' <> 'software-classifier'" in sql
    assert "supersession_rank" in sql


def test_software_supersession_coalesces_broader_work_and_never_stops_running_work():
    migration = importlib.import_module(
        "operations.apps.core.migrations.0186_jobs_software_supersession"
    )
    sql = migration.FORWARD_SQL

    assert "pg_advisory_xact_lock" in sql
    assert "A broader Software request already covers this request." in sql
    assert "job.status IN ('queued', 'running')" in sql
    assert "job.status = 'queued'" in sql
    assert "terminal_reason = 'superseded-before-claim'" in sql
    assert "RETURN operations.jobs_request(" in sql
    assert "GRANT EXECUTE ON FUNCTION operations.jobs_request_software_v1" in sql
