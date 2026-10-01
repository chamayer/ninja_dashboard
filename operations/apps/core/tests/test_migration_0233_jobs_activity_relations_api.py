import importlib


def test_activity_relations_use_a_bounded_tenant_scoped_api():
    migration = importlib.import_module(
        "apps.core.migrations.0233_jobs_activity_relations_api"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0232_jobs_claim_recovery_and_fairness")
    ]
    assert "CREATE FUNCTION operations.jobs_activity_relations_v1" in sql
    assert "cardinality(p_run_ids) NOT BETWEEN 1 AND 100" in sql
    assert "operations.job_dependencies" in sql
    assert "operations.job_domain_attempts" in sql
    assert "operations.job_resource_claims" in sql
    assert "TO operations_app" in sql
