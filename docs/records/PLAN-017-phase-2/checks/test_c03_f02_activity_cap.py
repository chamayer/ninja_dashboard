"""Check 3 — F02: a page-capped status filter loses IDs behind the shared cursor."""

from __future__ import annotations

import logging

from activity_harness import FakeNinja, Store, activity, install
from ingest.activities import ingest as activities

START = 1000


def _run_until_quiet(client, runs=5):
    for _ in range(runs):
        activities.run(client)


def test_reproduces_single_filter_cap_skips_older_backlog(monkeypatch, caplog):
    # 20 new events for one filter; page size 5 x cap 2 drains only 10 per run.
    # NODE_DELETED is always added to the allowlist, so it is the filter here.
    records = [activity(START + i, "NODE_DELETED") for i in range(1, 21)]
    store = Store(START)
    install(monkeypatch, store, statuses=["NODE_DELETED"], page_size=5, max_pages=2)

    with caplog.at_level(logging.WARNING):
        _run_until_quiet(FakeNinja(records))

    eligible = set(range(START + 1, START + 21))
    assert store.last_id == START + 20
    assert set(store.stored_ids) == set(range(START + 11, START + 21))
    assert eligible - set(store.stored_ids) == set(range(START + 1, START + 11))
    # The cap is only a log warning; nothing durable records the lost frontier.
    assert any("page cap" in m for m in caplog.messages)


def test_reproduces_capped_filter_loses_ids_when_another_filter_drains(monkeypatch):
    # Filter A has a 20-event backlog; filter B has 3 newer events and drains.
    backlog = [activity(START + i, "A_EVENT") for i in range(1, 21)]
    newer = [activity(START + 100 + i, "B_EVENT") for i in range(1, 4)]
    store = Store(START)
    install(
        monkeypatch, store, statuses=["A_EVENT", "B_EVENT"], page_size=5, max_pages=2
    )

    _run_until_quiet(FakeNinja(backlog + newer))

    lost = {r["id"] for r in backlog} - set(store.stored_ids)
    assert store.last_id == START + 103
    assert lost == set(range(START + 1, START + 11))
    # Every processed ID was processed once: no repeats for this scenario, so
    # no duplicate stored rows, captured events or enqueues to check.
    assert len(store.stored_ids) == len(set(store.stored_ids))
    assert len(store.captured_event_ids) == len(set(store.captured_event_ids))


def test_control_backlog_within_cap_is_fully_processed(monkeypatch):
    records = [activity(START + i, "NODE_DELETED") for i in range(1, 10)]
    store = Store(START)
    install(monkeypatch, store, statuses=["NODE_DELETED"], page_size=5, max_pages=2)

    _run_until_quiet(FakeNinja(records))

    assert sorted(store.stored_ids) == list(range(START + 1, START + 10))
    assert store.last_id == START + 9
