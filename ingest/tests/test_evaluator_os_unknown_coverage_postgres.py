"""Unknown OS applies no OS-limited requirement and raises one finding (ADR-0036).

Opt-in PostgreSQL coverage of ``_evaluate_coverage``: the queries run against
the shared lifecycle harness plus the requirement tables (production column
shapes, 2026-10-18); finding writes are captured.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from ingest import evaluator
from ingest.tests.test_evaluator_lifecycle_postgres import _prepare_track_a_schema

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
CLIENT = uuid.UUID("00000000-0000-4000-8000-0000000000c1")

EXTRA = """
ALTER TABLE operations.devices
    ADD COLUMN canonical_hostname varchar(255) NOT NULL DEFAULT '',
    ADD COLUMN device_role varchar(16) NOT NULL DEFAULT 'unknown',
    ADD COLUMN os_group varchar(16) NOT NULL DEFAULT 'Unknown';
CREATE TABLE operations.agents (
    id smallint PRIMARY KEY, name varchar(80) NOT NULL, entity_type varchar(80) NOT NULL,
    supported_os_groups jsonb NOT NULL
);
INSERT INTO operations.agents VALUES
    (1, 'Ninja', 'agent.rmm', '["Windows", "macOS", "Linux"]'),
    (3, 'LogMeIn', 'agent.remote_access', '["Windows", "macOS"]');
CREATE TABLE operations.os_group_mappings (os_group varchar(16) NOT NULL, pattern text NOT NULL);
INSERT INTO operations.os_group_mappings VALUES ('Windows', 'Windows %'), ('macOS', 'macOS'),
    ('Linux', 'Linux'), ('Other', 'Other');
CREATE TABLE operations.coverage_requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), client_id uuid NULL, agent_id smallint NULL,
    entity_type varchar(80) NOT NULL, platform varchar(80) NOT NULL, device_scope varchar(16) NOT NULL,
    applicable_os_groups jsonb NULL, severity varchar(16) NOT NULL, gap_after_hours integer NOT NULL,
    confidence_probable integer NOT NULL, confidence_confirmed integer NOT NULL,
    enabled boolean NOT NULL, tenant_id bigint NOT NULL
);
INSERT INTO operations.coverage_requirements
    (agent_id, entity_type, platform, device_scope, severity, gap_after_hours,
     confidence_probable, confidence_confirmed, enabled, tenant_id)
VALUES (1, 'agent.rmm', 'Ninja', 'all', 'critical', 720, 1440, 2160, true, 1),
       (3, 'agent.remote_access', 'LogMeIn', 'all', 'high', 720, 1440, 2160, true, 1);
CREATE TABLE operations.requirement_profile_items (
    profile_id uuid, agent_id smallint, entity_type varchar(80), platform varchar(80),
    device_scope varchar(16), applicable_os_groups jsonb, severity varchar(16),
    gap_after_hours integer, confidence_probable integer, confidence_confirmed integer,
    tenant_id bigint
);
CREATE TABLE operations.requirement_profiles (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, is_tenant_default boolean NOT NULL
);
INSERT INTO operations.requirement_profiles VALUES
    ('00000000-0000-4000-8000-0000000000d1', 1, true);
INSERT INTO operations.requirement_profile_items
    (profile_id, agent_id, entity_type, platform, device_scope, severity,
     gap_after_hours, confidence_probable, confidence_confirmed, tenant_id)
VALUES
    ('00000000-0000-4000-8000-0000000000d1', 1, 'agent.rmm', 'Ninja', 'all',
     'critical', 720, 1440, 2160, 1),
    ('00000000-0000-4000-8000-0000000000d1', 3, 'agent.remote_access', 'LogMeIn', 'all',
     'high', 720, 1440, 2160, 1);
CREATE TABLE operations.clients (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, requirement_profile_id uuid NULL,
    deleted_at timestamptz NULL
);
INSERT INTO operations.clients VALUES ('00000000-0000-4000-8000-0000000000c1', 1, NULL, NULL);
CREATE TABLE operations.device_operator_decisions (
    tenant_id bigint NOT NULL, device_id uuid NOT NULL, dimension varchar(80) NOT NULL,
    value jsonb NOT NULL
);
CREATE TABLE operations.v_device_source_record_lifecycle_current (
    tenant_id bigint, device_id uuid, entity_type varchar(80), platform varchar(80),
    source_record_current boolean, record_lifecycle varchar(24)
);
INSERT INTO operations.finding_types (id, name, default_severity, finding_class, auto_resolvable, category_id)
VALUES (90, 'missing_required_platform', 'high', 'entity', true, 1),
       (91, 'stale_required_platform', 'medium', 'entity', true, 1),
       (92, 'os_unknown_coverage', 'medium', 'entity', true, 1)
ON CONFLICT DO NOTHING;
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
            _prepare_track_a_schema(connection)
            connection.execute(EXTRA)
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


@pytest.fixture
def captured(monkeypatch):
    writes: list[tuple] = []
    resolved: list[list] = []
    evaluator._finding_type_cache.clear()
    monkeypatch.setattr(
        evaluator,
        "_upsert_finding",
        lambda cur, tenant, ft, client, device, key, sev, conf, now, details, assessment=None: (
            writes.append((ft, device, details)) or 1
        ),
    )
    monkeypatch.setattr(
        evaluator,
        "_resolve_findings_absent",
        lambda cur, tenant, ft, subjects, now, **kw: resolved.append((ft, list(subjects))),
    )
    return writes, resolved


def _computer(conn, *, os_group="Unknown", role="unknown", presence=()):
    device = uuid.uuid4()
    conn.execute(
        """INSERT INTO operations.devices (id, tenant_id, client_id, lifecycle_status, os_group, device_role)
           VALUES (%s, 1, %s, 'active', %s, %s)""",
        (device, CLIENT, os_group, role),
    )
    for entity_type, platform in presence:
        conn.execute(
            "INSERT INTO operations.device_agent_presence_current VALUES (1, %s, %s, %s, %s, %s, NULL, true)",
            (device, entity_type, platform, NOW - timedelta(hours=1), NOW),
        )
    return device


def test_unknown_os_applies_no_os_limited_requirement_and_raises_one_finding(conn, captured):
    writes, resolved = captured
    # ADR-0036: positive on the OS. LogMeIn is present, but with the OS unknown
    # neither Ninja nor LogMeIn applies; one os_unknown_coverage finding lists both.
    listing = _computer(conn, presence=[("agent.remote_access", "LogMeIn")])
    # A Windows machine without Ninja: reported missing as before.
    windows = _computer(conn, os_group="Windows", presence=[("agent.remote_access", "LogMeIn")])
    with conn.cursor() as cur:
        evaluator._evaluate_coverage(cur, 1, None, NOW, [], set())
    by_device = {}
    for ft, device, details in writes:
        by_device.setdefault(device, []).append((ft, details))
    assert by_device[listing] == [
        (92, {"hostname": "", "requirements_not_applied": [
            {"entity_type": "agent.rmm", "platform": "Ninja"},
            {"entity_type": "agent.remote_access", "platform": "LogMeIn"},
        ]}),
    ]
    assert [ft for ft, _d in by_device[windows]] == [90]
    assert resolved == [(92, [listing])]


def test_a_seen_agent_does_not_make_an_unknown_os_requirement_apply(conn, captured):
    writes, _resolved = captured
    # Ninja and LogMeIn have been on it, but the OS is unknown: nothing is
    # required, so nothing is missing or stale; the OS finding is raised.
    device = _computer(conn, role="workstation", presence=[("agent.rmm", "Ninja"),
                                                          ("agent.remote_access", "LogMeIn")])
    with conn.cursor() as cur:
        evaluator._evaluate_coverage(cur, 1, device, NOW, [], set())
    assert [ft for ft, d, _details in writes if d == device] == [92]
