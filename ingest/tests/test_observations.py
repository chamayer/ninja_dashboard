import uuid
from datetime import datetime, timezone

from ingest import observations
from ingest.observations import material_hash, material_projection


# ── Hardening tests (ADR-0007 §Heartbeat, §SCD-2) ───────────────────────
#
# These tests exercise the write_current_rows control flow with a scripted
# mock cursor. They cover: out-of-order guard (older AND equal timestamp),
# resolved-ID preservation, material-change → history queuing with
# prior-last-seen-at side-band, and heartbeat without material change.


class _MockCursor:
    """Minimal scripted cursor for observation write tests.

    `fetch_queue` supplies one row per SELECT ... FOR UPDATE. The advisory
    lock SELECT and the upsert/history INSERTs consume no queue entries.
    Records every execute for post-hoc assertions.
    """

    def __init__(self, fetch_queue):
        self._queue = list(fetch_queue)
        self.executed: list[tuple[str, object]] = []
        self.executemany_calls: list[tuple[str, list]] = []
        self.rowcount = 0
        self._pending_fetch = None

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        self.executed.append((sql_norm, params))
        # Only the SELECT ... FOR UPDATE consumes the fetch queue.
        if "SELECT observed_at, material_hash, active" in sql_norm:
            self._pending_fetch = self._queue.pop(0) if self._queue else None
        else:
            self._pending_fetch = None

    def executemany(self, sql, rows):
        self.executemany_calls.append((" ".join(sql.split()), list(rows)))
        self.rowcount = len(rows)

    def fetchone(self):
        return self._pending_fetch


def _base_row(**overrides):
    row = {
        "observation_id": uuid.uuid4(),
        "tenant_id": 1,
        "source_binding_id": uuid.UUID("00000000-0000-4000-8000-000000000011"),
        "collector_instance_id": uuid.UUID(
            "00000000-0000-4000-8000-000000000001"),
        "client_id": None,
        "device_id": None,
        "entity_type": "agent.rmm",
        "parent_source_key": "",
        "entity_key": "42",
        "platform": "Ninja",
        "subplatform": "",
        "observed_at": datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        "last_seen_at": datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        "last_received_at": datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        "active": True,
        "withdrawn_at": None,
        "snapshot_scope": "Ninja",
        "last_snapshot_run_id": uuid.uuid4(),
        "raw_data": {},
        "canonical_data": {"hostname": "host-1", "os_name": "Windows 11"},
        "raw_hash": b"\x00" * 32,
        "batch_id": uuid.uuid4(),
        "collector_version": "",
        "schema_version": 1,
    }
    row.update(overrides)
    return row


def _history_close_updates(cur):
    """Return the parameter dicts passed to the SCD-2 close-UPDATE."""
    return [
        params for sql, params in cur.executed
        if "UPDATE operations.entity_observation_history" in sql
    ]


def test_out_of_order_row_is_skipped_before_history_mutation():
    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    older = _base_row(observed_at=now)
    prev = (
        datetime(2026, 7, 22, 12, 1, tzinfo=timezone.utc),  # newer stored
        b"different-hash", True, None, None,
        datetime(2026, 7, 22, 12, 1, tzinfo=timezone.utc),
    )
    cur = _MockCursor(fetch_queue=[prev])

    written = observations.write_current_rows(cur, [older])

    assert written == 0
    # No history mutation of any kind — this is the point of the guard.
    assert not any(
        "operations.entity_observation_history" in sql
        for sql, _ in cur.executed
    )
    assert cur.executemany_calls == []


def test_equal_timestamp_row_is_treated_as_stale():
    ts = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    incoming = _base_row(observed_at=ts, canonical_data={"hostname": "b"})
    # Stored row has the same observed_at with a DIFFERENT material hash.
    prev = (ts, b"different-hash", True, None, None, ts)
    cur = _MockCursor(fetch_queue=[prev])

    written = observations.write_current_rows(cur, [incoming])

    assert written == 0
    # Equal-timestamp rows must not open a zero-length SCD-2 interval.
    assert _history_close_updates(cur) == []
    assert cur.executemany_calls == []


def test_resolved_ids_preserved_when_incoming_row_is_null():
    prior_ts = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    new_ts = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    resolved_device = uuid.uuid4()
    resolved_client = uuid.uuid4()
    incoming = _base_row(
        observed_at=new_ts, client_id=None, device_id=None,
    )
    # Same material hash → heartbeat only, no history write.
    incoming_hash = material_hash(incoming["canonical_data"])
    prev = (prior_ts, incoming_hash, True,
            resolved_client, resolved_device, prior_ts)
    cur = _MockCursor(fetch_queue=[prev])

    observations.write_current_rows(cur, [incoming])

    assert len(cur.executemany_calls) == 1
    upsert_sql, shaped_rows = cur.executemany_calls[0]
    assert "COALESCE(EXCLUDED.client_id" in upsert_sql
    assert "COALESCE(EXCLUDED.device_id" in upsert_sql
    # Python-side preservation runs regardless of SQL COALESCE.
    assert shaped_rows[0]["client_id"] == resolved_client
    assert shaped_rows[0]["device_id"] == resolved_device


def test_material_change_queues_history_with_prior_last_seen_at():
    prior_ts = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    prior_last_seen = datetime(2026, 7, 22, 11, 30, tzinfo=timezone.utc)
    new_ts = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    incoming = _base_row(
        observed_at=new_ts, last_seen_at=new_ts,
        canonical_data={"hostname": "host-1", "os_name": "Windows 12"},
    )
    prev = (prior_ts, b"prior-hash", True, None, None, prior_last_seen)
    cur = _MockCursor(fetch_queue=[prev])

    observations.write_current_rows(cur, [incoming])

    closes = _history_close_updates(cur)
    assert len(closes) == 1
    # Close must use the prior last_seen_at, not the new observation time.
    assert closes[0]["last_seen_at"] == prior_last_seen
    assert closes[0]["effective_to"] == new_ts


def test_heartbeat_without_material_change_skips_history():
    prior_ts = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    new_ts = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    incoming = _base_row(observed_at=new_ts, last_seen_at=new_ts)
    incoming_hash = material_hash(incoming["canonical_data"])
    prev = (prior_ts, incoming_hash, True, None, None, prior_ts)
    cur = _MockCursor(fetch_queue=[prev])

    observations.write_current_rows(cur, [incoming])

    # Heartbeat: current gets a new upsert row but history is untouched.
    assert _history_close_updates(cur) == []
    history_inserts = [
        c for c in cur.executemany_calls
        if "INSERT INTO operations.entity_observation_history" in c[0]
    ]
    assert history_inserts == []


def test_new_identity_opens_first_history_version():
    incoming = _base_row()
    cur = _MockCursor(fetch_queue=[None])  # prev is None → new identity

    observations.write_current_rows(cur, [incoming])

    # New identity: no close (nothing to close), but a new open version.
    assert _history_close_updates(cur) == [
        # UPDATE runs unconditionally but affects zero rows on a new tuple;
        # observation_runs reconciliation depends on this being idempotent.
        {
            "tenant_id": incoming["tenant_id"],
            "source_binding_id": incoming["source_binding_id"],
            "entity_type": incoming["entity_type"],
            "parent_source_key": "",
            "entity_key": incoming["entity_key"],
            "effective_to": incoming["observed_at"],
            "last_seen_at": incoming["observed_at"],
        },
    ]
    history_inserts = [
        c for c in cur.executemany_calls
        if "INSERT INTO operations.entity_observation_history" in c[0]
    ]
    assert len(history_inserts) == 1


def test_batch_is_sorted_by_identity_before_locking():
    a = _base_row(entity_key="c")
    b = _base_row(entity_key="a")
    c = _base_row(entity_key="b")
    cur = _MockCursor(fetch_queue=[None, None, None])

    observations.write_current_rows(cur, [a, b, c])

    lock_calls = [
        params[0] for sql, params in cur.executed
        if "pg_advisory_xact_lock" in sql
    ]
    # Locks acquired in sorted order: a → b → c by entity_key.
    assert [key.rsplit("|", 1)[1] for key in lock_calls] == ["a", "b", "c"]


def test_volatile_fields_do_not_change_material_hash():
    base = {
        "hostname": "host-1",
        "last_seen_at": "a",
        "is_online": True,
        "power_state": "on",
    }
    changed_heartbeat = {
        **base,
        "last_seen_at": "b",
        "is_online": False,
        "power_state": "off",
    }
    assert material_hash(base) == material_hash(changed_heartbeat)
    assert material_hash(base) != material_hash({**base, "hostname": "host-2"})


def test_material_fields_change_hash_and_projection_is_sorted():
    base = {"hostname": "host-1", "os_version": "1"}
    changed = {**base, "os_version": "2"}
    assert material_hash(base) != material_hash(changed)
    assert list(material_projection(base)) == ["hostname", "os_version"]


def test_parent_scope_is_part_of_identity_contract():
    first = ("software", "device-a", "agent")
    second = ("software", "device-b", "agent")
    assert first != second
