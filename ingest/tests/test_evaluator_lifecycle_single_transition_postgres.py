"""Opt-in PostgreSQL coverage: one lifecycle decision per Computer per run.

Run with ``RUN_POSTGRES_INTEGRATION_TESTS=1``. Uses a disposable Postgres
container. Regression for the 2026-10 oscillation: the source-withdrawal step
forced a Computer back to ``active`` whenever a record was still listed, and the
contact policy later in the same run moved it straight back, writing two
opposite ``lifecycle.transition`` rows every run. Also covers the ADR-0032
listing states: review for what only documentation or a stopped VM lists,
automatic retirement when nothing lists the machine, and restore.
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
                # The view's production column types (2026-10-16), as a table
                # so each record's lifecycle mapping can be set directly.
                cur.execute(
                    """
                    ALTER TABLE operations.entity_observation_current
                        ADD COLUMN entity_key text NOT NULL DEFAULT '';
                    ALTER TABLE operations.devices ADD COLUMN entity_id uuid NULL;
                    CREATE TABLE operations.entities (
                        id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
                        retired_at timestamptz NULL, retired_reason varchar(500) NOT NULL,
                        updated_at timestamptz NOT NULL, updated_reason varchar(120) NOT NULL
                    );
                    CREATE TABLE operations.v_device_source_record_lifecycle_current (
                        observation_id uuid NOT NULL,
                        tenant_id bigint NOT NULL,
                        device_id uuid NOT NULL,
                        source_name varchar(80) NOT NULL,
                        source_record_current boolean NOT NULL,
                        last_seen_at timestamptz NULL,
                        record_lifecycle varchar(24) NOT NULL,
                        counts_as_current_computer_evidence boolean NOT NULL
                    );
                    CREATE TABLE operations.change_actions (
                        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), action text NOT NULL
                    );
                    CREATE FUNCTION operations.begin_change(
                        p_action text, p_reason text, p_evidence jsonb, p_actor_kind text,
                        p_actor_id bigint, p_process text, p_process_version text,
                        p_tenant_id bigint, p_explicit boolean
                    ) RETURNS uuid LANGUAGE plpgsql AS $$
                    DECLARE v uuid;
                    BEGIN
                        INSERT INTO operations.change_actions (action) VALUES (p_action)
                        RETURNING id INTO v;
                        PERFORM set_config('operations.change_action_id', v::text, true);
                        RETURN v;
                    END $$;
                    """
                )
            yield conn


NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _add_computer(
    cur,
    status: str,
    *,
    current_evidence: bool = True,
    last_contact: datetime | None = None,
    lifecycle: str = "unknown",
    seen: datetime = NOW,
    records: bool = True,
    entity_type: str = "agent.remote_access",
    data: str = '{"is_online": false}',
) -> uuid.UUID:
    device_id, entity_id = uuid.uuid4(), uuid.uuid4()
    cur.execute(
        "INSERT INTO operations.devices VALUES (%s, 1, %s, %s, NULL, %s)",
        (device_id, uuid.uuid4(), status, entity_id),
    )
    cur.execute(
        "INSERT INTO operations.entities VALUES (%s, 1, NULL, '', now(), '')", (entity_id,)
    )
    if not records:
        return device_id
    observation_id = uuid.uuid4()
    cur.execute(
        """INSERT INTO operations.entity_observation_current
               (observation_id, tenant_id, device_id, entity_type, platform, active,
                observed_at, canonical_data)
           VALUES (%s, 1, %s, %s, 'ScreenConnect', true, %s, %s::jsonb)""",
        (observation_id, device_id, entity_type, NOW, data),
    )
    cur.execute(
        """INSERT INTO operations.v_device_source_record_lifecycle_current
           VALUES (%s, 1, %s, 'ScreenConnect', true, %s, %s, %s)""",
        (observation_id, device_id, seen, lifecycle, current_evidence),
    )
    if last_contact is not None:
        cur.execute(
            """
            INSERT INTO operations.device_agent_presence_current VALUES
                (1, %s, %s, 'ScreenConnect', %s, %s, NULL, false)
            """,
            (device_id, entity_type, last_contact, NOW),
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
    owned: set[uuid.UUID] = set()
    _sync_source_withdrawal_lifecycle(cur, 1, NOW, run_id, None, owned)
    _sync_lifecycle_status(cur, 1, NOW, run_id, skip=owned)


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
        silent = _add_computer(cur, "pending_cleanup", last_contact=NOW - timedelta(days=60))
        aging = _add_computer(cur, "offline_aging", last_contact=NOW - timedelta(days=10))
        _run(cur)
        _run(cur)
        assert _status(cur, silent) == "pending_cleanup"
        assert _status(cur, aging) == "offline_aging"
        assert _transitions(cur, silent) == []
        assert _transitions(cur, aging) == []


def test_real_changes_write_exactly_one_transition(postgres_connection) -> None:
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', '1', true)")
        back = _add_computer(cur, "pending_cleanup", last_contact=NOW - timedelta(hours=1))
        gone = _add_computer(cur, "active", current_evidence=False)
        listed = _add_computer(cur, "pending_cleanup")
        stale = _add_computer(cur, "active", last_contact=NOW - timedelta(days=60))
        _run(cur)
        _run(cur)
        assert _transitions(cur, back) == [("pending_cleanup", "active")]
        assert _transitions(cur, gone) == [("active", "pending_cleanup")]
        # An evidence record without qualified contact evidence leaves review for active.
        assert _transitions(cur, listed) == [("pending_cleanup", "active")]
        assert _transitions(cur, stale) == [("active", "pending_cleanup")]
        cur.execute(
            """
            SELECT after_state FROM operations.audit_log
             WHERE entity_id = %s AND action = 'lifecycle.transition'
            """,
            (back,),
        )
        after = cur.fetchone()[0]
        assert after["evidence_kind"] == "reporting"
        assert after["contact_evidence_kind"] == "direct_contact"
        assert after["evidence_platform"] == "ScreenConnect"


def test_documentation_and_a_stopped_vm_are_review_not_evidence(postgres_connection) -> None:
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', '1', true)")
        documented = _add_computer(
            cur, "active", current_evidence=False, lifecycle="documentation",
            entity_type="cmdb.asset",
        )
        # The contact policy alone would call this VM offline_aging.
        stopped = _add_computer(
            cur, "offline_aging", current_evidence=False, lifecycle="stopped",
            entity_type="vm.guest", last_contact=NOW - timedelta(days=2),
            data='{"power_state": "poweredoff"}',
        )
        _run(cur)
        _run(cur)
        assert _transitions(cur, documented) == [("active", "pending_cleanup")]
        assert _transitions(cur, stopped) == [("offline_aging", "pending_cleanup")]


def test_nothing_listing_a_machine_retires_it_and_reporting_restores_it(
    postgres_connection,
) -> None:
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', '1', true)")
        archived = _add_computer(
            cur, "pending_cleanup", current_evidence=False, lifecycle="archived",
            entity_type="cmdb.asset",
        )
        empty_old = _add_computer(cur, "pending_cleanup", records=False)
        recent = _add_computer(
            cur, "pending_cleanup", current_evidence=False, seen=NOW - timedelta(days=3)
        )
        back = _add_computer(cur, "retired", last_contact=NOW - timedelta(hours=2))
        listed_silent = _add_computer(cur, "retired", last_contact=NOW - timedelta(days=90))
        _run(cur)
        _run(cur)
        assert _transitions(cur, archived) == [("pending_cleanup", "retired")]
        assert _transitions(cur, empty_old) == [("pending_cleanup", "retired")]
        # Without Hudu, retirement waits for the review period.
        assert _transitions(cur, recent) == []
        assert _transitions(cur, back) == [("retired", "active")]
        # Listed again but not reporting: stays retired.
        assert _transitions(cur, listed_silent) == []
        cur.execute(
            """SELECT e.retired_at IS NOT NULL, e.retired_reason FROM operations.entities e
                 JOIN operations.devices d ON d.entity_id = e.id WHERE d.id = %s""",
            (archived,),
        )
        assert cur.fetchone() == (True, "Nothing lists this machine any more (ADR-0032).")
        cur.execute("SELECT action, count(*) FROM operations.change_actions GROUP BY 1 ORDER BY 1")
        assert cur.fetchall() == [
            ("computer.restore.automatic", 1),
            ("computer.retire.automatic", 2),
        ]
        cur.execute("SELECT current_setting('operations.change_action_id', true)")
        assert cur.fetchone()[0] == ""
