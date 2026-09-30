import importlib


def test_claims_apply_the_immutable_definition_timeout_contract():
    migration = importlib.import_module("apps.core.migrations.0230_jobs_definition_timeout_contract")
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [("operations", "0229_jobs_health_measurements")]
    assert "CREATE FUNCTION operations.jobs_claim_next_v4" in sql
    assert "operations.jobs_claim_next_v3" in sql
    assert "metadata ->> 'timeout_minutes'" in sql
    assert "NOT BETWEEN 1 AND 1440" in sql
    assert "GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v4" in sql
