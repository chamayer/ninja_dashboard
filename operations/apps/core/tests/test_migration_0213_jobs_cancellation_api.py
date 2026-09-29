"""Static contract checks for governed Jobs cancellation."""

import importlib


def test_cancellation_is_atomic_and_running_work_is_cooperative():
    migration = importlib.import_module(
        "apps.core.migrations.0213_jobs_cancellation_api"
    )
    sql = migration.FORWARD_SQL

    assert "CREATE FUNCTION operations.jobs_cancel_v1" in sql
    assert "status = 'queued'" in sql
    assert "cancellation_requested_at = now()" in sql
    assert "TO operations_app;" in sql
