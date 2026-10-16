"""Opt-in PostgreSQL coverage: one lifecycle decision per Computer per run.

Run with ``RUN_POSTGRES_INTEGRATION_TESTS=1``. Uses a disposable Postgres
container. Regression for the 2026-10 oscillation: the source-withdrawal step
forced a Computer back to ``active`` whenever a record was still listed, and the
contact policy later in the same run moved it straight back, writing two
opposite ``lifecycle.transition`` rows every run.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from ingest.evaluator import _sync_lifecycle_status, _sync_source_withdrawal_lifecycle
from ingest.tests.test_evaluator_lifecycle_postgres import _prepare_track_a_schema


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_INTEGRATION_TESTS=1 to start a disposable Postgres container"
        )
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn, autocommit=True) as conn:
            _prepare_track_a_schema(conn)
            with conn.cursor() as cur:
                # Production column types (read from production 2026-10-16).
                cur.execute(
                    """
                    CREATE TABLE operations.v_device_source_record_lifecycle_current (
                        observation_id uuid NOT NULL,
                        tenant_id bigint NOT NULL,
                        device_id uuid NOT NULL,
                        counts_as_current_computer_evidence boolean NOT NULL
                    );
                    """
                )
            yield conn


NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _add_computer(
    cur,
    status: str,
    *,
    current_evidence: bool,
    last_contact: datetime | None,
) -> uuid.UUID:
    device_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO operations.devices VALUES (%s, 1, %s, %s, NULL)",
        (device_id, uuid.uuid4(), status),
    )
    cur.execute(
        "INSERT INTO operations.v_device_source_record_lifecycle_current VALUES (%s, 1, %s, %s)",
        (uuid.uuid4(), device_id, current_evidence),
    )
    if last_contact is not None:
        cur.execute(
            """
            INSERT INTO operations.device_agent_presence_current VALUES
                (1, %s, 'agent.remote_access', 'ScreenConnect', %s, %s, NULL, false)
            """,
            (device_id, last_contact, NOW),
        )
        cur.execute(
            """
            INSERT INTO operations.entity_observation_current VALUES
                (%s, 1, %s, 'agent.remote_access', 'ScreenConnect', true, %s,
                 '{"is_online": false}'::jsonb)
            """,
            (uuid.uuid4(), device_id, NOW),
        )
    return device_id


@pytest.fixture(autouse=True)
def _no_lifecycle_findings(monkeypatch):
    """This test is about transitions; lifecycle findings are covered elsewhere."""
    monkeypatch.setattr(
        "ingest.evaluator._resolve_lifecycle_findings_absent",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "ingest.evaluator._upsert_lifecycle_finding", lambda *args, **kwargs: 0
    )


def _run(cur) -> None:
    """The two lifecycle steps in the order ``evaluate`` runs them."""
    run_id = uuid.uuid4()
    _sync_source_withdrawal_lifecycle(cur, 1, NOW, run_id, None)
    _sync_lifecycle_status(cur, 1, NOW, run_id)


def _status(cur, device_id: uuid.UUID) -> str:
    cur.execute(
        "SELECT lifecycle_status FROM operations.devices WHERE id = %s", (device_id,)
    )
    return cur.fetchone()[0]


def _transitions(cur, device_id: uuid.UUID) -> list[tuple[str, str]]:
    cur.execute(
        """
        SELECT before_state->>'lifecycle_status', after_state->>'lifecycle_status'
          FROM operations.audit_log
         WHERE action = 'lifecycle.transition' AND entity_id = %s
         ORDER BY occurred_at
        """,
        (device_id,),
    )
    return cur.fetchall()


def test_listed_but_silent_computer_writes_no_transitions(postgres_connection) -> None:
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', '1', true)")
        silent = _add_computer(
            cur,
            "pending_cleanup",
            current_evidence=True,
            last_contact=NOW - timedelta(days=60),
        )
        aging = _add_computer(
            cur,
            "offline_aging",
            current_evidence=True,
            last_contact=NOW - timedelta(days=10),
        )
        _run(cur)
        _run(cur)
        assert _status(cur, silent) == "pending_cleanup"
        assert _status(cur, aging) == "offline_aging"
        assert _transitions(cur, silent) == []
        assert _transitions(cur, aging) == []


def test_real_changes_write_exactly_one_transition(postgres_connection) -> None:
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', '1', true)")
        back = _add_computer(
            cur,
            "pending_cleanup",
            current_evidence=True,
            last_contact=NOW - timedelta(hours=1),
        )
        gone = _add_computer(cur, "active", current_evidence=False, last_contact=None)
        documented = _add_computer(
            cur, "pending_cleanup", current_evidence=True, last_contact=None
        )
        stale = _add_computer(
            cur, "active", current_evidence=True, last_contact=NOW - timedelta(days=60)
        )
        _run(cur)
        _run(cur)
        assert _transitions(cur, back) == [("pending_cleanup", "active")]
        assert _transitions(cur, gone) == [("active", "pending_cleanup")]
        # Current evidence without qualified lifecycle evidence keeps the
        # earlier behavior: it leaves review for active.
        assert _transitions(cur, documented) == [("pending_cleanup", "active")]
        assert _transitions(cur, stale) == [("active", "pending_cleanup")]
        cur.execute(
            """
            SELECT after_state FROM operations.audit_log
             WHERE entity_id = %s AND action = 'lifecycle.transition'
            """,
            (back,),
        )
        after = cur.fetchone()[0]
        assert after["evidence_kind"] == "source_evidence_restored"
        assert after["contact_evidence_kind"] == "direct_contact"
        assert after["evidence_platform"] == "ScreenConnect"
