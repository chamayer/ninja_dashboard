"""In-memory Ninja activity feed and patched boundaries for checks 3 and 4.

The fake feed follows the documented /v2/activities contract in
ingest/activities/ingest.py: newest first, `olderThan` walks back, one
`status=` filter per call.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

# Placeholder settings, as in ingest/tests/test_jobs_worker_drain.py.
for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

from ingest.activities import ingest as activities  # noqa: E402


class FakeNinja:
    def __init__(self, records: list[dict]):
        self.records = records
        self.calls = 0

    def get(self, path, params):
        assert path == "/activities"
        self.calls += 1
        rows = sorted(self.records, key=lambda r: r["id"], reverse=True)
        if "status" in params:
            rows = [r for r in rows if r["statusCode"] == params["status"]]
        if "olderThan" in params:
            rows = [r for r in rows if r["id"] < params["olderThan"]]
        return {"activities": rows[: params["pageSize"]]}


def activity(activity_id: int, status: str, device_id: int = 5) -> dict:
    return {
        "id": activity_id,
        "statusCode": status,
        "deviceId": device_id,
        "activityTime": 1_790_000_000 + activity_id,
        "activityType": "SYSTEM",
    }


class Store:
    """Durable state the real code would write: cursor, rows, events, queue."""

    def __init__(self, last_id: int):
        self.last_id = last_id
        self.stored_ids: list[int] = []
        self.captured_event_ids: list[int] = []
        self.enqueued_devices: list[int] = []


def install(monkeypatch, store: Store, *, statuses, page_size, max_pages,
            enqueue=None):
    @contextmanager
    def transaction():
        yield SimpleNamespace()

    @contextmanager
    def run_log(_kind):
        yield {}

    def insert_ignore(_cur, _table, rows, conflict_keys):
        new = [r["id"] for r in rows if r["id"] not in store.stored_ids]
        store.stored_ids.extend(new)
        return len(new)

    def capture(_cur, rows):
        store.captured_event_ids.extend(r["id"] for r in rows)
        return {"status": "complete"}

    def set_last_id(value):
        store.last_id = value

    def default_enqueue(device_id, reason):
        store.enqueued_devices.append(device_id)
        return True

    monkeypatch.setattr(
        activities,
        "db",
        SimpleNamespace(transaction=transaction, insert_ignore=insert_ignore),
    )
    monkeypatch.setattr(activities, "run_log", run_log)
    monkeypatch.setattr(activities, "capture_ninja_events", capture)
    monkeypatch.setattr(activities, "_get_last_id", lambda: str(store.last_id))
    monkeypatch.setattr(activities, "_set_last_id", set_last_id)
    monkeypatch.setattr(activities, "_fetch_known_device_ids", lambda: {5})
    monkeypatch.setattr(activities, "_refresh_activity_summary_views", lambda: None)
    monkeypatch.setattr(activities, "enqueue_activity", enqueue or default_enqueue)
    monkeypatch.setattr(activities, "_PAGE_SIZE", page_size)
    monkeypatch.setattr(activities, "_MAX_PAGES_PER_SOURCE", max_pages)
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
        activities, "ninja_epoch_to_dt",
        lambda v: datetime.fromtimestamp(v, timezone.utc),
    )
