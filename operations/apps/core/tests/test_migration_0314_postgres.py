"""Migration 0314 on a real PostgreSQL: one History timeline per Computer.

0306's foundation and 0308's merges run first with production definitions; the
page helpers in ``views`` are run against the function.
"""

from __future__ import annotations

import importlib
import os

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer


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
            for name in (
                "0306_change_history_foundation",
                "0308_computer_merge_and_split",
                "0314_computer_history",
            ):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def test_the_timeline_includes_merged_computers_grouped_by_action(conn):
    from apps.core.views import _change_history_events, _history_computer_ids

    survivor, absorbed = _computer(conn, "pc-h"), _computer(conn, "pc-h")
    other = _computer(conn, "pc-other")
    with conn.transaction():
        conn.execute(
            "SELECT operations.begin_change('computer.rename', 'renamed at the source', '{}', 'operator', 7)"
        )
        conn.execute(
            "UPDATE operations.devices SET canonical_hostname = 'pc-h-old' WHERE id = %s", (absorbed,)
        )
    with conn.transaction():
        conn.execute(
            "SELECT operations.merge_computers(%s::uuid, %s::uuid, 'same serial'::text, '{}'::jsonb)",
            (survivor, absorbed),
        )

    with conn.cursor() as cur:
        ids = _history_computer_ids(cur, survivor)
        assert set(ids) == {survivor, absorbed}
        events = _change_history_events(cur, ids, None, {7: "amy"})
    by_label = {e["label"]: e for e in events}
    assert by_label["computer.rename"]["actor"] == "amy"
    assert by_label["computer.rename"]["origin"] == "operator"
    assert any("pc-h → pc-h-old" in c for c in by_label["computer.rename"]["changes"])
    assert "computer.merge.automatic" in by_label
    # Another Computer's history never appears.
    with conn.cursor() as cur:
        assert all(
            row[2] != str(other)
            for row in cur.execute(
                "SELECT * FROM operations.computer_history(%s::uuid[], NULL, 100)", (ids,)
            ).fetchall()
        )


def test_paging_and_limits(conn):
    device = _computer(conn, "pc-page")
    with conn.cursor() as cur:
        rows = cur.execute(
            "SELECT recorded_at FROM operations.computer_history(%s::uuid[], NULL, 1)", ([device],)
        ).fetchall()
        assert len(rows) == 1
        assert cur.execute(
            "SELECT count(*) FROM operations.computer_history(%s::uuid[], %s, 100)",
            ([device], rows[0][0]),
        ).fetchone()[0] == 0
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("SELECT * FROM operations.computer_history(%s::uuid[], NULL, 0)", ([device],))
