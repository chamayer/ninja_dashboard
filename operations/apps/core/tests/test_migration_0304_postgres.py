"""Migration 0304 on a real PostgreSQL: cover is a live relation between open findings."""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0297_postgres import SCHEMA

TENANT = 1
_ORDER = (
    "0301_finding_state",
    "0302_finding_state_skip_unchanged",
    "0304_finding_cover_is_live",
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


def _finding(conn, type_name, subject, status="open", subject_type="device"):
    return conn.execute(
        """INSERT INTO operations.findings
               (tenant_id, finding_type_id, status, subject_id, subject_type)
           SELECT %s, id, %s, %s, %s FROM operations.finding_types WHERE name = %s RETURNING id""",
        (TENANT, status, subject, subject_type, type_name),
    ).fetchone()[0]


def _own_evidence(conn, finding, device):
    """The finding's own assessment: it may execute. Says nothing about any other finding."""
    conn.execute(
        "INSERT INTO operations.condition_participants VALUES (%s,'entity',%s,'device',%s,'affected')",
        (TENANT, finding, device),
    )
    conn.execute(
        """INSERT INTO operations.condition_assessments
           (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role,
            policy_version,response)
           VALUES (%s,'entity',%s,'device',%s,'affected','p1',%s)""",
        (
            TENANT, finding, device,
            json.dumps({"disposition": "eligible", "may_execute": True, "reasons": [], "blockers": []}),
        ),
    )


def _state(conn, finding):
    return conn.execute(
        "SELECT attention, reason, covered_by FROM operations.finding_state WHERE finding_id = %s",
        (finding,),
    ).fetchone()


def _set_status(conn, finding, status):
    conn.execute("UPDATE operations.findings SET status = %s WHERE id = %s", (status, finding))


def test_a_parent_that_opens_after_the_child_covers_it_without_a_reassessment(conn):
    device = uuid.uuid4()
    child = _finding(conn, "stale_required_platform", device)
    _own_evidence(conn, child, device)
    assert _state(conn, child)[0] == "needs_action"
    parent = _finding(conn, "device_offline", device)
    assert _state(conn, child) == ("covered", "covered_by:device_offline", [parent])


def test_a_closing_parent_hands_the_child_back_to_its_own_evidence_at_once(conn):
    device = uuid.uuid4()
    parent = _finding(conn, "device_offline", device)
    child = _finding(conn, "stale_required_platform", device)
    _own_evidence(conn, child, device)
    assert _state(conn, child)[0] == "covered"
    _set_status(conn, parent, "resolved")
    assert _state(conn, child) == ("needs_action", "ready", [])
    _set_status(conn, parent, "open")
    assert _state(conn, child)[0] == "covered"


def test_a_covered_finding_does_not_need_an_assessment(conn):
    device = uuid.uuid4()
    _finding(conn, "device_offline", device)
    child = _finding(conn, "stale_required_platform", device)
    assert _state(conn, child)[:2] == ("covered", "covered_by:device_offline")


def test_a_chain_names_the_root_most_open_parent_and_follows_it_when_it_closes(conn):
    device = uuid.uuid4()
    top = _finding(conn, "device_offline", device)
    middle = _finding(conn, "stale_required_platform", device)
    bottom = _finding(conn, "reboot_pending", device)
    for finding in (middle, bottom):
        _own_evidence(conn, finding, device)
    assert _state(conn, middle)[2] == [top]
    assert _state(conn, bottom)[2] == [top]  # the root-most open parent, not the middle one
    _set_status(conn, top, "resolved")
    assert _state(conn, middle)[0] == "needs_action"
    assert _state(conn, bottom) == ("covered", "covered_by:stale_required_platform", [middle])


def test_other_computers_other_types_and_other_subjects_do_not_cover(conn):
    device = uuid.uuid4()
    _finding(conn, "device_offline", uuid.uuid4())  # another computer
    _finding(conn, "plain", device)  # a type that covers nothing
    child = _finding(conn, "stale_required_platform", device)
    assert _state(conn, child)[0] == "pending"
    client = uuid.uuid4()
    _finding(conn, "device_offline", client, subject_type="client")
    other = _finding(conn, "stale_required_platform", client, subject_type="client")
    assert _state(conn, other)[0] == "pending"  # cover applies to computers only


def test_a_closed_child_is_not_covered_and_the_fill_agrees_with_the_triggers(conn):
    device = uuid.uuid4()
    _finding(conn, "device_offline", device)
    closed = _finding(conn, "stale_required_platform", device, status="resolved")
    assert _state(conn, closed)[0] is None
    live = conn.execute(
        "SELECT finding_id, attention, covered_by FROM operations.finding_state ORDER BY 1"
    ).fetchall()
    conn.execute("SELECT set_config('operations.tenant_id', '1', false)")
    conn.execute(
        """SELECT operations.refresh_finding_state(array_agg(id)) FROM operations.findings
            WHERE status IN ('open','acknowledged','investigating')"""
    )
    refilled = conn.execute(
        "SELECT finding_id, attention, covered_by FROM operations.finding_state ORDER BY 1"
    ).fetchall()
    assert refilled == live
