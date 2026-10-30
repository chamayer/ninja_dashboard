"""The Issues selection contract on a real PostgreSQL (PLAN-003 R3).

Tables carry only the columns the selection reads, with production types. The
selection SQL is executed as built by ``issue_selection._filtered_sql``.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from apps.core import issue_selection
from apps.core.issue_selection import Scope

SCHEMA = """
CREATE SCHEMA operations;
CREATE TABLE operations.finding_types (
    id smallint PRIMARY KEY, name varchar(120) NOT NULL UNIQUE,
    display_name varchar(120) NOT NULL, default_severity varchar(16) NOT NULL
);
CREATE TABLE operations.findings (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
    condition_namespace varchar(16) NOT NULL DEFAULT 'entity',
    finding_type_id smallint NOT NULL REFERENCES operations.finding_types (id),
    severity varchar(16) NOT NULL, status varchar(24) NOT NULL,
    snoozed_until timestamptz NULL, client_id uuid NULL,
    subject_type varchar(32) NOT NULL, subject_id uuid NULL,
    finding_details jsonb NOT NULL DEFAULT '{}', subject_ref jsonb NOT NULL DEFAULT '{}',
    last_detected_at timestamptz NULL, last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE operations.finding_state (
    finding_id uuid PRIMARY KEY, tenant_id bigint NOT NULL, attention text NULL,
    covered_by uuid[] NOT NULL DEFAULT ARRAY[]::uuid[]
);
CREATE TABLE operations.source_instances (id uuid PRIMARY KEY, source_id smallint NOT NULL);
CREATE TABLE operations.source_bindings (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL
);
CREATE TABLE operations.entity_candidates (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, status varchar(24) NOT NULL,
    client_id uuid NULL, last_observed_at timestamptz NOT NULL DEFAULT now(),
    external_id text NOT NULL, external_namespace varchar(120) NOT NULL
);
CREATE TABLE operations.devices (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, canonical_hostname text NULL,
    deleted_at timestamptz NULL, os_name text NOT NULL DEFAULT '',
    device_role varchar(16) NOT NULL DEFAULT 'unknown'
);
CREATE TABLE operations.clients (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, slug text NOT NULL,
    display_name text NOT NULL, deleted_at timestamptz NULL
);
CREATE TABLE operations.v_device_software_exposure (
    tenant_id bigint NOT NULL, finding_id uuid NOT NULL, client_id uuid NULL, device_id uuid NULL
);
INSERT INTO operations.finding_types VALUES
    (1, 'unmatched_source_group', 'Source group without a client', 'medium'),
    (2, 'client_unattached_group', 'Source group not attached', 'medium'),
    (3, 'device_offline', 'Computer offline', 'medium'),
    (4, 'missing_required_platform', 'Required agent missing', 'high'),
    (5, 'identity_resolution_pending', 'Record needs a match', 'low'),
    (6, 'rare_recent', 'Software needs approval', 'medium');
"""


@pytest.fixture(scope="module")
def dsn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(SCHEMA)
        yield url


@pytest.fixture
def conn(dsn):
    with psycopg.connect(dsn) as connection:
        yield connection
        connection.rollback()


def _finding(
    conn,
    type_id,
    *,
    namespace="entity",
    severity="medium",
    status="open",
    paused=False,
    client=None,
    subject_type="device",
    subject=None,
    details="{}",
    ref="{}",
    attention=None,
    covered_by=(),
):
    finding_id = uuid.uuid4()
    conn.execute(
        """
        INSERT INTO operations.findings (id, tenant_id, condition_namespace, finding_type_id,
            severity, status, snoozed_until, client_id, subject_type, subject_id,
            finding_details, subject_ref, last_detected_at)
        VALUES (%s, 1, %s, %s, %s, %s, CASE WHEN %s THEN now() + interval '1 day' END,
                %s, %s, %s, %s::jsonb, %s::jsonb, now())
        """,
        [
            finding_id,
            namespace,
            type_id,
            severity,
            status,
            paused,
            client,
            subject_type,
            subject or uuid.uuid4(),
            details,
            ref,
        ],
    )
    if attention:
        conn.execute(
            "INSERT INTO operations.finding_state VALUES (%s, 1, %s, %s::uuid[])",
            [finding_id, attention, list(covered_by)],
        )
    return finding_id


def _run(conn, scope, select="SELECT type_name, status, count(*) FROM selected GROUP BY 1, 2"):
    sql, params = issue_selection._filtered_sql(scope)
    return conn.execute(sql + " " + select, params).fetchall()


def _ids(conn, scope):
    return {row[0] for row in _run(conn, scope, "SELECT id FROM selected")}


def _source_group(conn, source_id, external_id):
    instance, binding = uuid.uuid4(), uuid.uuid4()
    conn.execute("INSERT INTO operations.source_instances VALUES (%s, %s)", [instance, source_id])
    conn.execute("INSERT INTO operations.source_bindings VALUES (%s, 1, %s)", [binding, instance])
    entity = _finding(
        conn,
        1,
        subject_type="source_binding",
        severity="critical",
        details=f'{{"source_id": {source_id}, "external_id": "{external_id}"}}',
    )
    admin = _finding(
        conn,
        2,
        namespace="admin",
        subject_type="source_group",
        severity="critical",
        ref=f'{{"source_binding_id": "{binding}", "external_id": "{external_id}"}}',
    )
    return entity, admin


def test_one_source_group_problem_counts_once_and_the_admin_record_represents_it(conn):
    entity, admin = _source_group(conn, 3, "G1")
    lone_admin = _finding(
        conn,
        2,
        namespace="admin",
        subject_type="source_group",
        severity="critical",
        ref='{"external_id": "G2"}',
    )
    selected = _ids(conn, Scope())
    assert admin in selected and lone_admin in selected
    assert entity not in selected
    assert issue_selection.SEVERITIES[0] == "critical"
    # The other record stays reachable as related evidence of its representative.
    assert _ids(conn, Scope(related_to=str(admin))) == {entity}


def test_covered_findings_are_related_issues_not_independent_work(conn):
    parent = _finding(conn, 3)
    child = _finding(conn, 4, severity="high", attention="covered", covered_by=[parent])
    assert parent in _ids(conn, Scope())
    assert child not in _ids(conn, Scope())
    assert _ids(conn, Scope(related_to=str(parent))) == {child}


def test_open_paused_and_resolved_are_disjoint(conn):
    open_id = _finding(conn, 3)
    paused = _finding(conn, 3, paused=True)
    resolved = _finding(conn, 3, status="resolved")
    acknowledged = _finding(conn, 3, status="acknowledged")
    assert {open_id, acknowledged} <= _ids(conn, Scope(status="open"))
    assert paused not in _ids(conn, Scope(status="open"))
    assert paused in _ids(conn, Scope(status="paused"))
    assert open_id not in _ids(conn, Scope(status="paused"))
    assert _ids(conn, Scope(status="resolved")) >= {resolved}
    assert resolved not in _ids(conn, Scope(status="open")) | _ids(conn, Scope(status="paused"))


def test_pending_candidates_are_open_work_of_their_registered_type(conn):
    candidate = uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.entity_candidates VALUES (%s, 1, 'pending', NULL, now(), 'X1', 'device')",
        [candidate],
    )
    conn.execute(
        "INSERT INTO operations.entity_candidates VALUES (%s, 1, 'observed_only', NULL, now(), 'X2', 'device')",
        [uuid.uuid4()],
    )
    rows = _run(
        conn,
        Scope(types=("identity_resolution_pending",)),
        "SELECT id, severity, kind FROM selected",
    )
    assert rows == [(candidate, "low", "candidate")]
    assert candidate not in _ids(conn, Scope(status="paused"))


def test_unassigned_client_is_client_work_without_one_not_fleet_work(conn):
    entity, admin = _source_group(conn, 4, "G3")
    device_issue = _finding(conn, 3)
    software = _finding(conn, 6, subject_type="software_product")
    unassigned = _ids(conn, Scope(client=issue_selection.CLIENT_UNASSIGNED))
    assert {admin, device_issue} <= unassigned
    assert software not in unassigned


def test_computer_filters_apply_to_computer_issues_only(conn):
    device = uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.devices VALUES (%s, 1, 'PC-1', NULL, 'Windows 11 Pro', 'workstation')",
        [device],
    )
    on_device = _finding(conn, 3, subject=device)
    elsewhere = _finding(conn, 3)
    software = _finding(conn, 6, subject_type="software_product")
    selected = _ids(conn, Scope(os="Windows 11 Pro", computer_type="workstation"))
    assert on_device in selected
    assert elsewhere not in selected and software not in selected
    assert _ids(conn, Scope(q="pc-1")) >= {on_device}


def test_device_scope_includes_inherited_software_issues(conn):
    device = uuid.uuid4()
    direct = _finding(conn, 3, subject=device)
    software = _finding(conn, 6, subject_type="software_product")
    unrelated = _finding(conn, 6, subject_type="software_product")
    conn.execute(
        "INSERT INTO operations.v_device_software_exposure VALUES (1, %s, NULL, %s)",
        [software, device],
    )
    assert _ids(conn, Scope(device_id=str(device))) == {direct, software}
    assert unrelated not in _ids(conn, Scope(device_id=str(device)))
