"""The Issues selection contract on a real PostgreSQL (PLAN-003 R3).

Tables carry only the columns the selection reads, with production types. The
selection SQL is executed as built by ``issue_selection._filtered_sql``.
"""

from __future__ import annotations

import os
import uuid
from collections import Counter
from types import SimpleNamespace
from urllib.parse import urlencode

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
CREATE TABLE operations.source_record_subjects (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, observation_id uuid
);
CREATE FUNCTION operations.computer_client_independent_evidence(bigint, uuid)
RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$;
CREATE TABLE operations.computer_client_ownership (
    tenant_id bigint NOT NULL, device_id uuid NOT NULL,
    effective_client_id uuid, state text NOT NULL
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
ALTER TABLE operations.finding_types ADD COLUMN issue_category text NOT NULL DEFAULT 'Inventory';
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


def test_snooze_at_the_current_boundary_is_open(conn):
    issue = _finding(conn, 3, paused=True)
    conn.execute("UPDATE operations.findings SET snoozed_until = now() WHERE id = %s", [issue])
    assert issue in _ids(conn, Scope(status="open"))
    assert issue not in _ids(conn, Scope(status="paused"))


def test_shared_action_selects_before_excluding_a_covered_representative(conn):
    entity, admin = _source_group(conn, 7, "covered-shared")
    conn.execute(
        "INSERT INTO operations.finding_state VALUES (%s, 1, 'covered', ARRAY[]::uuid[])",
        [admin],
    )
    assert entity not in _ids(conn, Scope())
    assert admin not in _ids(conn, Scope())
    # Filtering by type happens before choosing the action representative.
    assert entity in _ids(conn, Scope(types=("unmatched_source_group",)))


def test_home_totals_deduplicate_clients_and_subjects(conn, monkeypatch):
    client, subject = uuid.uuid4(), uuid.uuid4()
    _finding(conn, 3, client=client, subject=subject)
    _finding(conn, 3, client=client, subject=subject)
    _finding(conn, 3, client=None)
    _finding(conn, 3, paused=True)
    monkeypatch.setattr(issue_selection, "connection", SimpleNamespace(cursor=conn.cursor))
    monkeypatch.setattr(issue_selection, "mapping_types", lambda: ())
    monkeypatch.setattr(issue_selection, "reverse", lambda *_args, **_kwargs: "/findings/")
    monkeypatch.setattr(issue_selection.finding_registry, "finding_type_name", lambda name: name)
    monkeypatch.setattr(
        issue_selection.finding_registry,
        "build_taxonomy",
        lambda: ([{"label": "Inventory", "types": {"device_offline"}}], {}),
    )

    summary, attention = issue_selection.home_data()

    assert summary["open_actions"] == 3
    assert summary["paused_actions"] == 1
    assert len(attention) == 1
    assert attention[0]["count"] == 3
    assert attention[0]["clients"] == 1
    assert attention[0]["subjects"] == 2


def test_home_software_category_counts_open_independent_actions(conn, monkeypatch):
    conn.execute("UPDATE operations.finding_types SET issue_category = 'Software & security' WHERE id = 3")
    _finding(conn, 3, severity="critical")
    _finding(conn, 3, severity="medium")
    _finding(conn, 3, paused=True)
    _finding(conn, 3, attention="covered")
    monkeypatch.setattr(issue_selection, "connection", SimpleNamespace(cursor=conn.cursor))
    monkeypatch.setattr(issue_selection, "mapping_types", lambda: ())
    monkeypatch.setattr(issue_selection, "reverse", lambda *_args, **_kwargs: "/findings/")
    monkeypatch.setattr(issue_selection.finding_registry, "finding_type_name", lambda name: name)
    monkeypatch.setattr(
        issue_selection.finding_registry,
        "build_taxonomy",
        lambda: ([{"label": "Software & security", "types": {"device_offline"}}], {}),
    )

    summary, _ = issue_selection.home_data()

    assert summary["categories"]["Software & security"] == {
        "open_actions": 2,
        "paused_actions": 1,
        "critical_actions": 1,
    }


def test_home_shared_critical_count_uses_critical_representative(conn, monkeypatch):
    entity, admin = _source_group(conn, 8, "mixed-severity")
    conn.execute("UPDATE operations.findings SET severity = 'medium' WHERE id = %s", [admin])
    monkeypatch.setattr(issue_selection, "connection", SimpleNamespace(cursor=conn.cursor))
    monkeypatch.setattr(
        issue_selection, "mapping_types", lambda: ("unmatched_source_group", "client_unattached_group")
    )
    monkeypatch.setattr(issue_selection, "reverse", lambda *_args, **_kwargs: "/findings/")
    monkeypatch.setattr(issue_selection.finding_registry, "finding_type_name", lambda name: name)
    monkeypatch.setattr(
        issue_selection.finding_registry,
        "build_taxonomy",
        lambda: ([{"label": "Inventory", "types": {"unmatched_source_group", "client_unattached_group"}}], {}),
    )

    summary, attention = issue_selection.home_data()

    assert summary["open_actions"] == 1
    assert summary["critical_actions"] == 1
    assert summary["mapping_actions"] == 1
    assert {item["type_name"] for item in attention} == {
        "unmatched_source_group", "client_unattached_group"
    }
    assert entity in _ids(conn, Scope(severity="critical"))
    assert admin not in _ids(conn, Scope(severity="critical"))


def test_home_includes_pending_candidates_and_exact_snooze_expiry(conn, monkeypatch):
    client = uuid.uuid4()
    issue = _finding(conn, 3, client=client, paused=True)
    candidate = uuid.uuid4()
    conn.execute(
        "INSERT INTO operations.entity_candidates VALUES (%s, 1, 'pending', %s, now(), 'X1', 'device')",
        [candidate, client],
    )
    monkeypatch.setattr(issue_selection, "connection", SimpleNamespace(cursor=conn.cursor))
    monkeypatch.setattr(issue_selection, "mapping_types", lambda: ())
    monkeypatch.setattr(issue_selection, "reverse", lambda *_args, **_kwargs: "/findings/")
    monkeypatch.setattr(issue_selection.finding_registry, "finding_type_name", lambda name: name)
    monkeypatch.setattr(
        issue_selection.finding_registry,
        "build_taxonomy",
        lambda: ([{"label": "Inventory", "types": {"device_offline", "identity_resolution_pending"}}], {}),
    )

    paused, _ = issue_selection.home_data()
    conn.execute("UPDATE operations.findings SET snoozed_until = now() WHERE id = %s", [issue])
    expired, attention = issue_selection.home_data()

    assert (paused["open_actions"], paused["paused_actions"]) == (1, 1)
    assert (expired["open_actions"], expired["paused_actions"]) == (2, 0)
    candidate_item = next(item for item in attention if item["type_name"] == "identity_resolution_pending")
    assert (candidate_item["count"], candidate_item["clients"], candidate_item["subjects"]) == (1, 1, 1)


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


def _reference_home_actions(conn, scope):
    """Use the ordinary queue's full ranking, independent of compact Home SQL."""
    sql, params = issue_selection._filtered_sql(scope, summary=True)
    return conn.execute(
        sql
        + """
        SELECT selected.type_name, selected.status, selected.severity, selected.kind,
               selected.subject_type, selected.subject_id,
               COALESCE(f.client_id, c.client_id) AS recorded_client
        FROM selected
        LEFT JOIN operations.findings f
          ON selected.kind = 'finding' AND f.id = selected.id AND f.tenant_id = %(tenant)s
        LEFT JOIN operations.entity_candidates c
          ON selected.kind = 'candidate' AND c.id = selected.id AND c.tenant_id = %(tenant)s
        """,
        params,
    ).fetchall()


def _reference_home(conn, mapping, categories, groups, limit):
    """Assemble the Home contract from separately scoped ordinary queue reads."""
    type_categories = {
        name: category["label"] for category in categories for name in category["types"]
    }
    type_groups = {name: key for key, group in groups.items() for name in group["types"]}
    selected = _reference_home_actions(conn, Scope(status="open_paused"))
    critical = _reference_home_actions(conn, Scope(severity="critical"))
    critical_mapping = _reference_home_actions(conn, Scope(severity="critical", types=mapping))
    totals = {
        "open_actions": sum(row[1] == "open" for row in selected),
        "paused_actions": sum(row[1] == "paused" for row in selected),
        "critical_actions": len(critical),
        "mapping_actions": len(critical_mapping),
        "mapping_clients": len({row[6] for row in critical_mapping if row[6] is not None}),
        "categories": {},
    }
    for category in categories:
        rows = [row for row in selected if row[0] in category["types"]]
        totals["categories"][category["label"]] = {
            "open_actions": sum(row[1] == "open" for row in rows),
            "paused_actions": sum(row[1] == "paused" for row in rows),
            "critical_actions": sum(row[0] in category["types"] for row in critical),
        }
    severity = {name: number for number, name in enumerate(issue_selection.SEVERITIES)}
    attention = []
    for name, category_name in type_categories.items():
        rows = _reference_home_actions(conn, Scope(types=(name,)))
        if not rows:
            continue
        clients = len({row[6] for row in rows if row[6] is not None})
        subjects = len({(row[4], row[5]) for row in rows if row[5] is not None})
        subjects += sum(row[3] == "candidate" for row in rows)
        attention.append(
            {
                "type_name": name,
                "category": category_name,
                "label": name,
                "severity": min((row[2] for row in rows), key=severity.get),
                "count": len(rows),
                "clients": clients,
                "subjects": subjects,
                "href": "/findings/?"
                + urlencode({"type": type_groups.get(name, name), "issue": name}),
                "affected": (
                    f"{subjects:,} affected · {clients:,} recorded client{'s' if clients != 1 else ''}"
                    if clients
                    else f"{subjects:,} affected"
                ),
            }
        )
    attention.sort(
        key=lambda row: (
            severity[row["severity"]],
            -row["clients"],
            -row["count"],
            row["type_name"],
        )
    )
    return totals, attention[:limit]


def _home_contract(monkeypatch, conn, mapping):
    categories = [
        {
            "label": "Inventory",
            "types": {
                "unmatched_source_group",
                "client_unattached_group",
                "device_offline",
                "identity_resolution_pending",
            },
        },
        {"label": "Patching & support", "types": {"missing_required_platform"}},
        {"label": "Software & security", "types": {"rare_recent"}},
    ]
    groups = {
        "client_mapping": {
            "types": {
                "unmatched_source_group",
                "client_unattached_group",
            }
        }
    }
    for category in categories:
        conn.execute(
            "UPDATE operations.finding_types SET issue_category = %s WHERE name = ANY(%s)",
            (category["label"], list(category["types"])),
        )
    monkeypatch.setattr(issue_selection, "connection", SimpleNamespace(cursor=conn.cursor))
    monkeypatch.setattr(issue_selection, "mapping_types", lambda: mapping)
    monkeypatch.setattr(issue_selection, "reverse", lambda *_args, **_kwargs: "/findings/")
    monkeypatch.setattr(issue_selection.finding_registry, "finding_type_name", lambda name: name)
    monkeypatch.setattr(
        issue_selection.finding_registry, "build_taxonomy", lambda: (categories, groups)
    )
    return categories, groups


@pytest.mark.parametrize("covered_admin", (False, True))
@pytest.mark.parametrize(
    "mapping",
    (
        (),
        ("unmatched_source_group",),
        ("unmatched_source_group", "client_unattached_group"),
    ),
)
def test_compact_home_matches_queue_scopes_and_recorded_associations(
    conn,
    monkeypatch,
    covered_admin,
    mapping,
):
    categories, groups = _home_contract(monkeypatch, conn, mapping)
    client, other_client, subject = (uuid.uuid4() for _ in range(3))
    entity, admin = _source_group(conn, 20, "mixed-critical")
    conn.execute("UPDATE operations.findings SET client_id = %s WHERE id = %s", (client, entity))
    conn.execute(
        "UPDATE operations.findings SET client_id = %s, severity = 'medium' WHERE id = %s",
        (other_client, admin),
    )
    _, representative = _source_group(conn, 21, "covered-representative")
    if covered_admin:
        conn.execute(
            "INSERT INTO operations.finding_state VALUES (%s, 1, 'covered', '{}')",
            (representative,),
        )
    _, paused = _source_group(conn, 22, "split-status")
    conn.execute(
        "UPDATE operations.findings SET snoozed_until = now() + interval '1 day' WHERE id = %s",
        (paused,),
    )
    for level in ("critical", "high", "medium", "low", "info"):
        _finding(conn, 3, severity=level, subject=subject, client=client)
    _finding(conn, 3, paused=True)
    _finding(conn, 3, severity="critical", attention="covered")
    _finding(conn, 3, severity="critical", status="resolved")
    _finding(conn, 4, severity="high", status="acknowledged", client=client, subject=subject)
    _finding(conn, 4, severity="critical", client=client, subject=subject)
    # Home retains recorded client attribution even when live ownership is absent.
    _finding(conn, 6, severity="high", client=other_client, subject_type="source_record")
    for status in ("pending", "pending", "observed_only"):
        conn.execute(
            "INSERT INTO operations.entity_candidates VALUES (%s, 1, %s, %s, now(), 'X', 'device')",
            (uuid.uuid4(), status, client),
        )
    for limit in (0, 2, 20):
        actual = issue_selection.home_data(attention_limit=limit)
        assert actual == _reference_home(conn, mapping, categories, groups, limit)
        assert len({item["type_name"] for item in actual[1]}) == len(actual[1])
    # The ordinary queue still retains distinct non-shared action identities.
    assert Counter(row[0] for row in _reference_home_actions(conn, Scope()))["device_offline"] == 5


def test_compact_home_empty_population_preserves_zero_category_totals(conn, monkeypatch):
    mapping = ("unmatched_source_group", "client_unattached_group")
    categories, groups = _home_contract(monkeypatch, conn, mapping)
    assert issue_selection.home_data() == _reference_home(conn, mapping, categories, groups, 6)


def test_compact_home_restricted_role_cannot_count_other_tenant_work(conn, monkeypatch):
    mapping = ("unmatched_source_group", "client_unattached_group")
    _home_contract(monkeypatch, conn, mapping)
    _finding(conn, 3, severity="critical")
    hidden = _finding(conn, 3, severity="critical")
    conn.execute("UPDATE operations.findings SET tenant_id = 2 WHERE id = %s", (hidden,))
    conn.execute(
        "INSERT INTO operations.entity_candidates VALUES (%s, 2, 'pending', NULL, now(), 'hidden', 'device')",
        (uuid.uuid4(),),
    )
    expected = issue_selection.home_data()
    conn.execute("CREATE ROLE operations_home_test NOLOGIN")
    conn.execute("GRANT USAGE ON SCHEMA operations TO operations_home_test")
    conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA operations TO operations_home_test")
    for table in ("findings", "finding_state", "source_bindings", "entity_candidates"):
        conn.execute(f"ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY")
        conn.execute(
            f"CREATE POLICY home_tenant ON operations.{table} "
            "USING (tenant_id = current_setting('operations.tenant_id')::bigint)"
        )
    conn.execute("SET LOCAL operations.tenant_id = 1")
    conn.execute("SET LOCAL ROLE operations_home_test")
    assert issue_selection.home_data() == expected
    conn.execute("RESET ROLE")
