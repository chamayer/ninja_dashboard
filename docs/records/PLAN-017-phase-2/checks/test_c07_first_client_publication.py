"""Check 7 — first client publication from source evidence (ADR-0041).

Runs the real `operations.promote_client_candidate_v1` (migration 0342) and
the resolver's real `_attach_group` on synthetic evidence.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from conftest import OBSERVATION_SCHEMA, migration_function_sql, observation_row
from ingest.identity import client_resolver

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

# Columns are those the function and resolver read or write; uniqueness from
# the models (uq tenant+normalized_name on candidates and aliases, tenant+slug
# on clients). begin_change is stubbed: it records change history only.
CLIENT_SCHEMA = """
CREATE TABLE operations.entities (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, entity_class_id text NOT NULL,
    scope_kind text NOT NULL, client_id uuid, version integer NOT NULL,
    created_at timestamptz NOT NULL, created_reason text NOT NULL,
    updated_at timestamptz NOT NULL, updated_reason text NOT NULL,
    retired_at timestamptz, retired_reason text NOT NULL,
    deleted_at timestamptz, deleted_reason text NOT NULL
);
CREATE TABLE operations.clients (
    id uuid PRIMARY KEY REFERENCES operations.entities(id), tenant_id bigint NOT NULL,
    version integer NOT NULL, entity_id uuid NOT NULL, slug text NOT NULL,
    display_name text NOT NULL, timezone text NOT NULL, offline_after_days integer,
    requirement_profile_id uuid, created_at timestamptz NOT NULL,
    created_reason text NOT NULL, updated_at timestamptz NOT NULL,
    updated_reason text NOT NULL, stale_since timestamptz, stale_reason text NOT NULL,
    deleted_at timestamptz, deleted_reason text NOT NULL,
    provisional_since timestamptz, provisional_reason text NOT NULL DEFAULT '',
    verified_at timestamptz, verified_by text NOT NULL DEFAULT '',
    CONSTRAINT uq_clients_tenant_slug UNIQUE (tenant_id, slug)
);
CREATE TABLE operations.client_name_aliases (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, version integer NOT NULL,
    client_id uuid NOT NULL REFERENCES operations.clients(id), alias text NOT NULL,
    normalized_name text NOT NULL, tier text NOT NULL, enabled boolean NOT NULL,
    created_at timestamptz NOT NULL, created_by text NOT NULL, created_reason text NOT NULL,
    UNIQUE (tenant_id, normalized_name)
);
CREATE TABLE operations.client_candidates (
    id uuid PRIMARY KEY, version integer NOT NULL, tenant_id bigint NOT NULL,
    normalized_name text NOT NULL, display_name text NOT NULL, status text NOT NULL,
    seen_count integer NOT NULL, source_refs jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
    resolved_client_id uuid, resolved_at timestamptz,
    resolved_by text NOT NULL, resolved_reason text NOT NULL,
    UNIQUE (tenant_id, normalized_name)
);
CREATE TABLE operations.unmatched_source_groups (
    tenant_id bigint, source_id integer, external_id text
);
CREATE FUNCTION operations.begin_change(
    text, text, jsonb, text, uuid, text, text, bigint, boolean
) RETURNS void LANGUAGE sql AS 'SELECT NULL';
"""

NAME = "acme dental"


@pytest.fixture
def db(postgres_dsn):
    with psycopg.connect(postgres_dsn, autocommit=True) as setup:
        setup.execute("DROP SCHEMA IF EXISTS operations CASCADE")
        setup.execute("CREATE SCHEMA operations")
        setup.execute(OBSERVATION_SCHEMA)
        setup.execute(CLIENT_SCHEMA)
        setup.execute(
            migration_function_sql(
                "0342_automatic_client_promotion.py", "promote_client_candidate_v1"
            )
        )
    yield postgres_dsn


def _seed(conn, with_existing_client=False):
    """An open candidate seen twice, and its unattached org + device evidence."""
    binding, instance = uuid.uuid4(), uuid.uuid4()
    candidate = uuid.uuid4()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "INSERT INTO operations.client_candidates VALUES"
            " (%s, 1, 1, %s, 'Acme Dental', 'open', 2, '[]', now(), now(),"
            "  NULL, NULL, '', '')",
            (candidate, NAME),
        )
        org = observation_row(binding, instance, uuid.uuid4(), T0, external_id="g1",
                              namespace="site", entity_type="org")
        org["entity_key"] = "g1"
        device = observation_row(binding, instance, uuid.uuid4(), T0, external_id="d1",
                                 namespace="agent")
        device["canonical_data"] = {"platform_group_id": "g1"}
        from ingest.observations import write_current_rows
        write_current_rows(cur, [org, device])
        existing = None
        if with_existing_client:
            existing = uuid.uuid4()
            cur.execute(
                "INSERT INTO operations.entities VALUES (%s, 1, 'client', 'tenant', NULL,"
                " 1, now(), '', now(), '', NULL, '', NULL, '')", (existing,))
            cur.execute(
                "INSERT INTO operations.clients (id, tenant_id, version, entity_id, slug,"
                " display_name, timezone, created_at, created_reason, updated_at,"
                " updated_reason, stale_reason, deleted_reason) VALUES"
                " (%s, 1, 1, %s, 'acme', 'Acme', 'UTC', now(), '', now(), '', '', '')",
                (existing, existing))
    return binding, candidate, existing


def _promote(conn, candidate, client=None):
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT operations.promote_client_candidate_v1(1, %s, %s, 'test evidence')",
            (candidate, client),
        )
        return cur.fetchone()[0]


def _attach(conn, binding, client_id):
    with conn.transaction(), conn.cursor() as cur:
        client_resolver._attach_group(
            cur, None, binding, "g1", "Acme Dental", client_id, reason="resolver.name_match"
        )


def _counts(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT COUNT(*) FROM operations.clients),"
            " (SELECT COUNT(*) FROM operations.client_name_aliases),"
            " (SELECT string_agg(status, ',') FROM operations.client_candidates),"
            " (SELECT COUNT(DISTINCT client_id) FROM operations.entity_observation_current),"
            " (SELECT COUNT(*) FROM operations.entity_observation_current"
            "   WHERE client_id IS NULL)"
        )
        return cur.fetchone()


def test_create_attach_then_replay_is_idempotent(db):
    with psycopg.connect(db) as conn:
        binding, candidate, _ = _seed(conn)
        client = _promote(conn, candidate)
        _attach(conn, binding, client)
        assert _counts(conn) == (1, 1, "accepted", 1, 0)

        with pytest.raises(psycopg.errors.RaiseException, match="not open"):
            _promote(conn, candidate)
        _attach(conn, binding, uuid.uuid4())  # a later run: nothing unattached
        assert _counts(conn) == (1, 1, "accepted", 1, 0)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT client_id FROM operations.entity_observation_current")
            assert cur.fetchall() == [(client,)]
            cur.execute("SELECT provisional_since IS NOT NULL FROM operations.clients")
            assert cur.fetchone() == (True,)


def test_map_to_existing_client_creates_no_client(db):
    with psycopg.connect(db) as conn:
        binding, candidate, existing = _seed(conn, with_existing_client=True)
        assert _promote(conn, candidate, existing) == existing
        _attach(conn, binding, existing)
        assert _counts(conn) == (1, 1, "mapped", 1, 0)


def test_concurrent_promotions_publish_one_client(db):
    with psycopg.connect(db) as first, psycopg.connect(db) as second:
        _, candidate, _ = _seed(first)
        outcome: dict[str, object] = {}

        first.execute("BEGIN")
        first.execute(
            "SELECT operations.promote_client_candidate_v1(1, %s, NULL, 'first')",
            (candidate,),
        )

        def competing():
            try:
                _promote(second, candidate)
                outcome["second"] = "promoted"
            except psycopg.errors.RaiseException as exc:
                outcome["second"] = str(exc)

        thread = threading.Thread(target=competing)
        thread.start()
        thread.join(timeout=2)
        assert thread.is_alive(), "second promotion should wait on the candidate lock"
        first.execute("COMMIT")
        thread.join(timeout=10)

        assert "not open" in str(outcome["second"])
        assert _counts(first)[:3] == (1, 1, "accepted")
