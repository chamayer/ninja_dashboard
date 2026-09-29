"""Static contract checks for the restricted v1 worker APIs."""

import importlib


def test_v1_worker_api_returns_identity_and_finishes_fenced_claims():
    migration = importlib.import_module("apps.core.migrations.0208_jobs_v1_worker_api")
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [("operations", "0207_jobs_claim_result_api")]
    assert "CREATE FUNCTION operations.jobs_claim_next_v3" in sql
    assert "RETURNS TABLE (run_id UUID, claim_token UUID, job_key TEXT)" in sql
    assert "SET attempts = attempts + 1" in sql
    assert "CREATE FUNCTION operations.jobs_finish_v1" in sql
    assert "contract_version = 1 AND status = 'running' AND claim_token = p_claim_token" in sql
    assert "UPDATE operations.job_resource_claims" in sql
    assert "state = 'released'" in sql
    assert "TO ninja_ingest;" in sql
