"""Opt-in PostgreSQL coverage for the PLAN-022 legacy drop migrations.

Run with ``RUN_POSTGRES_INTEGRATION_TESTS=1``. The test uses a disposable
Postgres container; it never connects to a configured Operations environment.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import psycopg
import pytest

SQL_DIR = Path(__file__).resolve().parents[2] / "sql" / "migrations"


@pytest.fixture
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_INTEGRATION_TESTS=1 to start a disposable Postgres container"
        )
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute("""
                CREATE SCHEMA ninja_core;
                CREATE SCHEMA operations;
                CREATE SCHEMA ninja_agent_compliance;
                CREATE SCHEMA ninja_inventory;
                CREATE TABLE ninja_core.devices (id integer PRIMARY KEY);
                CREATE TABLE ninja_core.device_snapshots (device_id integer, snapshot_at timestamptz);
                CREATE TABLE ninja_core.device_health_snapshots (device_id integer, snapshot_at timestamptz);
                CREATE TABLE ninja_agent_compliance.clients (client_id integer PRIMARY KEY);
                CREATE VIEW ninja_agent_compliance.v_clients AS
                    SELECT client_id FROM ninja_agent_compliance.clients;
                CREATE VIEW ninja_inventory.v_live AS
                    SELECT v.client_id, d.id
                      FROM ninja_agent_compliance.v_clients v, ninja_core.devices d;
                CREATE MATERIALIZED VIEW ninja_inventory.live_current AS
                    SELECT * FROM ninja_inventory.v_live WITH NO DATA;
                CREATE TABLE operations.change_history_registry (table_name text PRIMARY KEY);
                CREATE TABLE operations.source_record_seen_daily (source_record_id uuid);
                CREATE VIEW operations.ninja_device_seen_daily_shadow AS
                    SELECT source_record_id FROM operations.source_record_seen_daily;
                INSERT INTO operations.change_history_registry
                    VALUES ('source_record_seen_daily'), ('findings');
            """)
            yield connection


def _regclass(conn, name: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0]


def test_snapshot_drop_leaves_current_ninja_tables(conn):
    conn.execute((SQL_DIR / "117_drop_legacy_ninja_snapshots.sql").read_text())
    assert not _regclass(conn, "ninja_core.device_snapshots")
    assert not _regclass(conn, "ninja_core.device_health_snapshots")
    assert _regclass(conn, "ninja_core.devices")


def test_agent_compliance_drop_removes_both_schemas_only(conn):
    conn.execute((SQL_DIR / "118_drop_legacy_agent_compliance.sql").read_text())
    schemas = {
        row[0]
        for row in conn.execute("SELECT nspname FROM pg_namespace").fetchall()
    }
    assert "ninja_agent_compliance" not in schemas
    assert "ninja_inventory" not in schemas
    assert _regclass(conn, "ninja_core.devices")


def test_agent_compliance_drop_refuses_an_outside_dependent(conn):
    conn.execute(
        "CREATE VIEW operations.uses_legacy AS"
        " SELECT client_id FROM ninja_agent_compliance.clients"
    )
    with pytest.raises(psycopg.errors.RaiseException, match="outside view dependents"):
        conn.execute((SQL_DIR / "118_drop_legacy_agent_compliance.sql").read_text())
    assert _regclass(conn, "ninja_agent_compliance.clients")


def test_daily_presence_drop(conn):
    migration = importlib.import_module(
        "operations.apps.core.migrations.0350_drop_daily_presence"
    )
    conn.execute(migration.FORWARD_SQL)
    assert not _regclass(conn, "operations.source_record_seen_daily")
    assert not _regclass(conn, "operations.ninja_device_seen_daily_shadow")
    assert conn.execute(
        "SELECT table_name FROM operations.change_history_registry"
    ).fetchall() == [("findings",)]


def test_retired_job_configuration_is_removed_and_other_jobs_kept(conn):
    conn.execute("""
        CREATE TABLE operations.job_schedules (
            tenant_id bigint, id uuid, definition_key text,
            PRIMARY KEY (tenant_id, id));
        CREATE TABLE operations.job_schedule_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id bigint,
            schedule_id uuid NOT NULL,
            FOREIGN KEY (tenant_id, schedule_id) REFERENCES operations.job_schedules (tenant_id, id));
        CREATE TABLE operations.job_recovery_policies (definition_key text);
        CREATE TABLE operations.job_recovery_policy_authorities (definition_key text);
        INSERT INTO operations.job_schedules VALUES
            (1, '00000000-0000-0000-0000-000000000001', 'agent-compliance'),
            (1, '00000000-0000-0000-0000-000000000002', 'resolver');
        INSERT INTO operations.job_schedule_events (tenant_id, schedule_id) VALUES
            (1, '00000000-0000-0000-0000-000000000001'),
            (1, '00000000-0000-0000-0000-000000000002');
        INSERT INTO operations.job_recovery_policies VALUES ('parity-check'), ('resolver');
        INSERT INTO operations.job_recovery_policy_authorities VALUES ('parity-check'), ('resolver');
    """)
    migration = importlib.import_module(
        "operations.apps.core.migrations.0351_retired_job_configuration"
    )
    conn.execute(migration.FORWARD_SQL)
    for table in ("job_schedules", "job_recovery_policies", "job_recovery_policy_authorities"):
        assert conn.execute(
            f"SELECT definition_key FROM operations.{table}"
        ).fetchall() == [("resolver",)]
    assert conn.execute(
        "SELECT schedule_id::text FROM operations.job_schedule_events"
    ).fetchall() == [("00000000-0000-0000-0000-000000000002",)]
