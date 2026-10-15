"""Migration 0303 on a real PostgreSQL: the old objects go, the stored state and its triggers stay."""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0297_postgres import SCHEMA

_ORDER = (
    "0297_finding_attention",
    "0298_finding_states_view",
    "0299_finding_states_view_set_based",
    "0300_finding_states_view_fast",
    "0301_finding_state",
    "0302_finding_state_skip_unchanged",
    "0303_drop_attention_view_and_columns",
)


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
            connection.execute("ALTER ROLE operations_migrate BYPASSRLS")
            for name in _ORDER:
                module = importlib.import_module(f"apps.core.migrations.{name}")
                connection.execute(module.FORWARD_SQL)
            yield connection


def _exists(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_the_old_objects_are_gone(conn):
    assert not _exists(conn, "SELECT to_regclass('operations.finding_states') IS NOT NULL")
    assert not _exists(conn, "SELECT to_regclass('operations.finding_attention_drift') IS NOT NULL")
    assert not _exists(
        conn, "SELECT to_regprocedure('operations.refresh_finding_attention(uuid[])') IS NOT NULL"
    )
    columns = conn.execute(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'operations' AND table_name = 'findings'
              AND column_name IN ('attention', 'attention_at')"""
    ).fetchall()
    assert columns == []


def test_the_stored_state_and_its_triggers_survive_and_still_work(conn):
    triggers = {
        row[0]
        for row in conn.execute(
            """SELECT tgname FROM pg_trigger
                WHERE tgrelid IN ('operations.findings'::regclass,
                                  'operations.condition_assessments'::regclass,
                                  'operations.condition_participants'::regclass)
                  AND NOT tgisinternal"""
        )
    }
    assert {
        "finding_state_findings_insert",
        "finding_state_findings_change",
        "finding_state_assessments_insert",
        "finding_state_assessments_update",
        "finding_state_participants_insert",
    } <= triggers
    assert not {t for t in triggers if t.startswith("findings_attention")}
    finding = conn.execute(
        """INSERT INTO operations.findings(tenant_id, finding_type_id, status, subject_id)
           SELECT 1, id, 'open', %s FROM operations.finding_types WHERE name = 'plain' RETURNING id""",
        (uuid.uuid4(),),
    ).fetchone()[0]
    assert conn.execute(
        "SELECT attention FROM operations.finding_state WHERE finding_id = %s", (finding,)
    ).fetchone() == ("pending",)
