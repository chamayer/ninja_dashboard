import importlib

from shared.jobs_registry import REPLAY_SAFE_RECOVERY_EVIDENCE


def _migration():
    return importlib.import_module("apps.core.migrations.0285_software_inventory_devices")


def test_restated_inventory_evidence_matches_the_registry():
    migration = _migration()
    assert REPLAY_SAFE_RECOVERY_EVIDENCE["software-queue-drain"] == migration.DRAIN_EVIDENCE
    assert REPLAY_SAFE_RECOVERY_EVIDENCE["software-enqueue-orgs"] == migration.FLEET_EVIDENCE
    assert "'" not in migration.DRAIN_EVIDENCE + migration.FLEET_EVIDENCE


def test_table_is_tenant_scoped_and_only_ingest_writes_inventory_state():
    sql = _migration().FORWARD_SQL
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "GRANT INSERT, UPDATE, DELETE ON operations.software_inventory_devices TO ninja_ingest" in sql
    # Operations may only record a release request.
    assert "GRANT UPDATE (release_requested_at, release_requested_by)" in sql
    assert "ON DELETE CASCADE" in sql


def test_migration_follows_0284():
    assert _migration().Migration.dependencies == [("operations", "0284_rare_software_title_grain")]
