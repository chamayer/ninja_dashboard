"""Static contract checks for fenced cooperative cancellation."""

import importlib


def test_worker_cancellation_is_fenced_and_releases_only_held_claims():
    migration = importlib.import_module(
        "apps.core.migrations.0217_jobs_cooperative_cancellation"
    )
    sql = migration.FORWARD_SQL

    assert "CREATE FUNCTION operations.jobs_should_cancel_v1" in sql
    assert "CREATE FUNCTION operations.jobs_finish_cancelled_v1" in sql
    assert "status = 'running' AND claim_token = p_claim_token" in sql
    assert "cancellation_requested_at IS NOT NULL" in sql
    assert "AND state = 'held'" in sql
    assert "TO ninja_ingest;" in sql
