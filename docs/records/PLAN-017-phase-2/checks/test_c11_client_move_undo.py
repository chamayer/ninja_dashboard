"""Check 11 — client source-group move, undo by moving back, and reappearance.

Computer merge -> split (the Computer-level undo) is covered by the existing
real-migration harness operations/apps/core/tests/test_migration_0315_postgres.py.
This check runs the real `move_client_source_group_v1` (migration 0341) and
`decide_client_source_mapping_v1` (0201), the real `v_client_source_link`
definition (0123), and the collector's real `_load_client_links`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest

from conftest import OBSERVATION_SCHEMA, migration_function_sql, observation_row
from ingest import source_observations
from ingest.observations import write_current_rows

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = 7

SCHEMA = """
CREATE TABLE operations.source_instances (id uuid PRIMARY KEY, source_id integer NOT NULL);
CREATE TABLE operations.clients (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, entity_id uuid NOT NULL,
    display_name text NOT NULL, deleted_at timestamptz
);
CREATE TABLE operations.devices (
    id uuid PRIMARY KEY, client_id uuid NOT NULL, deleted_at timestamptz
);
CREATE TABLE operations.client_name_aliases (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, version integer NOT NULL,
    client_id uuid NOT NULL, normalized_name text NOT NULL, enabled boolean NOT NULL,
    UNIQUE (tenant_id, normalized_name)
);
CREATE TABLE operations.entity_source_links (
    version integer NOT NULL, id uuid PRIMARY KEY, external_namespace varchar(120) NOT NULL,
    parent_external_namespace varchar(120) NOT NULL DEFAULT '',
    parent_external_id text NOT NULL DEFAULT '', external_id text NOT NULL,
    first_seen_at timestamptz, last_seen_at timestamptz, missing_since timestamptz,
    match_method text, match_confidence numeric, last_seen_binding_id uuid,
    reason varchar(120) NOT NULL, entity_id uuid NOT NULL,
    entity_class_id varchar(80) NOT NULL, source_instance_id uuid NOT NULL,
    tenant_id bigint NOT NULL
);
-- Columns and one-open-row index as in test_migration_0315_postgres.py.
CREATE TABLE operations.entity_source_link_history (
    version integer NOT NULL, id uuid PRIMARY KEY, external_namespace varchar(120) NOT NULL,
    parent_external_namespace varchar(120) NOT NULL, parent_external_id text NOT NULL,
    external_id text NOT NULL, match_method varchar(40) NOT NULL,
    match_confidence numeric NOT NULL, actor_kind varchar(16) NOT NULL,
    actor_process varchar(160) NOT NULL, reason varchar(120) NOT NULL, evidence jsonb NOT NULL,
    effective_from timestamptz NOT NULL, effective_to timestamptz NULL, actor_id bigint NULL,
    entity_id uuid NOT NULL, entity_class_id varchar(80) NOT NULL,
    last_seen_binding_id uuid NULL, source_instance_id uuid NOT NULL, tenant_id bigint NOT NULL
);
CREATE UNIQUE INDEX uq_entity_source_link_history_open ON operations.entity_source_link_history
    (tenant_id, source_instance_id, external_namespace, parent_external_namespace,
     parent_external_id, external_id) WHERE effective_to IS NULL;
-- Migration 0201, without the tenants/users foreign keys.
CREATE TABLE operations.client_source_mapping_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL CHECK (tenant_id = 1),
    source_link_id UUID NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('explicit', 'automatic', 'ignored', 'review')),
    provenance TEXT NOT NULL CHECK (provenance IN ('operator', 'legacy_alias', 'resolver')),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
    decided_by_id BIGINT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    superseded_by_id UUID REFERENCES operations.client_source_mapping_decisions(id),
    CHECK ((superseded_at IS NULL) = (superseded_by_id IS NULL)),
    UNIQUE (tenant_id, id)
);
-- Migration 0339.
ALTER TABLE operations.client_source_mapping_decisions
    ALTER CONSTRAINT client_source_mapping_decisions_superseded_by_id_fkey
    DEFERRABLE INITIALLY DEFERRED;
CREATE UNIQUE INDEX client_source_mapping_decisions_current
    ON operations.client_source_mapping_decisions (tenant_id, source_link_id)
    WHERE superseded_at IS NULL;
-- Migration 0123 definition.
CREATE VIEW operations.v_client_source_link WITH (security_invoker = true) AS
SELECT link.id, link.tenant_id, link.entity_id AS client_id, instance.source_id,
       link.external_id::varchar(240) AS external_id, link.external_namespace,
       link.first_seen_at, link.last_seen_at, link.missing_since
  FROM operations.entity_source_links link
  JOIN operations.source_instances instance ON instance.id = link.source_instance_id
 WHERE link.entity_class_id = 'client';
CREATE FUNCTION operations.begin_change(
    text, text, jsonb, text, bigint, text, text, bigint, boolean
) RETURNS void LANGUAGE sql AS 'SELECT NULL';
-- Stub: the real function (0340) also moves OS entities and findings.
CREATE FUNCTION operations.move_computer_to_client(uuid, uuid, text, bigint)
RETURNS void LANGUAGE sql AS 'UPDATE operations.devices SET client_id = $2 WHERE id = $1';
"""


@pytest.fixture
def conn(postgres_dsn):
    with psycopg.connect(postgres_dsn, autocommit=True) as setup:
        setup.execute("DROP SCHEMA IF EXISTS operations CASCADE")
        setup.execute("CREATE SCHEMA operations")
        setup.execute(OBSERVATION_SCHEMA)
        setup.execute(SCHEMA)
        setup.execute(migration_function_sql(
            "0201_client_source_mapping_decisions.py", "decide_client_source_mapping_v1"))
        setup.execute(migration_function_sql(
            "0341_client_source_group_move.py", "move_client_source_group_v1"))
    with psycopg.connect(postgres_dsn) as connection:
        yield connection


def _seed(conn):
    a, b = uuid.uuid4(), uuid.uuid4()
    instance, binding, link, device = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("INSERT INTO operations.source_instances VALUES (%s, %s)", (instance, SOURCE_ID))
        for client, name in ((a, "Acme"), (b, "Beta")):
            cur.execute("INSERT INTO operations.clients VALUES (%s, 1, %s, %s, NULL)",
                        (client, client, name))
        cur.execute("INSERT INTO operations.devices VALUES (%s, %s, NULL)", (device, a))
        cur.execute("INSERT INTO operations.client_name_aliases VALUES"
                    " (gen_random_uuid(), 1, 1, %s, 'acmeclinic', true)", (a,))
        org = observation_row(binding, instance, uuid.uuid4(), T0, external_id="g1",
                              namespace="site", entity_type="org")
        org.update(entity_key="g1", client_id=a, canonical_data={"name": "Acme Clinic"})
        rec = observation_row(binding, instance, uuid.uuid4(), T0, external_id="d1",
                              namespace="agent")
        rec.update(client_id=a, device_id=device, canonical_data={"platform_group_id": "g1"})
        write_current_rows(cur, [org, rec])
        cur.execute(
            "INSERT INTO operations.entity_source_links (version, id, external_namespace,"
            " external_id, reason, entity_id, entity_class_id, source_instance_id, tenant_id)"
            " VALUES (1, %s, 'site', 'g1', 'observation', %s, 'client', %s, 1)",
            (link, a, instance))
        cur.execute(
            "INSERT INTO operations.entity_source_link_history VALUES (1, gen_random_uuid(),"
            " 'site', '', '', 'g1', 'compatibility', 1, 'system', 'ingest.entity_link_sync',"
            " 'observation', '{}', clock_timestamp(), NULL, NULL, %s, 'client', NULL, %s, 1)",
            (a, instance))
    return a, b, link, device


def _move(conn, link, to, reason):
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT operations.move_client_source_group_v1(1, %s, %s, %s, 7)",
                    (link, to, reason))
        return cur.fetchone()[0]


def _snapshot(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT entity_id FROM operations.entity_source_links),"
            " (SELECT array_agg(DISTINCT client_id) FROM operations.entity_observation_current),"
            " (SELECT client_id FROM operations.devices),"
            " (SELECT client_id FROM operations.client_name_aliases),"
            " (SELECT COUNT(*) FROM operations.entity_source_link_history),"
            " (SELECT COUNT(*) FROM operations.entity_source_link_history"
            "   WHERE effective_to IS NULL),"
            " (SELECT COUNT(*) FROM operations.client_source_mapping_decisions),"
            " (SELECT reason FROM operations.client_source_mapping_decisions"
            "   WHERE superseded_at IS NULL)"
        )
        return cur.fetchone()


def test_move_then_move_back_restores_state_and_keeps_provenance(conn):
    a, b, link, device = _seed(conn)
    assert _move(conn, link, b, "wrong client")["computers_moved"] == 1
    assert _snapshot(conn) == (b, [b], b, b, 2, 1, 1, "Moved from Acme to Beta: wrong client")

    assert _move(conn, link, a, "undo")["computers_moved"] == 1
    assert _snapshot(conn) == (a, [a], a, a, 3, 1, 2, "Moved from Beta to Acme: undo")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entity_id, evidence ->> 'moved_from_client_id', effective_to IS NULL"
            "  FROM operations.entity_source_link_history ORDER BY effective_from"
        )
        assert cur.fetchall() == [(a, None, False), (b, str(a), False), (a, str(b), True)]


def test_reappearing_group_is_collected_to_the_restored_client(conn):
    a, b, link, _ = _seed(conn)
    _move(conn, link, b, "wrong client")
    _move(conn, link, a, "undo")
    source = SimpleNamespace(ops_source_id=SOURCE_ID)
    with conn.transaction(), conn.cursor() as cur:
        assert source_observations._load_client_links(cur, source) == {"g1": a}


def test_moving_to_the_current_client_is_refused(conn):
    a, _, link, _ = _seed(conn)
    with pytest.raises(psycopg.errors.RaiseException, match="already belongs"):
        _move(conn, link, a, "noop")
