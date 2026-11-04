"""Check coordination at the boundary, including streamed API collection."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ingest import source_observations
from ingest.inventory import software


class BoundaryReached(Exception):
    pass


def test_source_guard_precedes_snapshot_creation(monkeypatch):
    statements = []

    @contextmanager
    def transaction():
        yield SimpleNamespace(execute=lambda sql, *args: statements.append(sql))

    def begin(*args, **kwargs):
        assert any("acquire_tenant_guard" in sql for sql in statements)
        raise BoundaryReached

    monkeypatch.setattr(source_observations.db, "transaction", transaction)
    monkeypatch.setattr(source_observations, "begin_run", begin)
    source = SimpleNamespace(
        source_key="test", source_name="Test", source_binding_id="binding"
    )
    with pytest.raises(BoundaryReached):
        source_observations.write_observations(
            source, [{}], "batch", datetime.now(timezone.utc)
        )


def test_software_fetch_finishes_before_guard_and_guard_precedes_writes(monkeypatch):
    events = []

    class Cursor:
        def execute(self, sql, *args):
            if "acquire_tenant_guard" in sql:
                events.append("guard")

        @contextmanager
        def copy(self, sql):
            yield SimpleNamespace(set_types=lambda _: None, write_row=lambda _: None)

    @contextmanager
    def transaction():
        yield Cursor()

    def batches():
        events.append("fetch")
        yield [], True
        events.append("fetch_complete")

    def lock(*args):
        assert events == ["fetch", "fetch_complete", "guard"]
        raise BoundaryReached

    monkeypatch.setattr(software.db, "transaction", transaction)
    monkeypatch.setattr(software, "_load_settings", lambda _: {})
    monkeypatch.setattr(software, "_lock_inventory_ownership", lock)
    with pytest.raises(BoundaryReached):
        software.apply(batches(), {}, listed_by="test")


def test_notification_coordination_precedes_ownership_locks(monkeypatch):
    for key in ("NINJA_BASE_URL", "NINJA_TOKEN_URL"):
        monkeypatch.setenv(key, "https://example.invalid")
    for key in (
        "NINJA_CLIENT_ID",
        "NINJA_CLIENT_SECRET",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ):
        monkeypatch.setenv(key, "synthetic-test")
    from ingest import notifications

    statements = []

    class Cursor:
        def execute(self, sql, *args):
            statements.append(sql)
            if "lock_computer_client_scopes" in sql:
                assert any(
                    "acquire_tenant_guard(%s, 'shared')" in item for item in statements
                )
                raise BoundaryReached

    @contextmanager
    def cursor():
        yield Cursor()

    @contextmanager
    def connection():
        yield SimpleNamespace(cursor=cursor)

    monkeypatch.setattr(
        notifications.db, "pool", SimpleNamespace(connection=connection)
    )
    finding = dict(
        finding_row_kind="entity",
        subject_type="device",
        subject_id="device",
        client_id="client",
    )
    with (
        pytest.raises(BoundaryReached),
        notifications._delivery_ownership_guard([finding], 1),
    ):
        pytest.fail("must coordinate before entering delivery")
