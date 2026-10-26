"""Check 4 — F03: the activity cursor advances before durable software demand."""

from __future__ import annotations

import pytest

from activity_harness import FakeNinja, Store, activity, install
from ingest.activities import ingest as activities

START = 1000


class Crash(RuntimeError):
    pass


def test_reproduces_interrupted_enqueue_leaves_no_demand_after_replay(monkeypatch):
    records = [activity(START + 1, "SOFTWARE_ADDED", device_id=5)]
    store = Store(START)

    def crashing_enqueue(_device_id, reason):
        raise Crash("process stopped before the queue write")

    install(
        monkeypatch, store, statuses=["SOFTWARE_ADDED"], page_size=5, max_pages=2,
        enqueue=crashing_enqueue,
    )
    client = FakeNinja(records)
    with pytest.raises(Crash):
        activities.run(client)

    # Cursor and event capture committed before the enqueue was attempted.
    assert store.last_id == START + 1
    assert store.captured_event_ids == [START + 1]
    assert store.enqueued_devices == []

    # Replay with a healthy queue: the event is at the cursor and is skipped.
    install(monkeypatch, store, statuses=["SOFTWARE_ADDED"], page_size=5, max_pages=2)
    activities.run(client)
    assert store.enqueued_devices == []
    # The software event is not stored as an activity row (by design).
    assert store.stored_ids == []


def test_control_uninterrupted_run_enqueues_once(monkeypatch):
    records = [activity(START + 1, "SOFTWARE_ADDED", device_id=5)]
    store = Store(START)
    install(monkeypatch, store, statuses=["SOFTWARE_ADDED"], page_size=5, max_pages=2)
    client = FakeNinja(records)

    activities.run(client)
    activities.run(client)

    assert store.enqueued_devices == [5]
    assert store.last_id == START + 1
