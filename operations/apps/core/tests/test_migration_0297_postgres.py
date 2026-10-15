"""Migration 0297 on a real PostgreSQL: the rule, the triggers, and the drift record."""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

_MIGRATION = importlib.import_module("apps.core.migrations.0297_finding_attention")
TENANT = 1
OPEN = "open"

SCHEMA = """
CREATE ROLE operations_app; CREATE ROLE ninja_ingest; CREATE ROLE operations_readonly;
CREATE ROLE metabase_ro; CREATE ROLE operations_migrate;
CREATE SCHEMA operations AUTHORIZATION operations_migrate;
GRANT ALL ON SCHEMA operations TO CURRENT_USER;
CREATE TABLE operations.finding_types (
    id serial PRIMARY KEY, name text UNIQUE NOT NULL, covered_by jsonb NOT NULL DEFAULT '[]');
CREATE TABLE operations.findings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id integer NOT NULL,
    finding_type_id integer NOT NULL REFERENCES operations.finding_types(id),
    status text NOT NULL DEFAULT 'open', snoozed_until timestamptz,
    subject_type text NOT NULL DEFAULT 'device', subject_id uuid NOT NULL,
    last_seen_at timestamptz);
CREATE TABLE operations.condition_policy_versions (
    version text PRIMARY KEY, policy jsonb NOT NULL, active boolean NOT NULL DEFAULT false);
CREATE TABLE operations.condition_participants (
    tenant_id integer, row_kind text, finding_id uuid, participant_kind text,
    participant_id uuid, participant_role text);
CREATE TABLE operations.condition_assessments (
    tenant_id integer, row_kind text, finding_id uuid, participant_kind text,
    participant_id uuid, participant_role text, policy_version text,
    response jsonb, assessed_at timestamptz NOT NULL DEFAULT now());
GRANT ALL ON ALL TABLES IN SCHEMA operations TO operations_migrate;
INSERT INTO operations.condition_policy_versions VALUES
    ('p1', '{"freshness_hours": 24}', true);
INSERT INTO operations.finding_types(name, covered_by) VALUES
    ('device_offline', '[]'), ('stale_required_platform', '["device_offline"]'),
    ('reboot_pending', '["stale_required_platform"]'), ('plain', '[]');
"""


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
            connection.execute(_MIGRATION.FORWARD_SQL)
            yield connection


def _finding(conn, type_name, subject, status=OPEN):
    return conn.execute(
        """INSERT INTO operations.findings(tenant_id, finding_type_id, status, subject_id)
           SELECT %s, id, %s, %s FROM operations.finding_types WHERE name = %s RETURNING id""",
        (TENANT, status, subject, type_name),
    ).fetchone()[0]


def _participant(conn, finding, device):
    conn.execute(
        "INSERT INTO operations.condition_participants VALUES (%s,'entity',%s,'device',%s,'affected')",
        (TENANT, finding, device),
    )


def _assess(conn, finding, device, **response):
    base = {"disposition": "eligible", "may_execute": True, "reasons": [], "blockers": []}
    base.update(response)
    conn.execute(
        """INSERT INTO operations.condition_assessments
           (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role,
            policy_version,response)
           VALUES (%s,'entity',%s,'device',%s,'affected','p1',%s)""",
        (TENANT, finding, device, json.dumps(base)),
    )


def _attention(conn, finding):
    return conn.execute(
        "SELECT attention FROM operations.findings WHERE id = %s", (finding,)
    ).fetchone()[0]


def test_a_finding_that_may_execute_needs_action(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    conn.execute("SELECT operations.refresh_finding_attention(%s)", ([finding],))
    assert _attention(conn, finding) == "needs_action"


def test_a_blocked_assessment_blocks_and_a_missing_one_is_pending(conn):
    device = uuid.uuid4()
    blocked = _finding(conn, "plain", device)
    _participant(conn, blocked, device)
    _assess(conn, blocked, device, disposition="blocked", may_execute=False)
    unassessed = _finding(conn, "plain", uuid.uuid4())
    conn.execute("SELECT operations.refresh_finding_attention(%s)", ([blocked, unassessed],))
    assert _attention(conn, blocked) == "blocked"
    assert _attention(conn, unassessed) == "pending"


def test_closing_the_covering_finding_uncovers_the_child_without_a_reassessment(conn):
    device = uuid.uuid4()
    parent = _finding(conn, "device_offline", device)
    child = _finding(conn, "stale_required_platform", device)
    _participant(conn, child, device)
    _assess(
        conn, child, device, disposition="suppressed", may_execute=False,
        reasons=["covered_by:device_offline"], blockers=[str(parent)],
    )
    conn.execute("SELECT operations.refresh_finding_attention(%s)", ([child],))
    assert _attention(conn, child) == "covered"
    # The trigger refreshes the child the moment its covering finding closes.
    conn.execute("UPDATE operations.findings SET status = 'resolved' WHERE id = %s", (parent,))
    assert _attention(conn, child) == "pending"
    # And reopening it covers the child again.
    conn.execute("UPDATE operations.findings SET status = 'open' WHERE id = %s", (parent,))
    assert _attention(conn, child) == "covered"


def test_a_closed_finding_has_no_attention(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    conn.execute("SELECT operations.refresh_finding_attention(%s)", ([finding],))
    conn.execute("UPDATE operations.findings SET status = 'resolved' WHERE id = %s", (finding,))
    assert _attention(conn, finding) is None


def test_a_new_covering_finding_covers_children_when_it_opens(conn):
    device = uuid.uuid4()
    # reboot_pending is covered by stale_required_platform, itself covered by device_offline.
    child = _finding(conn, "reboot_pending", device)
    _participant(conn, child, device)
    middle = _finding(conn, "stale_required_platform", device, status="resolved")
    _assess(
        conn, child, device, disposition="suppressed", may_execute=False,
        reasons=["covered_by:stale_required_platform"], blockers=[str(middle)],
    )
    conn.execute("SELECT operations.refresh_finding_attention(%s)", ([child],))
    assert _attention(conn, child) == "pending"
    conn.execute("UPDATE operations.findings SET status = 'open' WHERE id = %s", (middle,))
    assert _attention(conn, child) == "covered"


def test_updates_that_do_not_change_status_do_not_fire_the_trigger(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    conn.execute("UPDATE operations.findings SET attention = 'blocked' WHERE id = %s", (finding,))
    conn.execute("UPDATE operations.findings SET last_seen_at = now() WHERE id = %s", (finding,))
    assert _attention(conn, finding) == "blocked"


def test_compute_agrees_with_the_stored_value_after_a_fill(conn):
    conn.execute("SELECT set_config('operations.tenant_id', '1', false)")
    conn.execute(_MIGRATION.FILL_SQL)
    drift = conn.execute(
        """SELECT count(*) FROM operations.compute_finding_attention(
               ARRAY(SELECT id FROM operations.findings
                      WHERE status IN ('open','acknowledged','investigating'))) c
           JOIN operations.findings f ON f.id = c.finding_id
           WHERE f.attention IS DISTINCT FROM c.attention"""
    ).fetchone()[0]
    assert drift == 0


def test_the_consistency_check_records_then_repairs_a_wrong_value(conn):
    from ingest import finding_attention

    finding_attention._available.update(at=0.0, ok=False, warned=False)
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    conn.execute("SELECT operations.refresh_finding_attention(%s)", ([finding],))
    conn.execute("UPDATE operations.findings SET attention = 'blocked' WHERE id = %s", (finding,))
    with conn.cursor() as cursor:
        repaired = finding_attention.check_and_repair(cursor, TENANT)
    assert repaired >= 1
    assert _attention(conn, finding) == "needs_action"
    kept = conn.execute(
        """SELECT stored_attention, computed_attention FROM operations.finding_attention_drift
           WHERE finding_id = %s""",
        (finding,),
    ).fetchone()
    assert kept == ("blocked", "needs_action")
    with conn.cursor() as cursor:
        assert finding_attention.check_and_repair(cursor, TENANT) == 0
