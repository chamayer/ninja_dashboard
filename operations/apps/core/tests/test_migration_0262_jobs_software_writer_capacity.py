from importlib import import_module


def test_software_writer_capacity_policy_seeds_the_derived_findings_lock():
    migration = import_module("apps.core.migrations.0262_jobs_software_writer_capacity")

    assert migration.Migration.dependencies == [("operations", "0261_jobs_wait_reason_truth")]
    assert "tenant:{tenant_id}:software-findings" in migration.FORWARD_SQL
    assert "'capacity:processing'" in migration.FORWARD_SQL
    assert "SET capacity = 2" in migration.FORWARD_SQL
    assert "SET capacity = 5" in migration.FORWARD_SQL
