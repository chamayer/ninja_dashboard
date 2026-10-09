"""Static contract for durable schedule retirement."""

import importlib


def test_retired_tenant_schedules_are_disabled_only_through_the_restricted_api():
    migration = importlib.import_module(
        "apps.core.migrations.0274_jobs_retire_undeclared_schedules"
    )
    sql = migration.FORWARD_SQL

    assert migration.Migration.dependencies == [
        ("operations", "0273_repair_derived_projection_contracts")
    ]
    assert "CREATE FUNCTION operations.jobs_disable_retired_tenant_schedules_v1" in sql
    assert "schedule.scope_identity = 'tenant:1'" in sql
    assert "SET enabled = FALSE" in sql
    assert "TO ninja_ingest" in sql
