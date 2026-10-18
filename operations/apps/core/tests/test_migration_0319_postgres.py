"""Migration 0319 on a real PostgreSQL: audit_log is cut over to the change history.

``audit_log`` uses its production definition (2026-10-18); 0306's foundation
provides the change actions and the covered ``devices`` table.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0306_postgres import _device

AUDIT = """
CREATE TABLE operations.audit_log (
    audit_id uuid PRIMARY KEY, actor_kind varchar(16) NOT NULL, source varchar(32) NOT NULL,
    action varchar(120) NOT NULL, entity_type varchar(80) NOT NULL, entity_id uuid NULL,
    before_state jsonb NULL, after_state jsonb NULL, ip_address inet NULL,
    user_agent text NOT NULL, occurred_at timestamptz NOT NULL, actor_id bigint NULL,
    tenant_id bigint NOT NULL
);
INSERT INTO operations.audit_log VALUES
    ('00000000-0000-4000-8000-0000000000a1', 'system', 'ingest', 'lifecycle.transition',
     'device', NULL, '{}', '{}', NULL, '', now(), NULL, 1);
GRANT SELECT, INSERT ON operations.audit_log TO operations_app, ninja_ingest;
"""


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(FOUNDATION_SCHEMA)
            connection.execute(AUDIT)
            foundation = importlib.import_module("apps.core.migrations.0306_change_history_foundation")
            migration = importlib.import_module("apps.core.migrations.0319_audit_log_cutover")
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(migration.FORWARD_SQL)
            yield connection


def _audit(conn, action, entity_id, actor_id=7, actor_kind="user"):
    conn.execute(
        """INSERT INTO operations.audit_log VALUES
               (gen_random_uuid(), %s, 'ui', %s, 'device', %s, '{"a": 1}', '{"a": 2}',
                '10.0.0.5', 'browser', now(), %s, 1)""",
        (actor_kind, action, entity_id, actor_id),
    )


def test_an_operator_audit_names_the_requests_change_action(conn):
    device = uuid.uuid4()
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        _device(conn, device, uuid.uuid4())  # opens the implicit action
        _audit(conn, "device.lifecycle.retired", device)
        _audit(conn, "device.note", device)
    action = conn.execute(
        """SELECT a.action, a.actor_kind, a.actor_id, a.explicit,
                  jsonb_array_length(a.evidence -> 'items'), a.evidence -> 'items' -> 0
             FROM operations.devices_change_history h
             JOIN operations.change_actions a ON a.id = h.action_id
            WHERE h.entity_key = %s""",
        (str(device),),
    ).fetchone()
    assert action[:5] == ("device.lifecycle.retired", "operator", 7, True, 2)
    assert action[5]["before"] == {"a": 1} and action[5]["ip_address"] == "10.0.0.5"


def test_without_other_writes_a_new_explicit_action_is_started(conn):
    device = uuid.uuid4()
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        _audit(conn, "attribute_decision.set", device, actor_id=None, actor_kind="system")
    assert conn.execute(
        """SELECT action, actor_kind, explicit FROM operations.change_actions
            WHERE evidence -> 'items' -> 0 ->> 'entity_id' = %s""",
        (str(device),),
    ).fetchone() == ("attribute_decision.set", "process", True)


def test_audit_log_keeps_its_rows_and_takes_no_new_ones(conn):
    assert conn.execute("SELECT count(*) FROM operations.audit_log").fetchone()[0] == 1
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute("UPDATE operations.audit_log SET action = 'x'")
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute("DELETE FROM operations.audit_log")
