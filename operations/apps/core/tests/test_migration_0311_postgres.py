"""Migration 0311 on a real PostgreSQL: confirming Computers in use.

Production definitions (2026-10-16) for devices and operator decisions, with
the decision validation trigger; 0306's foundation records the action.
"""

from __future__ import annotations

import importlib
import os

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer
from apps.core.tests.test_migration_0309_postgres import DECISIONS


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
            connection.execute(TABLES)
            connection.execute(DECISIONS)
            foundation = importlib.import_module(
                "apps.core.migrations.0306_change_history_foundation"
            )
            migration = importlib.import_module("apps.core.migrations.0311_confirmed_in_use")
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(migration.FORWARD_SQL)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def test_the_operations_role_confirms_in_use_as_one_recorded_action(conn):
    from types import SimpleNamespace

    from apps.core.finding_actions import CONFIRM_COMPUTERS_IN_USE
    from apps.core.identity_actions import _apply

    device = _computer(conn, "pc-in-use")
    finding = SimpleNamespace(id=None, subject_id=device, finding_details={})
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE operations_app")
        assert _apply(cur, finding, CONFIRM_COMPUTERS_IN_USE, "on the shelf, needed", 7).startswith(
            "Confirmed in use"
        )
    value, set_by = conn.execute(
        """SELECT value, set_by FROM operations.device_operator_decisions
            WHERE device_id = %s AND dimension = 'in_use_confirmed'""",
        (device,),
    ).fetchone()
    assert value is True and set_by == "user:7"
    assert conn.execute(
        """SELECT a.action FROM operations.device_operator_decisions_change_history h
             JOIN operations.change_actions a ON a.id = h.action_id
            ORDER BY h.id DESC LIMIT 1"""
    ).fetchone()[0] == "computer.confirm_in_use"
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute("SELECT operations.confirm_computers_in_use(%s, '')", ([device],))


def test_ingest_cannot_confirm(conn):
    device = _computer(conn, "pc-ingest-2")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT operations.confirm_computers_in_use(%s, 'x')", ([device],))
