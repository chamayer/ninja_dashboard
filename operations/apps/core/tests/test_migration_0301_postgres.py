"""Migration 0301 on a real PostgreSQL: every input change updates finding_state in the same
transaction, the cascade follows covering findings, and the app roles cannot write the table."""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0297_postgres import SCHEMA

_MIGRATION = importlib.import_module("apps.core.migrations.0301_finding_state")
_SKIP = importlib.import_module("apps.core.migrations.0302_finding_state_skip_unchanged")
TENANT = 1


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
            # Production: the migration owner bypasses row-level security.
            connection.execute("ALTER ROLE operations_migrate BYPASSRLS")
            connection.execute(_MIGRATION.FORWARD_SQL)
            connection.execute(_SKIP.FORWARD_SQL)
            yield connection


def _finding(conn, type_name, subject, status="open", severity="medium"):
    return conn.execute(
        """INSERT INTO operations.findings(tenant_id, finding_type_id, status, subject_id, severity)
           SELECT %s, id, %s, %s, %s FROM operations.finding_types WHERE name = %s RETURNING id""",
        (TENANT, status, subject, severity, type_name),
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


def _state(conn, finding):
    return conn.execute(
        "SELECT attention, reason, covered_by, policy_version FROM operations.finding_state"
        " WHERE finding_id = %s",
        (finding,),
    ).fetchone()


def test_a_new_finding_gets_a_row_without_any_call(conn):
    finding = _finding(conn, "plain", uuid.uuid4())
    assert _state(conn, finding)[:2] == ("pending", "no_current_assessment")


def test_an_assessment_insert_updates_the_state_in_the_same_transaction(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    assert _state(conn, finding)[:2] == ("needs_action", "ready")
    assert _state(conn, finding)[3] == "p1"


def test_a_participant_change_after_the_assessment_is_not_missed(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _assess(conn, finding, device)  # assessed before its participant exists
    _participant(conn, finding, device)
    assert _state(conn, finding)[0] == "needs_action"
    conn.execute("DELETE FROM operations.condition_participants WHERE finding_id = %s", (finding,))
    assert _state(conn, finding)[0] == "pending"  # the assessed participant set no longer matches


def test_a_bulk_insert_refreshes_every_finding_it_touches(conn):
    devices = [uuid.uuid4() for _ in range(5)]
    findings = [_finding(conn, "plain", d) for d in devices]
    for finding, device in zip(findings, devices, strict=True):
        _participant(conn, finding, device)
    rows = [
        (TENANT, f, d, json.dumps({"disposition": "eligible", "may_execute": True,
                                   "reasons": [], "blockers": []}))
        for f, d in zip(findings, devices, strict=True)
    ]
    with conn.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO operations.condition_assessments
               (tenant_id,row_kind,finding_id,participant_kind,participant_id,participant_role,
                policy_version,response)
               VALUES (%s,'entity',%s,'device',%s,'affected','p1',%s)""",
            rows,
        )
    assert {_state(conn, f)[0] for f in findings} == {"needs_action"}
    # One INSERT ... SELECT that writes many rows is a single statement-level event.
    conn.execute(
        """UPDATE operations.condition_assessments
              SET response = response || '{"may_execute": false, "disposition": "blocked"}'
            WHERE finding_id = ANY(%s)""",
        (findings,),
    )
    assert {_state(conn, f)[0] for f in findings} == {"blocked"}


def test_closing_and_reopening_a_finding_updates_its_state(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    conn.execute("UPDATE operations.findings SET status = 'resolved' WHERE id = %s", (finding,))
    assert _state(conn, finding)[:2] == (None, "closed")
    conn.execute("UPDATE operations.findings SET status = 'open' WHERE id = %s", (finding,))
    assert _state(conn, finding)[0] == "needs_action"


def test_a_severity_change_refreshes_but_a_last_seen_touch_does_not(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    before = conn.execute(
        "SELECT computed_at FROM operations.finding_state WHERE finding_id = %s", (finding,)
    ).fetchone()[0]
    conn.execute("UPDATE operations.findings SET last_seen_at = now() WHERE id = %s", (finding,))
    assert conn.execute(
        "SELECT computed_at FROM operations.finding_state WHERE finding_id = %s", (finding,)
    ).fetchone()[0] == before
    conn.execute("UPDATE operations.findings SET severity = 'high' WHERE id = %s", (finding,))
    assert conn.execute(
        "SELECT computed_at FROM operations.finding_state WHERE finding_id = %s", (finding,)
    ).fetchone()[0] > before


def test_closing_the_covering_finding_uncovers_its_child_in_the_same_transaction(conn):
    device = uuid.uuid4()
    parent = _finding(conn, "device_offline", device)
    child = _finding(conn, "stale_required_platform", device)
    _participant(conn, child, device)
    _assess(
        conn, child, device, disposition="suppressed", may_execute=False,
        reasons=["covered_by:device_offline"], blockers=[str(parent)],
    )
    attention, reason, covered_by, _ = _state(conn, child)
    assert (attention, reason, covered_by) == ("covered", "covered_by:device_offline", [parent])
    conn.execute("UPDATE operations.findings SET status = 'resolved' WHERE id = %s", (parent,))
    assert _state(conn, child)[0] == "pending"
    assert _state(conn, child)[2] == []
    conn.execute("UPDATE operations.findings SET status = 'open' WHERE id = %s", (parent,))
    assert _state(conn, child)[0] == "covered"


def test_the_cascade_follows_a_chain_of_covers(conn):
    device = uuid.uuid4()
    top = _finding(conn, "device_offline", device, status="resolved")
    middle = _finding(conn, "stale_required_platform", device)
    bottom = _finding(conn, "reboot_pending", device)
    for finding, parent, parent_type in (
        (middle, top, "device_offline"),
        (bottom, middle, "stale_required_platform"),
    ):
        _participant(conn, finding, device)
        _assess(
            conn, finding, device, disposition="suppressed", may_execute=False,
            reasons=[f"covered_by:{parent_type}"], blockers=[str(parent)],
        )
    assert _state(conn, middle)[0] == "pending"  # its covering finding is closed
    assert _state(conn, bottom)[0] == "covered"  # still covered by the open middle finding
    conn.execute("UPDATE operations.findings SET status = 'open' WHERE id = %s", (top,))
    assert _state(conn, middle)[0] == "covered"
    assert _state(conn, bottom)[0] == "covered"


def test_the_app_roles_can_read_but_not_write_the_state(conn):
    grants = conn.execute(
        """SELECT grantee, privilege_type FROM information_schema.role_table_grants
            WHERE table_schema = 'operations' AND table_name = 'finding_state'"""
    ).fetchall()
    writers = {g for g, p in grants if p in {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}}
    assert not writers & {"operations_app", "ninja_ingest", "operations_readonly", "PUBLIC"}
    assert {g for g, p in grants if p == "SELECT"} >= {"operations_app", "ninja_ingest"}


def test_the_fill_creates_a_row_for_every_active_finding(conn):
    conn.execute("DELETE FROM operations.finding_state")
    conn.execute(_MIGRATION.FILL_SQL)
    active = conn.execute(
        "SELECT count(*) FROM operations.findings WHERE status IN ('open','acknowledged','investigating')"
    ).fetchone()[0]
    stored = conn.execute(
        "SELECT count(*) FROM operations.finding_state WHERE attention IS NOT NULL"
    ).fetchone()[0]
    assert stored == active


def test_the_consistency_check_records_then_repairs_a_wrong_state(conn):
    from ingest import finding_attention

    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    # Simulate a missed input by writing the table the way only the function may.
    conn.execute("SELECT set_config('operations.tenant_id', '1', false)")
    conn.execute(
        "UPDATE operations.finding_state SET attention = 'blocked' WHERE finding_id = %s", (finding,)
    )
    with conn.cursor() as cursor:
        repaired = finding_attention.check_and_repair_state(cursor, TENANT)
    assert repaired >= 1
    assert _state(conn, finding)[0] == "needs_action"
    kept = conn.execute(
        """SELECT stored_attention, computed_attention FROM operations.finding_state_drift
           WHERE finding_id = %s""",
        (finding,),
    ).fetchone()
    assert kept == ("blocked", "needs_action")
    with conn.cursor() as cursor:
        assert finding_attention.check_and_repair_state(cursor, TENANT) == 0


def _set_state(conn, finding, **columns):
    conn.execute("SELECT set_config('operations.tenant_id', '1', false)")
    assignments = ", ".join(f"{name} = %s" for name in columns)
    conn.execute(
        f"UPDATE operations.finding_state SET {assignments} WHERE finding_id = %s",
        (*columns.values(), finding),
    )


def _computed_at(conn, finding):
    return conn.execute(
        "SELECT computed_at FROM operations.finding_state WHERE finding_id = %s", (finding,)
    ).fetchone()[0]


def test_an_unchanged_reassessment_only_restamps_the_state(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    _set_state(conn, finding, attention="blocked")  # a marker the full rule would overwrite
    before = _computed_at(conn, finding)
    conn.execute(
        "UPDATE operations.condition_assessments SET assessed_at = now() WHERE finding_id = %s",
        (finding,),
    )
    assert _state(conn, finding)[0] == "blocked"  # not recomputed
    assert _computed_at(conn, finding) > before  # but kept inside the freshness window


def test_a_changed_reassessment_is_recomputed_in_full(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    _set_state(conn, finding, attention="blocked")
    conn.execute(
        """UPDATE operations.condition_assessments
              SET response = response || '{"reasons": ["something_new"]}', assessed_at = now()
            WHERE finding_id = %s""",
        (finding,),
    )
    assert _state(conn, finding)[0] == "needs_action"


def test_one_statement_can_mix_changed_and_unchanged_findings(conn):
    devices = [uuid.uuid4(), uuid.uuid4()]
    same, different = (_finding(conn, "plain", d) for d in devices)
    for finding, device in ((same, devices[0]), (different, devices[1])):
        _participant(conn, finding, device)
        _assess(conn, finding, device)
        _set_state(conn, finding, attention="blocked")
    conn.execute(
        """UPDATE operations.condition_assessments
              SET assessed_at = now(),
                  response = CASE WHEN finding_id = %s
                                  THEN response || '{"reasons": ["x"]}'::jsonb ELSE response END
            WHERE finding_id = ANY(%s)""",
        (different, [same, different]),
    )
    assert _state(conn, same)[0] == "blocked"  # only re-stamped
    assert _state(conn, different)[0] == "needs_action"  # recomputed


def test_a_state_from_an_older_policy_version_is_recomputed_not_restamped(conn):
    device = uuid.uuid4()
    finding = _finding(conn, "plain", device)
    _participant(conn, finding, device)
    _assess(conn, finding, device)
    _set_state(conn, finding, attention="blocked", policy_version="older")
    conn.execute(
        "UPDATE operations.condition_assessments SET assessed_at = now() WHERE finding_id = %s",
        (finding,),
    )
    assert _state(conn, finding)[0] == "needs_action"
    assert _state(conn, finding)[3] == "p1"
