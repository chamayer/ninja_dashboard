"""Activity cursor safety: cap detection (PLAN-017 F02) and enqueue order (F03).

Inverted from the PLAN-017 Phase 2 reproductions (checks 3 and 4). The fake
feed follows the /v2/activities contract documented in
ingest/activities/ingest.py: newest first, `olderThan` walks back, one
`status=` filter per call.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

from ingest import runlog  # noqa: E402
from ingest.activities import ingest as activities  # noqa: E402

START = 1000


class FakeNinja:
    def __init__(self, records: list[dict]):
        self.records = records

    def get(self, path, params):
        assert path == "/activities"
        rows = sorted(self.records, key=lambda r: r["id"], reverse=True)
        if "status" in params:
            rows = [r for r in rows if r["statusCode"] == params["status"]]
        if "olderThan" in params:
            rows = [r for r in rows if r["id"] < params["olderThan"]]
        return {"activities": rows[: params["pageSize"]]}


def _activity(activity_id: int, status: str, device_id: int = 5) -> dict:
    return {
        "id": activity_id,
        "statusCode": status,
        "deviceId": device_id,
        "activityTime": 1_790_000_000 + activity_id,
        "activityType": "SYSTEM",
    }


class Store:
    def __init__(self, last_id: int):
        self.last_id = last_id
        self.events: list[str] = []
        self.enqueued_devices: list[int] = []
        self.run_stats: list[dict] = []


class Crash(RuntimeError):
    pass


def _install(monkeypatch, store: Store, *, statuses, enqueue=None):
    @contextmanager
    def transaction():
        yield SimpleNamespace()

    @contextmanager
    def run_log(_kind):
        stats: dict = {}
        yield stats
        store.run_stats.append(stats)

    def set_last_id(value):
        store.events.append("cursor")
        store.last_id = value

    def default_enqueue(device_id, reason):
        store.events.append("enqueue")
        store.enqueued_devices.append(device_id)
        return True

    monkeypatch.setattr(
        activities,
        "db",
        SimpleNamespace(
            transaction=transaction,
            insert_ignore=lambda _cur, _table, rows, conflict_keys: len(rows),
        ),
    )
    monkeypatch.setattr(activities, "run_log", run_log)
    monkeypatch.setattr(
        activities, "capture_ninja_events", lambda _cur, _rows: {"status": "complete"}
    )
    monkeypatch.setattr(activities, "_get_last_id", lambda: str(store.last_id))
    monkeypatch.setattr(activities, "_set_last_id", set_last_id)
    monkeypatch.setattr(activities, "_fetch_known_device_ids", lambda: {5})
    monkeypatch.setattr(activities, "_refresh_activity_summary_views", lambda: None)
    monkeypatch.setattr(activities, "enqueue_activity", enqueue or default_enqueue)
    monkeypatch.setattr(activities, "_PAGE_SIZE", 5)
    monkeypatch.setattr(activities, "_MAX_PAGES_PER_SOURCE", 2)
    monkeypatch.setattr(
        activities,
        "settings",
        SimpleNamespace(
            activity_types_include=list(statuses),
            activity_sources=[],
            SOFTWARE_QUEUE_ENABLED=True,
        ),
    )
    monkeypatch.setattr(
        activities,
        "ninja_epoch_to_dt",
        lambda v: datetime.fromtimestamp(v, timezone.utc),
    )


def test_cap_hit_records_the_run_as_partial(monkeypatch):
    # 20 new events, page size 5 x cap 2: only the newest 10 are reachable.
    records = [_activity(START + i, "NODE_DELETED") for i in range(1, 21)]
    store = Store(START)
    _install(monkeypatch, store, statuses=["NODE_DELETED"])

    activities.run(FakeNinja(records))

    reason = store.run_stats[-1].get("partial_reason")
    assert reason and "NODE_DELETED" in reason and "2-page limit" in reason


def test_backlog_within_cap_is_not_partial(monkeypatch):
    # The event at the cursor is what the walk stops on, as in a real feed.
    records = [_activity(START + i, "NODE_DELETED") for i in range(0, 10)]
    store = Store(START)
    _install(monkeypatch, store, statuses=["NODE_DELETED"])

    activities.run(FakeNinja(records))

    assert "partial_reason" not in store.run_stats[-1]
    assert store.last_id == START + 9


def test_software_demand_is_enqueued_before_the_cursor_advances(monkeypatch):
    records = [_activity(START + 1, "SOFTWARE_ADDED", device_id=5)]
    store = Store(START)
    _install(monkeypatch, store, statuses=["SOFTWARE_ADDED"])

    activities.run(FakeNinja(records))

    assert store.events == ["enqueue", "cursor"]
    assert store.enqueued_devices == [5]


def test_interrupted_enqueue_leaves_the_cursor_for_a_replay(monkeypatch):
    records = [_activity(START + 1, "SOFTWARE_ADDED", device_id=5)]
    store = Store(START)

    def crashing_enqueue(_device_id, reason):
        raise Crash("process stopped before the queue write")

    _install(monkeypatch, store, statuses=["SOFTWARE_ADDED"], enqueue=crashing_enqueue)
    client = FakeNinja(records)
    with pytest.raises(Crash):
        activities.run(client)
    assert store.last_id == START

    _install(monkeypatch, store, statuses=["SOFTWARE_ADDED"])
    activities.run(client)
    assert store.enqueued_devices == [5]
    assert store.last_id == START + 1


def test_run_log_records_partial_reason(monkeypatch):
    finalized: list[tuple[str, str | None]] = []

    @contextmanager
    def transaction():
        yield SimpleNamespace(execute=lambda *_a: None, fetchone=lambda: (7,))

    monkeypatch.setattr(runlog.db, "transaction", transaction)
    monkeypatch.setattr(
        runlog,
        "_finalize",
        lambda _run_id, _started, status, _stats, error=None: finalized.append(
            (status, error)
        ),
    )

    with runlog.run_log("activities") as stats:
        stats["partial_reason"] = "stopped at the page limit"
    with runlog.run_log("activities"):
        pass

    assert finalized == [("partial", "stopped at the page limit"), ("ok", None)]
