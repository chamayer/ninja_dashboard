"""The coverage pass stores a verdict for every requirement (ADR-0035, migration 0332).

Opt-in PostgreSQL coverage of ``_evaluate_coverage`` on the same harness as the
OS-unknown tests, plus a Hudu (``cmdb.asset``) requirement. Finding writes and
the verdict writer are captured.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from ingest import evaluator
from ingest.tests.test_evaluator_lifecycle_postgres import _prepare_track_a_schema
from ingest.tests.test_evaluator_os_unknown_coverage_postgres import CLIENT, EXTRA, lifecycle_record

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)

HUDU = """
INSERT INTO operations.agents VALUES
    (9, 'Hudu', 'cmdb.asset', '["Windows", "macOS", "Linux", "Other", "Unknown"]');
INSERT INTO operations.requirement_profile_items
    (profile_id, agent_id, entity_type, platform, device_scope, severity, gap_after_hours,
     confidence_probable, confidence_confirmed, tenant_id)
VALUES ('00000000-0000-4000-8000-0000000000d1',
        9, 'cmdb.asset', 'Hudu', 'all', 'medium', 720, 1440, 2160, 1);
"""


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn, autocommit=True) as connection:
            _prepare_track_a_schema(connection)
            connection.execute(EXTRA)
            connection.execute(HUDU)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


@pytest.fixture
def captured(monkeypatch):
    findings: list[tuple] = []
    writes: list[tuple] = []
    evaluator._finding_type_cache.clear()
    monkeypatch.setattr(
        evaluator,
        "_upsert_finding",
        lambda cur,
        tenant,
        ft,
        client,
        device,
        key,
        sev,
        conf,
        now,
        details,
        assessment=None: (findings.append((ft, device, details.get("platform", ""), key)) or 1),
    )
    monkeypatch.setattr(evaluator, "_resolve_findings_absent", lambda *a, **kw: None)
    monkeypatch.setattr(
        evaluator,
        "_write_requirement_state",
        lambda cur, tenant, device, verdicts: writes.append((device, verdicts)),
    )
    return findings, writes


def _computer(
    conn, *, presence=(), hudu=None, exemptions=None, os_group="Windows", lifecycle="active"
):
    device = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.devices (id, tenant_id, client_id, lifecycle_status, os_group, device_role)
           VALUES (%s, 1, %s, %s, %s, 'workstation')""",
        (device, CLIENT, lifecycle, os_group),
    )
    for entity_type, platform, age in presence:
        lifecycle_record(conn, device, entity_type, platform, NOW)
        conn.execute(
            "INSERT INTO operations.device_agent_presence_current VALUES (1, %s, %s, %s, %s, %s, NULL, true)",
            (device, entity_type, platform, NOW - age, NOW),
        )
    if hudu is not None:
        conn.execute(
            "INSERT INTO operations.device_agent_presence_current VALUES (1, %s, 'cmdb.asset', 'Hudu', NULL, %s, NULL, NULL)",
            (device, NOW - timedelta(hours=2)),
        )
        lifecycle_record(conn, device, "cmdb.asset", "Hudu", NOW,
                         lifecycle="documentation" if hudu == "active" else hudu)
    if exemptions:
        conn.execute(
            "INSERT INTO operations.device_operator_decisions VALUES (1, %s, 'exemptions', %s::jsonb)",
            (device, '{"%s": true}' % exemptions),
        )
    return device


def _by_device(verdicts):
    result: dict[str, dict[str, str]] = {}
    for item in verdicts:
        result.setdefault(item["device_id"], {})[item["platform"]] = item["verdict"]
    return result


def test_every_requirement_gets_a_verdict_and_hudu_is_seen(conn, captured):
    findings, writes = captured
    recent = timedelta(hours=1)
    documented = _computer(
        conn,
        presence=[
            ("agent.rmm", "Ninja", recent),
            ("agent.remote_access", "LogMeIn", recent),
        ],
        hudu="active",
    )
    archived_only = _computer(
        conn,
        presence=[
            ("agent.rmm", "Ninja", recent),
            ("agent.remote_access", "LogMeIn", recent),
        ],
        hudu="archived",
    )
    silent = _computer(
        conn, presence=[("agent.rmm", "Ninja", timedelta(days=40))], hudu="active"
    )
    no_agents = _computer(conn)
    exempt = _computer(
        conn,
        presence=[("agent.remote_access", "LogMeIn", recent)],
        hudu="active",
        exemptions="agent.rmm",
    )

    with conn.cursor() as cur:
        evaluator._evaluate_coverage(cur, 1, None, NOW, [], set())

    ((device_arg, verdicts),) = writes
    assert device_arg is None
    by_device = _by_device(verdicts)
    assert by_device[str(documented)] == {
        "Ninja": "satisfied",
        "LogMeIn": "satisfied",
        "Hudu": "satisfied",
    }
    assert by_device[str(archived_only)] == {
        "Ninja": "satisfied",
        "LogMeIn": "satisfied",
        "Hudu": "missing",
    }
    assert by_device[str(silent)] == {
        "Ninja": "stale",
        "LogMeIn": "missing",
        "Hudu": "satisfied",
    }
    assert by_device[str(no_agents)] == {
        "Ninja": "outside_coverage",
        "LogMeIn": "outside_coverage",
        "Hudu": "outside_coverage",
    }
    assert by_device[str(exempt)] == {
        "Ninja": "exempt",
        "LogMeIn": "satisfied",
        "Hudu": "satisfied",
    }

    # Every missing/stale verdict names the finding written in the same pass.
    keys = {(device, platform): key for _ft, device, platform, key in findings}
    for item in verdicts:
        if item["verdict"] in {"missing", "stale"}:
            assert (
                item["condition_key"]
                == keys[(uuid.UUID(item["device_id"]), item["platform"])]
            )
        else:
            assert item["condition_key"] is None
    assert {(device, platform) for device, platform in keys} == {
        (archived_only, "Hudu"),
        (silent, "Ninja"),
        (silent, "LogMeIn"),
    }


def test_single_computer_pass_writes_only_that_computer(conn, captured):
    _findings, writes = captured
    device = _computer(
        conn, presence=[("agent.rmm", "Ninja", timedelta(hours=1))], hudu="active"
    )
    with conn.cursor() as cur:
        evaluator._evaluate_coverage(cur, 1, device, NOW, [], set())
    ((device_arg, verdicts),) = writes
    assert device_arg == device
    assert {item["device_id"] for item in verdicts} == {str(device)}
    assert _by_device(verdicts)[str(device)] == {
        "Ninja": "satisfied",
        "LogMeIn": "missing",
        "Hudu": "satisfied",
    }


def test_unknown_os_and_pending_cleanup_are_recorded_not_raised(conn, captured):
    findings, writes = captured
    recent = timedelta(hours=1)
    unknown = _computer(
        conn, os_group="Unknown", presence=[("agent.rmm", "Ninja", timedelta(days=40))],
        hudu="active",
    )
    cleanup = _computer(
        conn, lifecycle="pending_cleanup", presence=[("agent.rmm", "Ninja", timedelta(days=45))],
        hudu="archived",
    )
    live = _computer(conn, presence=[("agent.rmm", "Ninja", recent)], hudu="active")

    with conn.cursor() as cur:
        evaluator._evaluate_coverage(cur, 1, None, NOW, [], set())

    ((_device_arg, verdicts),) = writes
    by_device = _by_device(verdicts)
    # Hudu supports "Unknown", so it still applies; the agents do not.
    assert by_device[str(unknown)] == {
        "Ninja": "os_unknown", "LogMeIn": "os_unknown", "Hudu": "satisfied",
    }
    # Lifecycle decides a Computer awaiting cleanup: nothing is checked.
    assert by_device[str(cleanup)] == {
        "Ninja": "pending_cleanup", "LogMeIn": "pending_cleanup", "Hudu": "pending_cleanup",
    }
    assert by_device[str(live)]["LogMeIn"] == "missing"
    raised = {(device, platform) for _ft, device, platform, _key in findings}
    assert not {item for item in raised if item[0] in {unknown, cleanup}} - {
        (unknown, "")  # the os_unknown_coverage finding carries no platform
    }
