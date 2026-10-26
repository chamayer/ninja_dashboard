"""Check 12 — tenant scope for source-record reads and writes with colliding IDs.

Policies are the tenant_isolation policies of migrations 0066 (observation
current/history/runs) and 0101 (entity_source_links), with FORCE RLS and the
production role attributes recorded in test_migration_0332_postgres.py
(operations_migrate owns and bypasses RLS; runtime roles are plain).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest

from conftest import OBSERVATION_SCHEMA, observation_row
from ingest import source_observations
from ingest.observations import write_current_rows

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = 7

POLICY = (
    "CREATE POLICY tenant_isolation ON operations.{t}"
    " USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)"
    " WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);"
    " ALTER TABLE operations.{t} ENABLE ROW LEVEL SECURITY;"
    " ALTER TABLE operations.{t} FORCE ROW LEVEL SECURITY;"
)
TABLES = (
    "entity_observation_current", "entity_observation_history",
    "observation_snapshot_runs", "entity_source_links",
)

SCHEMA = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_migrate') THEN
    CREATE ROLE operations_migrate NOLOGIN SUPERUSER BYPASSRLS;
    CREATE ROLE operations_app NOLOGIN;
    CREATE ROLE ninja_ingest NOLOGIN;
  END IF;
END $$;
SET ROLE operations_migrate;
CREATE SCHEMA operations;
GRANT USAGE ON SCHEMA operations TO operations_app, ninja_ingest;
""" + OBSERVATION_SCHEMA + """
CREATE TABLE operations.source_instances (id uuid PRIMARY KEY, source_id integer NOT NULL);
CREATE TABLE operations.entity_source_links (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, external_namespace text NOT NULL,
    external_id text NOT NULL, entity_id uuid NOT NULL, entity_class_id text NOT NULL,
    source_instance_id uuid NOT NULL, first_seen_at timestamptz,
    last_seen_at timestamptz, missing_since timestamptz
);
-- Migration 0123 definition.
CREATE VIEW operations.v_client_source_link WITH (security_invoker = true) AS
SELECT link.id, link.tenant_id, link.entity_id AS client_id, instance.source_id,
       link.external_id::varchar(240) AS external_id, link.external_namespace,
       link.first_seen_at, link.last_seen_at, link.missing_since
  FROM operations.entity_source_links link
  JOIN operations.source_instances instance ON instance.id = link.source_instance_id
 WHERE link.entity_class_id = 'client';
""" + "".join(POLICY.format(t=t) for t in TABLES) + """
GRANT SELECT, INSERT, UPDATE ON operations.entity_observation_current,
    operations.entity_observation_history, operations.observation_snapshot_runs
    TO ninja_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.entity_observation_current
    TO operations_app;
GRANT SELECT ON operations.entity_source_links, operations.source_instances,
    operations.v_client_source_link TO operations_app, ninja_ingest;
RESET ROLE;
"""

CLIENT = {1: uuid.uuid4(), 2: uuid.uuid4()}
SEED: dict[str, uuid.UUID] = {}


@pytest.fixture
def conn(postgres_dsn):
    with psycopg.connect(postgres_dsn, autocommit=True) as setup:
        setup.execute("DROP SCHEMA IF EXISTS operations CASCADE")
        setup.execute(SCHEMA)
        instance, binding = uuid.uuid4(), uuid.uuid4()
        setup.execute("SET ROLE operations_migrate")
        setup.execute("INSERT INTO operations.source_instances VALUES (%s, %s)",
                      (instance, SOURCE_ID))
        for tenant in (1, 2):
            # Same source instance, namespace and external ID in both tenants.
            setup.execute(
                "INSERT INTO operations.entity_source_links VALUES"
                " (gen_random_uuid(), %s, 'site', 'g1', %s, 'client', %s, now(), now(), NULL)",
                (tenant, CLIENT[tenant], instance))
        with setup.cursor() as cur:
            for tenant in (1, 2):
                row = observation_row(binding, instance, uuid.uuid4(), T0, external_id="42")
                row.update(tenant_id=tenant, client_id=CLIENT[tenant])
                write_current_rows(cur, [row])
        setup.execute("RESET ROLE")
    SEED.update(binding=binding, instance=instance)
    with psycopg.connect(postgres_dsn) as connection:
        yield connection


def _as(conn, role, tenant):
    conn.execute(f"SET ROLE {role}")
    if tenant is None:
        conn.execute("RESET operations.tenant_id")
    else:
        conn.execute("SELECT set_config('operations.tenant_id', %s, false)", (str(tenant),))


def _visible(conn):
    return conn.execute(
        "SELECT tenant_id, client_id FROM operations.entity_observation_current ORDER BY 1"
    ).fetchall()


def test_each_tenant_reads_only_its_own_colliding_records(conn):
    for role in ("ninja_ingest", "operations_app"):
        for tenant in (1, 2):
            _as(conn, role, tenant)
            assert _visible(conn) == [(tenant, CLIENT[tenant])]
            with conn.cursor() as cur:
                links = source_observations._load_client_links(
                    cur, SimpleNamespace(ops_source_id=SOURCE_ID)
                )
            # The collector also filters on its own tenant (1), so under
            # tenant 2 context it sees nothing rather than tenant 2's link.
            assert links == ({"g1": CLIENT[1]} if tenant == 1 else {})
            assert conn.execute(
                "SELECT client_id FROM operations.v_client_source_link"
            ).fetchall() == [(CLIENT[tenant],)]
            conn.execute("RESET ROLE")
            conn.rollback()


def test_no_tenant_context_reads_nothing_or_fails_closed(conn):
    # A session that never set the tenant: current_setting(..., TRUE) is NULL.
    conn.execute("SET ROLE operations_app")
    assert _visible(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM operations.v_client_source_link").fetchone() == (0,)
    conn.rollback()

    # A pooled session that set the tenant before (SET LOCAL leaves the same
    # trace) now has '' and the 0066/0101 policy cast raises instead.
    with conn.transaction():
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
    conn.execute("SET ROLE operations_app")
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        _visible(conn)
    conn.rollback()


def test_writes_cannot_cross_tenants(conn):
    binding, instance = SEED["binding"], SEED["instance"]
    _as(conn, "ninja_ingest", 1)
    row = observation_row(binding, instance, uuid.uuid4(), T0, external_id="99")
    row.update(tenant_id=2)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.cursor() as cur:
        write_current_rows(cur, [row])
    conn.rollback()

    _as(conn, "operations_app", 1)
    # Retargeting a tenant 1 row to tenant 2 is rejected by WITH CHECK.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE operations.entity_observation_current SET tenant_id = 2")
    conn.rollback()
    _as(conn, "operations_app", 1)
    assert conn.execute(
        "UPDATE operations.entity_observation_current SET client_id = NULL"
        " WHERE external_id = '42'"
    ).rowcount == 1  # only the tenant 1 row is reachable
    conn.rollback()
