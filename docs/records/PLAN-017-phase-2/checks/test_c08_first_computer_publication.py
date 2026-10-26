"""Check 8 — first Computer publication and canonical attachment.

Runs the real `write_current_rows` (source identity and first history
interval) and the real `ingest.identity.resolver._promote_unmatched_clusters`
(Computer creation, attachment, advisory-lock serialization, sibling guard).
Matching is stubbed to "no existing Computer" because a first publication has
nothing to match; matcher behavior is covered by
ingest/tests/test_identity_matching_postgres.py. Naming, agent-id loading and
layer entities are stubbed as side effects outside identity publication.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from conftest import OBSERVATION_SCHEMA, observation_row
from ingest.identity import resolver
from ingest.observations import write_current_rows

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
CLIENT = uuid.UUID("00000000-0000-4000-8000-0000000000c1")

# Columns written by _create_device_anchor / _create_device_for_group.
DEVICE_SCHEMA = """
CREATE TABLE operations.entities (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, entity_class_id text NOT NULL,
    scope_kind text NOT NULL, client_id uuid, version integer NOT NULL,
    created_at timestamptz NOT NULL, created_reason text NOT NULL,
    updated_at timestamptz NOT NULL, updated_reason text NOT NULL,
    retired_at timestamptz, retired_reason text NOT NULL,
    deleted_at timestamptz, deleted_reason text NOT NULL
);
CREATE TABLE operations.devices (
    id uuid PRIMARY KEY, version integer NOT NULL, tenant_id bigint NOT NULL,
    client_id uuid, entity_id uuid NOT NULL REFERENCES operations.entities(id),
    canonical_hostname text NOT NULL, canonical_serial text NOT NULL,
    canonical_vm_uuid text NOT NULL, device_type text NOT NULL,
    device_role text NOT NULL, lifecycle_status text NOT NULL, os_name text NOT NULL,
    os_family text NOT NULL, os_group text NOT NULL, created_at timestamptz NOT NULL,
    created_reason text NOT NULL, updated_at timestamptz NOT NULL,
    updated_reason text NOT NULL, stale_reason text NOT NULL, deleted_reason text NOT NULL
);
"""


@pytest.fixture
def dsn(postgres_dsn, monkeypatch):
    with psycopg.connect(postgres_dsn, autocommit=True) as setup:
        setup.execute("DROP SCHEMA IF EXISTS operations CASCADE")
        setup.execute("CREATE SCHEMA operations")
        setup.execute(OBSERVATION_SCHEMA)
        setup.execute(DEVICE_SCHEMA)
    monkeypatch.setattr(resolver, "identity_entity_types", lambda _cur: {"agent.test"})
    monkeypatch.setattr(resolver, "record_name_short", lambda _c, _p, _t, name, _d=None: (name or "").lower())
    monkeypatch.setattr(resolver, "resolve_match", lambda _cur, **_kw: None)
    monkeypatch.setattr(resolver, "_load_agent_ids", lambda _cur: {})
    monkeypatch.setattr(resolver, "_write_layer_entities_for_new_device", lambda _cur, **_kw: None)
    monkeypatch.setattr(resolver, "write_computer_names", lambda _cur, _ids: None)
    monkeypatch.setattr(resolver, "invalidate_client_names", lambda *_a, **_k: None)
    yield postgres_dsn


def _record(conn, *, binding=None, external_id="d1", at=T0, hostname="PC-1"):
    binding = binding or uuid.uuid4()
    row = observation_row(binding, uuid.uuid4(), uuid.uuid4(), at, external_id=external_id)
    row.update(client_id=CLIENT, platform="Test", entity_key=external_id,
               canonical_data={"hostname": hostname})
    with conn.transaction(), conn.cursor() as cur:
        written = write_current_rows(cur, [row])
    return row, written


def _promote(conn):
    with conn.transaction(), conn.cursor() as cur:
        return resolver._promote_unmatched_clusters(cur, ())


def _state(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT COUNT(*) FROM operations.devices),"
            " (SELECT COUNT(*) FROM operations.devices d JOIN operations.entities e"
            "   ON e.id = d.id AND d.entity_id = e.id),"
            " (SELECT COUNT(*) FROM operations.entity_observation_current"
            "   WHERE device_id IS NULL),"
            " (SELECT COUNT(DISTINCT device_id) FROM operations.entity_observation_current)"
        )
        return cur.fetchone()


def test_first_source_identity_opens_one_history_interval_and_replays(dsn):
    with psycopg.connect(dsn) as conn:
        row, written = _record(conn)
        assert written == 1
        replay = dict(row, observation_id=uuid.uuid4(), batch_id=uuid.uuid4())
        with conn.transaction(), conn.cursor() as cur:
            write_current_rows(cur, [replay])  # same identity, same instant
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (SELECT COUNT(*) FROM operations.entity_observation_current),"
                " (SELECT COUNT(*) FROM operations.entity_observation_history),"
                " (SELECT COUNT(*) FROM operations.entity_observation_history"
                "   WHERE effective_to IS NULL)"
            )
            assert cur.fetchone() == (1, 1, 1)


def test_first_computer_is_created_once_and_replay_creates_none(dsn):
    with psycopg.connect(dsn) as conn:
        _record(conn)
        assert _promote(conn) == 1
        assert _state(conn) == (1, 1, 0, 1)
        assert _promote(conn) == 0
        assert _state(conn) == (1, 1, 0, 1)


def test_sibling_record_attaches_to_the_existing_computer(dsn):
    with psycopg.connect(dsn) as conn:
        _record(conn)
        _promote(conn)
        # The same source record under another binding arrives unattached.
        _record(conn, binding=uuid.uuid4(), at=T0 + timedelta(hours=1))
        assert _promote(conn) == 0
        assert _state(conn) == (1, 1, 0, 1)


def test_concurrent_promotions_serialize_and_create_one_computer(dsn):
    with psycopg.connect(dsn) as first, psycopg.connect(dsn) as second:
        _record(first)
        result: dict[str, int] = {}
        first.execute("BEGIN")
        with first.cursor() as cur:
            result["first"] = resolver._promote_unmatched_clusters(cur, ())

        thread = threading.Thread(target=lambda: result.setdefault("second", _promote(second)))
        thread.start()
        thread.join(timeout=2)
        assert thread.is_alive(), "second promotion should wait on the advisory lock"
        first.execute("COMMIT")
        thread.join(timeout=10)

        assert result == {"first": 1, "second": 0}
        assert _state(first) == (1, 1, 0, 1)
