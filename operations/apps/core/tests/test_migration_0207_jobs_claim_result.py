"""Static contract checks for the claimed-run result API."""

import importlib


def test_claim_result_api_returns_run_and_fence_without_caller_lookup():
    migration = importlib.import_module(
        "apps.core.migrations.0207_jobs_claim_result_api"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0206_effective_client_mapping_decision_permissions")
    ]
    assert "CREATE FUNCTION operations.jobs_claim_next_v2" in sql
    assert "RETURNS TABLE (run_id UUID, claim_token UUID)" in sql
    assert "operations.jobs_claim_next_v1" in sql
    assert "job.claim_token = v_claim_token" in sql
    assert "job.worker_incarnation = p_worker_incarnation" in sql
    assert "GRANT EXECUTE ON FUNCTION operations.jobs_claim_next_v2" in sql
