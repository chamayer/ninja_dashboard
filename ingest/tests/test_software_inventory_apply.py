"""The rebuilt software inventory: completeness, holds, and set-based apply."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ingest.inventory import queue, software
from shared import software_settings

CFG = software_settings.effective({})


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def get(self, path, query):
        self.queries.append((path, dict(query)))
        return self.responses.pop(0)


def _page(results, offset, total, name="c"):
    return {"results": results, "cursor": {"name": name, "offset": offset, "count": total}}


# ── Completeness ──────────────────────────────────────────────────


def test_paging_to_the_reported_total_is_complete():
    client = _Client([_page([{}] * 2, 0, 3), _page([{}], 2, 3)])
    flags = [complete for _rows, complete in software.pages(client)]
    assert flags == [False, True]
    assert client.queries[0][1]["pageSize"] == software.PAGE_SIZE
    assert client.queries[1][1]["cursor"] == "c"


def test_a_stalled_cursor_is_reported_incomplete():
    client = _Client([_page([{}], 0, 10), _page([{}], 1, 10), _page([{}], 1, 10)])
    flags = [complete for _rows, complete in software.pages(client)]
    assert flags[-1] is False


def test_an_empty_page_before_the_total_is_incomplete():
    client = _Client([_page([{}], 0, 5), _page([], 1, 5)])
    assert [complete for _rows, complete in software.pages(client)][-1] is False


def test_device_filter_is_numeric_only():
    assert software.device_filter([1, "22"]) == "id in (1,22)"


# ── Streaming ──────────────────────────────────────────────────────


def test_rows_resolve_to_devices_and_collection_time_is_the_newest():
    device, client = uuid.uuid4(), uuid.uuid4()
    batches = [([
        {"deviceId": 1, "name": "A", "timestamp": 100},
        {"deviceId": 1, "name": "B", "timestamp": 300},
        {"deviceId": 2, "name": "C"},
        {"deviceId": 1, "name": ""},
    ], True)]
    collected, stream = {}, software._Stream()
    rows = list(software.stream_rows(batches, {"1": (device, client)}, collected, stream))
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (1, client, device, "a"), (2, client, device, "b"),
    ]
    assert len(rows[0]) == len(software.LISTING_COLUMNS)
    assert collected[device] == datetime.fromtimestamp(300, tz=UTC)
    assert (stream.seen, stream.unresolved, stream.complete) == (4, 1, True)


# ── Removal guard ──────────────────────────────────────────────────


def test_a_first_list_is_never_held():
    assert software.hold_reason(None, 0, CFG) == ""


def test_a_sharp_shrink_holds_removals():
    reason = software.hold_reason({"listed_count": 120}, 40, CFG)
    assert "previous list had 120" in reason


def test_ordinary_change_and_small_lists_are_not_held():
    assert software.hold_reason({"listed_count": 120}, 100, CFG) == ""
    assert software.hold_reason({"listed_count": 10}, 1, CFG) == ""


def test_a_release_after_the_hold_lets_the_list_apply():
    held = datetime(2026, 10, 1, tzinfo=UTC)
    released = datetime(2026, 10, 2, tzinfo=UTC)
    previous = {"listed_count": 120, "held_at": held, "release_requested_at": released}
    assert software.hold_reason(previous, 10, CFG) == ""
    stale_release = {**previous, "release_requested_at": datetime(2026, 9, 1, tzinfo=UTC)}
    assert software.hold_reason(stale_release, 10, CFG) != ""


def test_removals_need_a_complete_response_and_no_hold():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    counts = [(a, 100, 100, None, None), (b, 5, 100, None, None), (c, 3, None, None, None)]
    assert [(d[0], d[2]) for d in software.device_decisions(counts, True, CFG)] == [
        (a, True), (b, False), (c, True),
    ]
    assert not any(d[2] for d in software.device_decisions(counts, False, CFG))


# ── Apply statements ───────────────────────────────────────────────


def test_removal_is_limited_to_listed_devices_and_records_why():
    sql = software.REMOVE_SQL
    assert "FROM inventory_devices d" in sql and "d.removals_allowed" in sql
    assert "NOT EXISTS" in sql and "l.client_id = c.client_id" in sql
    assert "stale_reason = %(reason)s" in sql and "effective_to = %(at)s" in sql
    assert software.REMOVED_REASON == "ninja.inventory.not_listed"


def test_stored_rows_are_read_by_computer_not_by_client_and_title():
    """The direct join used the (client, title) index: 4.3 s per 100 computers."""
    sql = software.DELTA_SQL
    assert "WITH stored AS MATERIALIZED" in sql
    assert "c.device_id IN (SELECT device_id FROM inventory_devices)" in sql
    assert "LEFT JOIN operations.software_installations_current" not in sql


def test_unchanged_rows_only_refresh_their_open_interval():
    assert "d.kind = 'unchanged'" in software.HISTORY_SQL
    assert "WHERE d.kind <> 'unchanged'" in software.OPEN_INTERVALS_SQL
    # Reappearing after removal counts as changed and opens a new interval.
    assert "OR c.stale_since IS NOT NULL THEN 'changed'" in software.DELTA_SQL


def test_a_held_device_keeps_its_confirmed_count():
    sql = software.DEVICES_SQL
    assert "ELSE s.listed_count END" in sql
    assert "COALESCE(s.held_at, EXCLUDED.held_at)" in sql


def test_duplicate_rows_keep_the_last_one():
    assert "DISTINCT ON (device_id, canonical_name)" in software.LISTING_SQL
    assert "seq DESC" in software.LISTING_SQL


# ── Device worker ──────────────────────────────────────────────────


def test_the_worker_fetches_batches_and_retries_failed_ones(monkeypatch):
    entries = [queue.Entry(i, f"id={i}", 0, 3) for i in range(1, 151)]
    entries.append(queue.Entry(999, "org=1", 0, 3))
    finished, requested = [], []
    monkeypatch.setattr(queue, "recover_stale_entries", lambda: 0)
    monkeypatch.setattr(queue, "claim", lambda run: entries)
    monkeypatch.setattr(queue, "_finish", lambda batch, error="": finished.append(
        ([e.id for e in batch], error)) or (len(batch) if error else 0))
    monkeypatch.setattr(software, "load_device_map", lambda: {})

    def _refresh(client, ids, device_map):
        requested.append(len(ids))
        if len(requested) == 2:
            raise RuntimeError("ninja down")
        return software.ApplyResult(devices=len(ids), new=1)

    monkeypatch.setattr(software, "device_refresh", _refresh)
    outcome = queue.drain(object(), "run-1")

    assert requested == [100, 50]
    assert outcome.entries == 151
    assert outcome.failed == 51  # the unusable entry and the failed batch
    assert outcome.material_changed
    assert finished[0] == ([999], "Not a single-computer request (expected id=<number>).")
    assert finished[-1] == (list(range(101, 151)), "ninja down")


def test_an_unchanged_inventory_is_not_a_material_change():
    assert not software.ApplyResult(unchanged=500).material_changed
    assert software.ApplyResult(removed=1).material_changed
    assert software.ApplyResult(relinked=1).material_changed


def test_a_version_change_clears_the_catalog_link_for_relinking():
    sql = software.RELINK_SQL
    assert "SET software_version_id = NULL" in sql
    assert "v.version IS DISTINCT FROM COALESCE(c.version, '')" in sql
    # Limited to the computers in this response.
    assert "c.device_id IN (SELECT device_id FROM inventory_devices)" in sql
    # The catalog backfill links exactly the unlinked rows, by the same rule.
    from ingest import software_catalog

    assert "install.software_version_id IS NULL" in software_catalog._BACKFILL_LINKS
    assert "version.version = COALESCE(install.version, '')" in software_catalog._BACKFILL_LINKS


# ── Progress and summaries ─────────────────────────────────────────


def test_paging_reports_rows_received_against_ninjas_total():
    seen = []
    client = _Client([_page([{}] * 2, 0, 3), _page([{}], 2, 3)])
    list(software.pages(client, on_page=lambda received, total: seen.append((received, total))))
    assert seen == [(2, 3), (3, 3)]


def test_the_worker_counts_computers_handled(monkeypatch):
    entries = [queue.Entry(i, f"id={i}", 0, 3) for i in range(1, 251)]
    counts = []
    monkeypatch.setattr(queue, "recover_stale_entries", lambda: 0)
    monkeypatch.setattr(queue, "claim", lambda run: entries)
    monkeypatch.setattr(queue, "_finish", lambda batch, error="": 0)
    monkeypatch.setattr(software, "load_device_map", lambda: {})
    monkeypatch.setattr(software, "device_refresh",
                        lambda client, ids, device_map: software.ApplyResult(devices=len(ids)))
    queue.drain(object(), "run-1", lambda done, total, unit: counts.append((done, total, unit)))
    assert counts == [(0, 250, "computers"), (100, 250, "computers"), (200, 250, "computers"),
                      (250, 250, "computers")]


def test_a_run_describes_itself_in_plain_english():
    text = software.ApplyResult(devices=4629, new=15695, changed=33023, removed=21779,
                                unchanged=516359, relinked=166310).describe("Full check")
    assert text.startswith("Full check: 4,629 computers refreshed.")
    assert "21,779 removed" in text and "166,310 version links corrected" in text
    assert software.ApplyResult().describe("Changed computers") == (
        "Changed computers: no computer reported a software list."
    )
    assert "removals" not in software.ApplyResult(devices=1).describe("x")
    assert "nothing was removed" in software.ApplyResult(devices=1, complete=False).describe("x")


def test_every_inventory_change_names_its_title_in_the_change_feed():
    for sql in (software.REMOVE_SQL, software.RELINK_SQL, software.CHANGED_TITLES_SQL):
        assert "INSERT INTO operations.software_reclassification_targets" in sql
        assert "'inventory'" in sql
        # A coalesced change bumps the generation so an earlier capture
        # cannot acknowledge it (PLAN-017 U04).
        assert "DO UPDATE SET generation = target.generation + 1" in sql
    assert "kind <> 'unchanged'" in software.CHANGED_TITLES_SQL


def test_freshness_reads_as_a_sentence():
    stats = {"collected_within_24h": 69, "collected_1_to_7_days": 10, "collected_over_7_days": 21,
             "collected_unknown": 0, "computers_not_reporting": 156}
    text = software.describe_freshness(stats)
    assert text.startswith("Ninja had collected 69% of these lists within 24 hours; 21 were over")
    assert "156 computers with installed software sent no list" in text
    assert software.describe_freshness({**stats, "collected_within_24h": 0, "collected_1_to_7_days": 0,
                                        "collected_over_7_days": 0}) == ""


def test_an_empty_last_page_without_a_cursor_keeps_the_reported_total():
    """Ninja's final page can be empty with no cursor; the earlier total decides."""
    seen = []
    complete = _Client([_page([{}] * 2, 0, 3), _page([{}], 2, 4), {"results": []}])
    flags = [done for _rows, done in software.pages(
        complete, on_page=lambda received, total: seen.append((received, total)))]
    assert flags[-1] is False  # 3 received of 4 reported: incomplete
    assert seen[-1] == (3, 4)
    short = _Client([_page([{}] * 2, 0, 9), {"results": []}])
    assert [done for _rows, done in software.pages(short)][-1] is False
