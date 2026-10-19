"""Migration 0323 on a real PostgreSQL: maintenance cadence and retired schedules.

Jobs tables use production column types (2026-10-19); 0306's change history
foundation and 0227's terminal-outcome trigger run first, then every
statement of 0323.
"""

from __future__ import annotations

import importlib
import os
import uuid
from decimal import Decimal

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA

MODULE = "apps.core.migrations.0323_maintenance_cadence_and_retired_schedules"
REVISION = "0" * 64

JOBS = """
CREATE ROLE metabase_ro NOLOGIN;
CREATE TABLE operations.job_schedules (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL CHECK (tenant_id = 1),
    definition_key text NOT NULL, definition_digest text NOT NULL, scope_identity text NOT NULL,
    enabled boolean NOT NULL, capability_reason text NOT NULL, cadence jsonb NOT NULL,
    anchor_at timestamptz NOT NULL, time_zone text NOT NULL, next_due_at timestamptz,
    last_consumed_due_at timestamptz, last_requested_at timestamptz, last_request_id uuid,
    last_run_id uuid, last_outcome text, configuration_revision text NOT NULL
);
CREATE TABLE operations.operator_job_runs (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, job_key text NOT NULL,
    requested_at timestamptz NOT NULL, completed_at timestamptz, status text NOT NULL,
    terminal_reason text
);
CREATE TABLE operations.job_definition_versions (
    definition_key text NOT NULL, definition_digest text NOT NULL, handler_version text NOT NULL,
    metadata jsonb NOT NULL, created_at timestamptz NOT NULL
);
CREATE TABLE operations.queue_registry (
    queue_key varchar(120) NOT NULL, queue_type varchar(16) NOT NULL, table_name varchar(120) NOT NULL,
    owner varchar(80) NOT NULL, enabled boolean NOT NULL, max_pending_age_m integer NOT NULL,
    max_failure_count integer NOT NULL, max_depth integer NOT NULL, description text NOT NULL
);
CREATE TABLE operations.job_dependencies (
    id uuid NOT NULL, tenant_id bigint NOT NULL, dependent_run_id uuid NOT NULL,
    prerequisite_run_id uuid NOT NULL, required_input_revisions jsonb NOT NULL,
    required_output_revision text NOT NULL, failure_rule text NOT NULL, state text NOT NULL,
    reason text NOT NULL, created_at timestamptz NOT NULL, resolved_at timestamptz
);
CREATE TABLE operations.job_lane_limits (
    tenant_id bigint NOT NULL, lane text NOT NULL, capacity smallint NOT NULL, policy_revision text NOT NULL
);
CREATE TABLE operations.job_resource_limits (
    resource_template text NOT NULL, capacity smallint NOT NULL, policy_revision text NOT NULL,
    policy_kind text NOT NULL
);
CREATE TABLE operations.job_runtime_heartbeats (
    tenant_id bigint NOT NULL, runtime_kind text NOT NULL, runtime_identity uuid NOT NULL,
    registry_digest text NOT NULL, metadata jsonb NOT NULL, started_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL, stopped_at timestamptz
);
CREATE FUNCTION operations.jobs_current_lifecycle_v1(p_tenant_id bigint)
RETURNS TABLE(lifecycle text, run_count bigint, oldest_requested_at timestamptz)
LANGUAGE sql AS $$ SELECT 'ready'::text, 0::bigint, NULL::timestamptz WHERE false $$;
ALTER TABLE operations.job_schedules OWNER TO operations_migrate;
ALTER TABLE operations.operator_job_runs OWNER TO operations_migrate;
"""


def _run(conn, status, key):
    run_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.operator_job_runs VALUES (%s, 1, %s, now(), now(), %s, %s)",
        (run_id, key, status, status),
    )
    return run_id


def _schedule(conn, key, enabled, reason, outcome, run_id):
    schedule_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.job_schedules VALUES (%s, 1, %s, 'd', 'tenant:1', %s, %s,
               '{"kind": "interval", "minutes": 30}', now(), 'UTC', NULL, NULL, NULL, NULL,
               %s, %s, %s)""",
        (schedule_id, key, enabled, reason, run_id, outcome, REVISION),
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
            for name in ("0306_change_history_foundation", "0227_jobs_schedule_terminal_outcomes"):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(
                        getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL
                    )
            # 0306 registers job_schedules as covered and enables its history.
            assert connection.execute(
                "SELECT to_regclass('operations.job_schedules_change_history') IS NOT NULL"
            ).fetchone()[0]
            ids = {}
            ids["resolver"] = _schedule(
                connection,
                "resolver",
                False,
                "Managed by its operation entry point.",
                "stalled",
                _run(connection, "stalled", "resolver"),
            )
            ids["legacy"] = _schedule(
                connection,
                "agent-compliance",
                False,
                "Disabled — retired legacy bridge.",
                "cancelled",
                _run(connection, "cancelled", "agent-compliance"),
            )
            # A required Job that is switched off (not retired) is still reported.
            ids["required"] = _schedule(
                connection,
                "required-job",
                False,
                "Switched off for maintenance.",
                "completed",
                _run(connection, "completed", "required-job"),
            )
            for key in ("resolver", "required-job", "patches"):
                connection.execute(
                    """INSERT INTO operations.job_definition_versions
                       VALUES (%s, 'd', 'v1', '{"capability": "always"}', now())""",
                    (key,),
                )
            ids["live"] = _schedule(
                connection,
                "patches",
                True,
                "",
                "failed",
                _run(connection, "failed", "patches"),
            )
            module = importlib.import_module(MODULE)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(module.FORWARD_SQL)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection, ids


def _outcome(conn, schedule_id):
    return conn.execute(
        "SELECT last_outcome FROM operations.job_schedules WHERE id = %s", (schedule_id,)
    ).fetchone()[0]


def test_schedules_retired_by_0244_are_repaired(conn):
    connection, ids = conn
    assert _outcome(connection, ids["resolver"]) == "retired"
    # Only the 0244-managed schedules are rewritten.
    assert _outcome(connection, ids["legacy"]) == "cancelled"
    assert _outcome(connection, ids["live"]) == "failed"
    # last_outcome is run bookkeeping, not a recorded column: no history row.
    assert (
        connection.execute(
            "SELECT count(*) FROM operations.job_schedules_change_history WHERE operation = 'U'"
        ).fetchone()[0]
        == 0
    )


def test_a_finished_run_updates_only_enabled_schedules(conn):
    connection, ids = conn
    disabled_run, enabled_run = (
        _run(connection, "running", "resolver"),
        _run(connection, "running", "patches"),
    )
    connection.execute(
        "UPDATE operations.job_schedules SET last_run_id = %s WHERE id = %s",
        (disabled_run, ids["resolver"]),
    )
    connection.execute(
        "UPDATE operations.job_schedules SET last_run_id = %s WHERE id = %s",
        (enabled_run, ids["live"]),
    )
    connection.execute(
        "UPDATE operations.operator_job_runs SET status = 'stalled' WHERE id = ANY(%s)",
        ([disabled_run, enabled_run],),
    )
    assert _outcome(connection, ids["resolver"]) == "retired"
    assert _outcome(connection, ids["live"]) == "stalled"


def test_health_reports_failures_and_required_disabled_but_not_retired(conn):
    connection, ids = conn
    with connection.transaction():
        connection.execute("SET LOCAL operations.tenant_id = '1'")
        rows = connection.execute(
            "SELECT kind, payload ->> 'job_key' FROM operations.jobs_health_measurements_v1(1)"
            " WHERE kind IN ('schedule_failure', 'required_disabled') ORDER BY 1, 2"
        ).fetchall()
    # The retired resolver schedule (capability always) is in neither category;
    # the enabled failed schedule and the required schedule switched off are.
    assert rows == [("required_disabled", "required-job"), ("schedule_failure", "patches")]


def test_cadence_functions_act_only_for_the_session_tenant(conn):
    connection, _ids = conn
    for tenant in ("2", ""):
        for statement in (
            "SELECT operations.claim_maintenance(1, 'identity.roaming_records', interval '1 hour')",
            "SELECT operations.complete_maintenance(1, 'identity.roaming_records', 1)",
        ):
            with pytest.raises(psycopg.errors.RaiseException), connection.transaction():
                connection.execute("SET LOCAL ROLE ninja_ingest")
                connection.execute("SELECT set_config('operations.tenant_id', %s, true)", (tenant,))
                connection.execute(statement)


def test_oversized_component_keys_are_refused(conn):
    connection, _ids = conn
    for statement in (
        "SELECT operations.claim_maintenance(1, %s, interval '1 hour')",
        "SELECT operations.complete_maintenance(1, %s, 1)",
    ):
        with pytest.raises(psycopg.errors.RaiseException), connection.transaction():
            connection.execute("SET LOCAL ROLE ninja_ingest")
            connection.execute(statement, ("x" * 65,))


def test_claims_are_exclusive_per_interval_and_free_on_rollback(conn):
    connection, _ids = conn

    def claim(component="identity.roaming_records", interval="1 hour"):
        return connection.execute(
            "SELECT operations.claim_maintenance(1, %s, %s::interval)", (component, interval)
        ).fetchone()[0]

    with connection.transaction():
        connection.execute("SET LOCAL ROLE ninja_ingest")
        assert claim() is True
        assert claim() is False
        assert claim("identity.shadow_naming") is True
        connection.execute(
            "SELECT operations.complete_maintenance(1, 'identity.roaming_records', 12.3456)"
        )
    assert connection.execute(
        """SELECT completed_at IS NOT NULL, last_seconds FROM operations.maintenance_cadence
            WHERE component = 'identity.roaming_records'"""
    ).fetchone() == (True, Decimal("12.346"))
    # A slot older than the interval is free again, and claiming it clears the completion.
    connection.execute(
        "UPDATE operations.maintenance_cadence SET started_at = now() - interval '2 hours'"
        " WHERE component = 'identity.roaming_records'"
    )
    with pytest.raises(RuntimeError), connection.transaction():
        connection.execute("SET LOCAL ROLE ninja_ingest")
        assert claim() is True
        raise RuntimeError("the maintenance work failed")
    # The claim rolled back with its transaction: the slot is still free.
    with connection.transaction():
        connection.execute("SET LOCAL ROLE ninja_ingest")
        assert claim() is True
    with pytest.raises(psycopg.errors.RaiseException), connection.transaction():
        connection.execute("SELECT operations.claim_maintenance(1, '', interval '1 hour')")


def test_cadence_is_classified_and_tenant_scoped(conn):
    connection, _ids = conn
    assert (
        connection.execute(
            "SELECT classification FROM operations.change_history_registry WHERE table_name = 'maintenance_cadence'"
        ).fetchone()[0]
        == "exempt"
    )
    with connection.transaction():
        connection.execute("SET LOCAL ROLE ninja_ingest")
        connection.execute("SET LOCAL operations.tenant_id = '2'")
        assert (
            connection.execute("SELECT count(*) FROM operations.maintenance_cadence").fetchone()[0]
            == 0
        )


def test_the_resolver_calls_match_the_function_signatures(conn):
    """psycopg types the parameters (smallint, double precision); the calls must resolve."""
    from ingest.identity import resolver

    connection, _ids = conn
    connection.execute("DELETE FROM operations.maintenance_cadence")
    with connection.transaction(), connection.cursor() as cur:
        cur.execute("SET LOCAL ROLE ninja_ingest")
        assert resolver._claim_maintenance(cur, "identity.signature_check") is True
        resolver._complete_maintenance(cur, "identity.signature_check", 1.23456)
        assert resolver._claim_maintenance(cur, "identity.signature_check") is False
    assert connection.execute(
        "SELECT last_seconds FROM operations.maintenance_cadence WHERE component = 'identity.signature_check'"
    ).fetchone()[0] == Decimal("1.235")
