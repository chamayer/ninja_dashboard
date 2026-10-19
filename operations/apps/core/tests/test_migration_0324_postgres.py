"""Migration 0324 on a real PostgreSQL: the Jobs catalog decides which schedules are retired.

Jobs tables use production column types (2026-10-19); 0306, 0227 and 0323
run first, then every statement of 0324. The retirement rule is called
exactly as ``ingest/operator_job_queue.py`` calls it on every poll.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0323_postgres import JOBS, REVISION, _run

MODULE = "apps.core.migrations.0324_retire_undeclared_schedules"
CHAIN = (
    "0306_change_history_foundation",
    "0227_jobs_schedule_terminal_outcomes",
    "0323_maintenance_cadence_and_retired_schedules",
)
REPLACED = "Replaced by the configured source schedule."
# What the catalog declares in this test (the rule's p_declared_keys).
DECLARED = ["source-actions", "required-job", "live-job"]
RETIRE_SQL = "SELECT operations.jobs_disable_retired_tenant_schedules_v1(%s, %s::text[])"


def _schedule(conn, key, *, enabled, reason, outcome, scope="tenant:1", digest="d", due=False):
    schedule_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.job_schedules VALUES (%s, 1, %s, %s, %s, %s, %s,
               '{"kind": "interval", "minutes": 30}', now(), 'UTC',
               CASE WHEN %s THEN now() + interval '5 minutes' END, NULL, NULL, NULL,
               %s, %s, %s)""",
        (
            schedule_id,
            key,
            digest,
            scope,
            enabled,
            reason,
            due,
            _run(conn, outcome or "completed", key),
            outcome,
            REVISION,
        ),
    )
    return schedule_id


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
            connection.execute(JOBS)
            for name in CHAIN:
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(
                        getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL
                    )
            ids = {
                # Replaced by source refreshes: repaired, reason kept.
                "patches": _schedule(
                    connection, "patches", enabled=False, reason=REPLACED, outcome="completed"
                ),
                "intel-nvd": _schedule(
                    connection, "intel-nvd", enabled=False, reason=REPLACED, outcome="completed"
                ),
                "source-demand": _schedule(
                    connection,
                    "source-demand",
                    enabled=False,
                    reason="Replaced by binding-scoped source refreshes.",
                    outcome=None,
                ),
                # Already retired by 0244 / 0323: untouched, reason kept.
                "resolver": _schedule(
                    connection,
                    "resolver",
                    enabled=False,
                    reason="Managed by its operation entry point.",
                    outcome="retired",
                ),
                # Removed from the catalog while still active: retired by the rule.
                "dropped": _schedule(
                    connection,
                    "dropped-job",
                    enabled=True,
                    reason="Available",
                    outcome="completed",
                    due=True,
                ),
                # Declared: never retired by the rule.
                "source-actions": _schedule(
                    connection,
                    "source-actions",
                    enabled=False,
                    reason="Waiting for pending work.",
                    outcome=None,
                    digest="p",
                ),
                "required": _schedule(
                    connection,
                    "required-job",
                    enabled=False,
                    reason="Switched off for maintenance.",
                    outcome="completed",
                ),
                "live": _schedule(
                    connection, "live-job", enabled=True, reason="Available", outcome="failed"
                ),
                # A per-binding source refresh is not a tenant schedule.
                "binding": _schedule(
                    connection,
                    "source-refresh",
                    enabled=True,
                    reason="Available",
                    outcome="completed",
                    scope="source-binding:00000000-0000-4000-8000-000000000011",
                    due=True,
                ),
            }
            for key, digest, capability in (
                ("resolver", "d", "always"),
                ("required-job", "d", "always"),
                ("live-job", "d", "always"),
                ("source-actions", "p", "pending_work"),
            ):
                connection.execute(
                    "INSERT INTO operations.job_definition_versions VALUES (%s, %s, 'v1', %s::jsonb, now())",
                    (key, digest, f'{{"capability": "{capability}"}}'),
                )
            module = importlib.import_module(MODULE)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(module.FORWARD_SQL)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection, ids


def _state(conn, schedule_id):
    return conn.execute(
        """SELECT enabled, next_due_at IS NOT NULL, last_outcome, capability_reason
             FROM operations.job_schedules WHERE id = %s""",
        (schedule_id,),
    ).fetchone()


def _retire(conn):
    """The rule as the scheduler calls it, with psycopg's own parameter types."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE ninja_ingest")
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(RETIRE_SQL, (1, DECLARED))
        return cur.fetchone()[0]


def _history(conn):
    return conn.execute("SELECT count(*) FROM operations.job_schedules_change_history").fetchone()[
        0
    ]


def test_the_replaced_schedules_are_repaired_with_their_replacement_reasons(conn):
    connection, ids = conn
    assert _state(connection, ids["patches"]) == (False, False, "retired", REPLACED)
    assert _state(connection, ids["intel-nvd"]) == (False, False, "retired", REPLACED)
    assert _state(connection, ids["source-demand"]) == (
        False,
        False,
        "retired",
        "Replaced by binding-scoped source refreshes.",
    )


def test_the_rule_retires_only_undeclared_tenant_schedules_and_is_idempotent(conn):
    connection, ids = conn
    assert _retire(connection) == 1
    # A schedule dropped from the catalog while active gets the generic reason.
    assert _state(connection, ids["dropped"]) == (
        False,
        False,
        "retired",
        "Retired — no longer declared in the Jobs catalog.",
    )
    # An already retired schedule keeps its specific reason.
    assert _state(connection, ids["resolver"]) == (
        False,
        False,
        "retired",
        "Managed by its operation entry point.",
    )
    # Declared schedules and per-binding source refreshes are untouched.
    assert _state(connection, ids["source-actions"]) == (
        False,
        False,
        None,
        "Waiting for pending work.",
    )
    assert _state(connection, ids["live"])[:3] == (True, False, "failed")
    assert _state(connection, ids["binding"])[:3] == (True, True, "completed")
    # The next poll changes nothing and records no history.
    before = _history(connection)
    assert _retire(connection) == 0
    assert _retire(connection) == 0
    assert _history(connection) == before


def test_health_lists_real_problems_only(conn):
    connection, _ids = conn
    with connection.transaction():
        connection.execute("SET LOCAL operations.tenant_id = '1'")
        rows = connection.execute(
            "SELECT kind, payload ->> 'job_key' FROM operations.jobs_health_measurements_v1(1)"
            " WHERE kind IN ('schedule_failure', 'required_disabled') ORDER BY 1, 2"
        ).fetchall()
    # Retired schedules and the idle pending-work schedule are absent; a required
    # schedule switched off and an enabled failure are reported.
    assert rows == [("required_disabled", "required-job"), ("schedule_failure", "live-job")]
