import importlib


def test_admission_applies_the_immutable_definition_priority_contract():
    migration = importlib.import_module("apps.core.migrations.0231_jobs_definition_priority_contract")
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [("operations", "0230_jobs_definition_timeout_contract")]
    assert "CREATE FUNCTION operations.jobs_apply_definition_priority_v1" in sql
    assert "BEFORE INSERT ON operations.operator_job_runs" in sql
    assert "metadata ->> 'priority'" in sql
    assert "NOT BETWEEN 0 AND 100" in sql
