"""Static safety checks for durable schedule activation."""

import importlib


def test_durable_schedule_runtime_is_ingest_only_and_never_starts_overdue_work():
    migration = importlib.import_module(
        "apps.core.migrations.0212_jobs_durable_schedule_runtime"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [("operations", "0211_fix_jobs_claim_v3_ambiguity")]
    assert "CREATE FUNCTION operations.jobs_reconcile_schedule_v2" in sql
    assert "CREATE FUNCTION operations.jobs_list_due_schedules_v1" in sql
    assert "now() + make_interval" in sql
    assert "TO ninja_ingest;" in sql
