"""A deploy-interrupted source refresh is not a source failure (PLAN-037 Step 4).

Runs the real ``collection_problems`` SQL against disposable synthetic
PostgreSQL tables that carry only the columns it reads; never a configured
service.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from ingest.source_health import collection_problems

NOW = datetime.now(UTC)

SCHEMA = """
CREATE SCHEMA operations;
CREATE TABLE operations.sources (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE operations.source_instances (
    id uuid PRIMARY KEY, source_id uuid NOT NULL, client_id bigint,
    config jsonb NOT NULL DEFAULT '{}', enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE operations.source_bindings (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL,
    schedule text, enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE operations.operator_job_runs (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, job_key text NOT NULL,
    scope_identity text NOT NULL, status text NOT NULL, trigger_kind text NOT NULL
        CHECK (trigger_kind IN ('automatic', 'operator', 'dependency', 'recovery')),
    terminal_reason text, error text, requested_at timestamptz NOT NULL,
    started_at timestamptz, completed_at timestamptz
);
CREATE TABLE operations.source_refresh_outputs (
    tenant_id bigint NOT NULL, source_binding_id uuid NOT NULL, run_id uuid NOT NULL,
    published_at timestamptz NOT NULL
);
"""


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SCHEMA)
            yield connection


def _binding(cur, *, last_success_age=timedelta(hours=1)):
    source, instance, binding = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cur.execute("INSERT INTO operations.sources VALUES (%s, 'Ninja')", (source,))
    cur.execute(
        "INSERT INTO operations.source_instances (id, source_id) VALUES (%s, %s)",
        (instance, source),
    )
    cur.execute(
        "INSERT INTO operations.source_bindings VALUES (%s, 1, %s, 'interval:60', true)",
        (binding, instance),
    )
    if last_success_age is not None:
        cur.execute(
            "INSERT INTO operations.source_refresh_outputs VALUES (1, %s, %s, %s)",
            (binding, uuid.uuid4(), NOW - last_success_age),
        )
    return binding


def _run(cur, binding, age, status, trigger="automatic", reason=None):
    at = NOW - age
    cur.execute(
        """
        INSERT INTO operations.operator_job_runs
        VALUES (%s, 1, 'source-refresh', %s, %s, %s, %s, 'error', %s, %s, %s)
        """,
        (uuid.uuid4(), f"source-binding:{binding}", status, trigger, reason, at, at, at),
    )


def _problem_bindings(cur):
    return {problem.binding_id for problem in collection_problems(cur, 1, NOW)}


def test_deploy_interruption_is_not_a_failure_but_real_failures_still_are(conn):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE operations.source_bindings, operations.operator_job_runs")
        # Completed, then a deploy interrupted the next scheduled attempt.
        interrupted = _binding(cur)
        _run(cur, interrupted, timedelta(hours=2), "completed")
        _run(cur, interrupted, timedelta(minutes=5), "stalled", reason="worker_interrupted")
        # The one replay was interrupted again: this still needs attention.
        replay_interrupted = _binding(cur)
        _run(cur, replay_interrupted, timedelta(minutes=30), "stalled", reason="worker_interrupted")
        _run(
            cur, replay_interrupted, timedelta(minutes=5), "stalled",
            trigger="recovery", reason="worker_interrupted",
        )
        # A failure followed by an interruption is not hidden by the interruption.
        failed_then_interrupted = _binding(cur)
        _run(cur, failed_then_interrupted, timedelta(hours=1), "failed")
        _run(cur, failed_then_interrupted, timedelta(minutes=5), "stalled", reason="worker_interrupted")
        # A stall with another (or no) reason is still a failure.
        other_stall = _binding(cur)
        _run(cur, other_stall, timedelta(minutes=5), "stalled", reason="deadline_exceeded")
        null_reason_stall = _binding(cur)
        _run(cur, null_reason_stall, timedelta(minutes=5), "stalled")
        # Only interruptions, and no data for longer than the freshness window.
        stale = _binding(cur, last_success_age=timedelta(hours=9))
        _run(cur, stale, timedelta(minutes=5), "stalled", reason="worker_interrupted")

        problems = _problem_bindings(cur)

    assert str(interrupted) not in problems
    assert {
        str(replay_interrupted),
        str(failed_then_interrupted),
        str(other_stall),
        str(null_reason_stall),
        str(stale),
    } <= problems
