"""OS-installation projection: batching, id-keyed updates, and single-flight.

A recording cursor stands in for Postgres, so these assert the structure that
removed the quadratic hang (commit in batches, analyze early, no plan-sensitive
join, skip when a pass is already running), not the speed. The speed evidence
is the rolled-back experiment recorded in `.work/plan.md`.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from ingest import os_installations

EVIDENCE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
SOURCE_INSTANCE = uuid.UUID("22222222-2222-4222-8222-222222222222")
CLIENT = uuid.UUID("33333333-3333-4333-8333-333333333333")
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


def _row(i: int) -> tuple:
    return (
        SOURCE_INSTANCE, "agent", "", "", f"ext-{i}",
        uuid.uuid4(), CLIENT, NOW, NOW, uuid.uuid4(),
    )  # fmt: skip


class FakeCursor:
    def __init__(self, world: "FakeWorld") -> None:
        self.world = world
        self.statements: list[tuple[str, object]] = []
        self._last = ""

    def execute(self, query, params=None):
        text = query if isinstance(query, str) else repr(query)
        if "ANALYZE" in text and self.world.analyze_fails:
            raise RuntimeError("permission denied to analyze")
        self.statements.append((text, params))
        self._last = text

    def fetchone(self):
        if "to_regclass" in self._last:
            return (self.world.migrated,)
        if "FOR UPDATE" in self._last and "source_identities identity" in self._last:
            return self.world.identity
        return None

    def fetchall(self):
        if "JOIN operations.devices device" in self._last:
            return list(self.world.rows)
        return []


class FakeConn:
    def __init__(self, world: "FakeWorld") -> None:
        self.world = world
        self.autocommit = False

    def execute(self, query, params=None):
        self.world.lock_calls.append(query)
        acquired = self.world.lock_acquired
        return type("R", (), {"fetchone": lambda self_: (acquired,)})()


class FakeWorld:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.migrated = True
        self.identity = None
        self.lock_acquired = True
        self.analyze_fails = False
        self.transactions: list[FakeCursor] = []
        self.lock_calls: list[str] = []
        self.conn = FakeConn(self)

    @contextmanager
    def transaction(self):
        cur = FakeCursor(self)
        self.transactions.append(cur)
        yield cur

    @property
    def pool(self):
        world = self

        class _Pool:
            @contextmanager
            def connection(self):
                yield world.conn

        return _Pool()


@pytest.fixture
def world(monkeypatch):
    w = FakeWorld([_row(i) for i in range(8)])
    monkeypatch.setattr(os_installations, "db", w)
    written: list[dict] = []

    def fake_write(cur, **kwargs):
        written.append(kwargs)
        return EVIDENCE_ID

    monkeypatch.setattr(
        os_installations.relationships, "write_current_evidence", fake_write
    )
    monkeypatch.setattr(os_installations, "FIRST_BATCH_SIZE", 2)
    monkeypatch.setattr(os_installations, "BATCH_SIZE", 3)
    monkeypatch.setattr(os_installations, "ANALYZE_BATCHES", 2)
    w.written = written
    return w


def _kinds(w: FakeWorld) -> list[str]:
    kinds = []
    for cur in w.transactions:
        text = " ".join(s for s, _ in cur.statements)
        if "ANALYZE" in text:
            kinds.append("analyze")
        elif "statement_timeout = '300s'" in text:
            kinds.append("withdraw")
        elif "statement_timeout = '60s'" in text:
            kinds.append("batch")
        else:
            kinds.append("load")
    return kinds


def test_commits_in_batches_and_analyzes_early(world):
    totals = os_installations.project_all()
    assert totals["status"] == "complete"
    assert totals["relationships_written"] == 8
    # 8 rows with batches of 2, 3, 3; analyze after the first two batches only.
    assert _kinds(world) == [
        "load", "batch", "analyze", "batch", "analyze", "batch", "withdraw",
    ]  # fmt: skip
    analyze = world.transactions[2]
    assert len(analyze.statements) == 4
    joined = " ".join(s for s, _ in analyze.statements)
    for table in os_installations._STATISTICS_TABLES:
        assert table in joined


def test_each_batch_sets_tenant_and_statement_timeout(world):
    os_installations.project_all()
    batches = [
        c
        for c in world.transactions
        if "statement_timeout = '60s'" in repr(c.statements)
    ]
    assert len(batches) == 3
    for cur in batches:
        assert "set_config('operations.tenant_id'" in cur.statements[0][0]
        assert cur.statements[1][0] == "SET LOCAL statement_timeout = '60s'"


def test_updates_are_keyed_by_evidence_id_not_the_external_key(world):
    os_installations.project_all()
    updates = [
        (text, params)
        for cur in world.transactions
        for text, params in cur.statements
        if "UPDATE operations.entity_relationship_evidence_" in text
        and "SET effective_to" not in text
        and "SET active = FALSE" not in text
    ]
    assert len(updates) == 16  # current + history for each of the 8 rows
    for text, params in updates:
        assert "external_relationship_id" not in text
        assert "source_instance_id" not in text
        assert EVIDENCE_ID in params
        assert not any(
            isinstance(p, str) and p.startswith("os-installation-") for p in params
        )


def test_skips_when_another_projection_is_running(world):
    world.lock_acquired = False
    totals = os_installations.project_all()
    assert totals["status"] == "skipped_busy"
    assert world.transactions == []
    assert world.written == []
    assert not any("pg_advisory_unlock" in str(c) for c in world.lock_calls)


def test_releases_lock_and_restores_autocommit(world):
    os_installations.project_all()
    assert any("pg_try_advisory_lock" in str(c) for c in world.lock_calls)
    assert any("pg_advisory_unlock" in str(c) for c in world.lock_calls)
    assert world.conn.autocommit is False


def test_lock_is_released_when_the_projection_fails(world, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("write failed")

    monkeypatch.setattr(os_installations.relationships, "write_current_evidence", boom)
    with pytest.raises(RuntimeError, match="write failed"):
        os_installations.project_all()
    assert any("pg_advisory_unlock" in str(c) for c in world.lock_calls)
    assert world.conn.autocommit is False


def test_reports_migration_pending(world):
    world.migrated = False
    totals = os_installations.project_all()
    assert totals["status"] == "migration_pending"
    assert _kinds(world) == ["load"]
    assert world.written == []


def test_analyze_failure_does_not_fail_the_projection(world):
    world.analyze_fails = True
    totals = os_installations.project_all()
    assert totals["status"] == "complete"
    assert totals["relationships_written"] == 8


def test_client_scope_change_is_left_for_review(world):
    other_client = uuid.UUID("44444444-4444-4444-8444-444444444444")
    world.identity = (uuid.uuid4(), uuid.uuid4(), other_client)
    totals = os_installations.project_all()
    assert totals["relationships_written"] == 0
    assert world.written == []
