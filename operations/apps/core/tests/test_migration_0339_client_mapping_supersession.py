import importlib

migration = importlib.import_module("apps.core.migrations.0339_defer_client_mapping_supersession")


def test_supersession_reference_is_checked_at_commit_and_reversible():
    forward = " ".join(migration.FORWARD_SQL.split())
    reverse = " ".join(migration.REVERSE_SQL.split())
    constraint = "client_source_mapping_decisions_superseded_by_id_fkey"
    assert f"ALTER CONSTRAINT {constraint} DEFERRABLE INITIALLY DEFERRED" in forward
    assert f"ALTER CONSTRAINT {constraint} NOT DEFERRABLE" in reverse
    assert migration.Migration.dependencies == [("operations", "0338_ruon_process_monitors")]
