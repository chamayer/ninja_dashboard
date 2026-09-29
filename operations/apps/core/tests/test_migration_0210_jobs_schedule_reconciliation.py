"""Static contract checks for durable Jobs schedule reconciliation."""

import importlib


def test_schedule_reconciliation_is_restricted_and_idempotent():
    migration = importlib.import_module(
        "apps.core.migrations.0210_jobs_schedule_reconciliation_api"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [("operations", "0209_jobs_v1_progress_api")]
    assert "CREATE FUNCTION operations.jobs_reconcile_schedule_v1" in sql
    assert "ON CONFLICT (tenant_id, definition_key, scope_identity) DO UPDATE" in sql
    assert "Jobs definition snapshot is not registered" in sql
    assert "TO ninja_ingest;" in sql
