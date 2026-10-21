"""Migration 0332 on a real PostgreSQL: stored requirement verdicts (ADR-0035).

Production role attributes (2026-10-21): ``operations_migrate`` is a superuser
with BYPASSRLS and owns the derived tables; the runtime roles are plain.
``findings`` uses the production column types the check reads.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

MODULE = "apps.core.migrations.0332_device_requirement_state"

SCHEMA = """
CREATE ROLE operations_migrate NOLOGIN SUPERUSER BYPASSRLS;
CREATE ROLE operations_app NOLOGIN;
CREATE ROLE operations_readonly NOLOGIN;
CREATE ROLE ninja_ingest NOLOGIN;
CREATE ROLE metabase_ro NOLOGIN;
CREATE SCHEMA operations;
GRANT USAGE ON SCHEMA operations TO operations_app, operations_readonly, ninja_ingest;
CREATE TABLE operations.change_history_registry (
    table_name text PRIMARY KEY, classification text NOT NULL, reason text NOT NULL,
    recorded_columns text[] NOT NULL, secret_columns text[] NOT NULL, key_columns text[] NOT NULL,
    computer_column text NULL, computer_condition_column text NULL,
    computer_condition_value text NULL, client_column text NULL, is_global boolean NOT NULL,
    capture text NULL, enforce_action boolean NOT NULL DEFAULT false
);
CREATE TABLE operations.finding_types (id smallint PRIMARY KEY, name varchar(80) NOT NULL);
INSERT INTO operations.finding_types VALUES
    (1, 'missing_required_platform'), (2, 'stale_required_platform');
CREATE TABLE operations.findings (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, finding_type_id smallint NOT NULL,
    subject_type varchar(32) NOT NULL, subject_id uuid NOT NULL,
    finding_details jsonb NOT NULL DEFAULT '{}', status varchar(16) NOT NULL
);
"""

DEVICE_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
DEVICE_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SCHEMA)
            module = importlib.import_module(MODULE)
            connection.execute("SET ROLE operations_migrate")
            connection.execute(module.FORWARD_SQL)
            connection.execute("RESET ROLE")
            yield connection


def _row(device, platform, verdict, entity_type="agent.rmm"):
    return {
        "device_id": str(device),
        "entity_type": entity_type,
        "platform": platform,
        "agent_id": 1,
        "verdict": verdict,
        "last_observed_at": None,
        "condition_key": None,
    }


def _as_ingest(conn, sql, params=(), tenant="1"):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT set_config('operations.tenant_id', %s, true)", (tenant,))
        return conn.execute(sql, params).fetchall()


def _write(conn, devices, rows, tenant="1"):
    return _as_ingest(
        conn,
        "SELECT operations.write_device_requirement_state(1, %s::uuid[], %s::jsonb)",
        (devices, json.dumps(rows)),
        tenant,
    )[0][0]


def _state(conn):
    return conn.execute(
        "SELECT device_id, platform, verdict FROM operations.device_requirement_state "
        "ORDER BY device_id, platform"
    ).fetchall()


def test_registry_classifies_both_tables(conn):
    rows = conn.execute(
        "SELECT table_name, classification FROM operations.change_history_registry ORDER BY 1"
    ).fetchall()
    assert rows == [
        ("device_requirement_state", "exempt"),
        ("device_requirement_state_drift", "history_store"),
    ]


def test_runtime_roles_cannot_write_the_table_directly(conn):
    for role in ("ninja_ingest", "operations_app"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(f"SET LOCAL ROLE {role}")
            conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
            conn.execute(
                "INSERT INTO operations.device_requirement_state "
                "(tenant_id, device_id, entity_type, platform, verdict) "
                "VALUES (1, gen_random_uuid(), 'agent.rmm', 'Ninja', 'satisfied')"
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        conn.execute("SELECT operations.write_device_requirement_state(1, NULL, '[]')")


def test_writer_replaces_all_or_only_the_listed_computers(conn):
    assert (
        _write(
            conn,
            None,
            [
                _row(DEVICE_A, "Ninja", "missing"),
                _row(DEVICE_A, "Ninja", "satisfied"),  # duplicate: the failure wins
                _row(DEVICE_A, "Hudu", "satisfied", "cmdb.asset"),
                _row(DEVICE_B, "Ninja", "stale"),
            ],
        )
        == 3
    )
    assert _state(conn) == [
        (DEVICE_A, "Hudu", "satisfied"),
        (DEVICE_A, "Ninja", "missing"),
        (DEVICE_B, "Ninja", "stale"),
    ]
    # A single-Computer pass leaves every other Computer's verdicts alone.
    assert _write(conn, [str(DEVICE_B)], [_row(DEVICE_B, "Ninja", "satisfied")]) == 1
    assert _state(conn)[-1] == (DEVICE_B, "Ninja", "satisfied")
    assert len(_state(conn)) == 3


def test_writer_needs_the_session_tenant(conn):
    with pytest.raises(psycopg.errors.RaiseException):
        _write(conn, None, [], tenant="2")


def test_readers_see_only_their_tenant(conn):
    count = lambda tenant: _as_ingest(  # noqa: E731
        conn, "SELECT count(*) FROM operations.device_requirement_state", tenant=tenant
    )[0][0]
    assert count("1") == 3
    assert count("2") == 0


def test_check_records_and_clears_disagreements(conn):
    _write(
        conn,
        None,
        [
            _row(DEVICE_A, "Ninja", "missing"),
            _row(DEVICE_B, "Ninja", "satisfied"),
        ],
    )
    stale_finding = uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.findings VALUES (%s, 1, 2, 'device', %s, %s, 'open')",
        (stale_finding, DEVICE_B, json.dumps({"entity_type": "agent.rmm", "platform": "Ninja"})),
    )
    check = lambda: _as_ingest(  # noqa: E731
        conn, "SELECT operations.check_device_requirement_state(1)"
    )[0][0]
    assert check() == 2
    drift = conn.execute(
        "SELECT device_id, disagreement, verdict, finding_id, cleared_at IS NULL "
        "FROM operations.device_requirement_state_drift ORDER BY device_id"
    ).fetchall()
    assert drift == [
        (DEVICE_A, "missing_without_finding", "missing", None, True),
        (DEVICE_B, "finding_without_verdict", "satisfied", stale_finding, True),
    ]
    # Rerunning refreshes the open rows instead of adding new ones.
    assert check() == 2
    assert (
        conn.execute("SELECT count(*) FROM operations.device_requirement_state_drift").fetchone()[0]
        == 2
    )
    # Once the verdicts and findings agree, both clear and stay as history.
    conn.execute(
        "INSERT INTO operations.findings VALUES (%s, 1, 1, 'device', %s, %s, 'open')",
        (uuid.uuid4(), DEVICE_A, json.dumps({"entity_type": "agent.rmm", "platform": "Ninja"})),
    )
    conn.execute(
        "UPDATE operations.findings SET status = 'resolved' WHERE id = %s", (stale_finding,)
    )
    assert check() == 0
    assert (
        conn.execute(
            "SELECT count(*) FROM operations.device_requirement_state_drift WHERE cleared_at IS NOT NULL"
        ).fetchone()[0]
        == 2
    )


def test_check_does_nothing_before_the_first_pass(conn):
    conn.execute("DELETE FROM operations.device_requirement_state")
    assert _as_ingest(conn, "SELECT operations.check_device_requirement_state(1)")[0][0] == 0


def test_reverse_removes_everything(conn):
    module = importlib.import_module(MODULE)
    with conn.transaction():
        conn.execute(module.REVERSE_SQL)
        assert (
            conn.execute("SELECT to_regclass('operations.device_requirement_state')").fetchone()[0]
            is None
        )
        raise psycopg.Rollback()
