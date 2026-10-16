"""Migration 0309 on a real PostgreSQL: identity decisions, split and confirm-separate.

Every operation runs (the SQL and the RunPython step) against production
column types, NOT NULL definitions and the decision validation trigger
(read 2026-10-16), after 0306 and 0308.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import FINDING_TYPES_SCHEMA, _SchemaEditor
from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer, _observation

DECISIONS = """
CREATE TABLE operations.operator_decision_dimensions (
    name varchar(80) PRIMARY KEY, entity_type varchar(16) NOT NULL,
    value_type varchar(16) NOT NULL, allowed_values jsonb NULL, description text NOT NULL,
    enabled boolean NOT NULL
);
INSERT INTO operations.operator_decision_dimensions VALUES
    ('exemptions', 'device', 'json', NULL, 'existing', true);
CREATE TABLE operations.device_operator_decisions (
    version integer NOT NULL CHECK (version >= 0), id uuid PRIMARY KEY,
    dimension varchar(80) NOT NULL, value jsonb NOT NULL, reason text NOT NULL,
    set_by varchar(120) NOT NULL, set_at timestamptz NOT NULL, tenant_id bigint NOT NULL,
    device_id uuid NOT NULL REFERENCES operations.devices(id) DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (tenant_id, device_id, dimension)
);
ALTER TABLE operations.device_operator_decisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.device_operator_decisions
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
CREATE FUNCTION operations.validate_operator_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dim operations.operator_decision_dimensions%ROWTYPE;
BEGIN
    SELECT * INTO dim FROM operations.operator_decision_dimensions WHERE name = NEW.dimension;
    IF NOT FOUND THEN RAISE EXCEPTION 'Unknown operator decision dimension: %', NEW.dimension; END IF;
    IF NOT dim.enabled THEN RAISE EXCEPTION 'disabled: %', NEW.dimension; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_validate_operator_decision BEFORE INSERT OR UPDATE
    ON operations.device_operator_decisions
    FOR EACH ROW EXECUTE FUNCTION operations.validate_operator_decision();
"""

EXISTING_TYPES = """
INSERT INTO operations.finding_types (name, default_severity, runbook_path, description,
    finding_class, source_module, auto_resolvable, subject_scope, suppressed_by_approval,
    drilldown_evidence_key, concern_signal, default_decision_scope, alertable, display_name,
    issue_category, issue_group, sort_order, covered_by, cover_note)
SELECT n, 'medium', '', 'old', 'entity', 'identity', true, 'device', false, '', false, 'global',
       false, n, 'Inventory', 'Duplicate computers', 50, '[]', ''
  FROM unnest(ARRAY['duplicate_device_records', 'identity_conflict', 'shared_serial']) n;
CREATE TABLE operations.admin_findings (
    version integer NOT NULL, id uuid PRIMARY KEY, condition_key varchar(255) NOT NULL,
    severity varchar(16) NOT NULL, status varchar(24) NOT NULL, subject_ref jsonb NOT NULL,
    details jsonb NOT NULL, first_detected_at timestamptz NOT NULL,
    last_detected_at timestamptz NOT NULL, resolved_at timestamptz NULL,
    finding_type_id smallint NOT NULL, tenant_id bigint NOT NULL
);
INSERT INTO operations.finding_types (name, default_severity, runbook_path, description,
    finding_class, source_module, auto_resolvable, subject_scope, suppressed_by_approval,
    drilldown_evidence_key, concern_signal, default_decision_scope, alertable, display_name,
    issue_category, issue_group, sort_order, covered_by, cover_note)
VALUES ('duplicate_platform_record', 'high', '', 'old', 'admin', 'evaluator', true, 'device',
        false, '', false, 'global', false, 'Duplicate record', 'Inventory', 'x', 1, '[]', '');
INSERT INTO operations.admin_findings
SELECT 1, gen_random_uuid(), k, 'high', s, '{}', '{"record_count": 2}', now(), now(), NULL,
       (SELECT id FROM operations.finding_types WHERE name = 'duplicate_platform_record'), 1
  FROM (VALUES ('duplicate_record:Ninja:agent.rmm:c:pc', 'open'),
               ('duplicate_platform_record:d:Ninja:agent.rmm:', 'open'),
               ('duplicate_record:Ninja:agent.rmm:c:old', 'resolved')) v(k, s);
CREATE FUNCTION operations.compute_finding_state(p_ids uuid[])
RETURNS TABLE(finding_id uuid) LANGUAGE sql STABLE AS $$ SELECT unnest(p_ids) $$;
UPDATE operations.condition_policy_versions SET policy = jsonb_set(policy, '{definitions}',
    '[{"name": "duplicate_device_records", "rules": ["parent_open"], "lifecycle": "historical"},
      {"name": "shared_serial", "rules": ["parent_open"], "lifecycle": "active"}]');
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
            connection.execute(FOUNDATION_SCHEMA)
            connection.execute(TABLES)
            connection.execute(DECISIONS)
            connection.execute(FINDING_TYPES_SCHEMA)
            connection.execute(EXISTING_TYPES)
            for name in (
                "0306_change_history_foundation",
                "0308_computer_merge_and_split",
            ):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(
                        getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL
                    )
            migration = importlib.import_module("apps.core.migrations.0309_identity_findings_and_split")
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(migration.FORWARD_SQL)
            migration.register_finding_type(None, _SchemaEditor(connection))
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def test_the_migration_registers_types_dimensions_and_policy(conn):
    row = conn.execute(
        """SELECT finding_class, alertable, covered_by, cover_note, issue_group
             FROM operations.finding_types WHERE name = 'two_machines_on_one_computer'"""
    ).fetchone()
    assert row == ("entity", False, [], "", "Computer identity")
    assert conn.execute(
        "SELECT display_name FROM operations.finding_types WHERE name = 'duplicate_device_records'"
    ).fetchone()[0] == "Computers that look like one machine"
    lifecycles = {
        d["name"]: d["lifecycle"]
        for d in conn.execute(
            "SELECT policy->'definitions' FROM operations.condition_policy_versions WHERE active"
        ).fetchone()[0]
    }
    assert lifecycles == {
        "duplicate_device_records": "active",
        "shared_serial": "active",
        "two_machines_on_one_computer": "active",
    }
    assert {
        r[0]
        for r in conn.execute(
            "SELECT name FROM operations.operator_decision_dimensions WHERE name LIKE 'identity_%'"
        ).fetchall()
    } == {"identity_separate", "identity_excluded_records"}


def test_finding_state_computation_runs_without_jit(conn):
    assert conn.execute(
        "SELECT proconfig FROM pg_proc WHERE oid = 'operations.compute_finding_state(uuid[])'::regprocedure"
    ).fetchone()[0] == ["jit=off"]


def test_old_keyed_duplicate_record_findings_are_closed_with_the_reason(conn):
    rows = dict(
        conn.execute(
            "SELECT condition_key, status || ':' || coalesce(details->>'resolved_reason', '') "
            "FROM operations.admin_findings"
        ).fetchall()
    )
    assert rows["duplicate_record:Ninja:agent.rmm:c:pc"].startswith("resolved:Replaced by")
    assert rows["duplicate_platform_record:d:Ninja:agent.rmm:"] == "open:"
    assert rows["duplicate_record:Ninja:agent.rmm:c:old"] == "resolved:"


def test_split_records_the_decision_and_detaches_only_the_chosen_records(conn):
    device = _computer(conn, "pc-split")
    keep = _observation(conn, device, "Ninja")
    split = _observation(conn, device, "SentinelOne")
    key = conn.execute(
        "SELECT entity_key FROM operations.entity_observation_current WHERE observation_id = %s",
        (split,),
    ).fetchone()[0]
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        detached = conn.execute(
            "SELECT operations.split_computer_records(%s, %s, 'two machines', 7)",
            (device, [split]),
        ).fetchone()[0]
    assert detached == 1
    owners = dict(
        conn.execute(
            "SELECT observation_id, device_id FROM operations.entity_observation_current "
            "WHERE observation_id = ANY(%s)",
            ([keep, split],),
        ).fetchall()
    )
    assert owners == {keep: device, split: None}
    value, set_by = conn.execute(
        """SELECT value, set_by FROM operations.device_operator_decisions
            WHERE device_id = %s AND dimension = 'identity_excluded_records'""",
        (device,),
    ).fetchone()
    assert value == [f"SentinelOne|{key}"] and set_by == "user:7"
    assert conn.execute(
        """SELECT a.action, a.explicit FROM operations.device_operator_decisions_change_history h
             JOIN operations.change_actions a ON a.id = h.action_id
            WHERE h.entity_key IS NOT NULL ORDER BY h.id DESC LIMIT 1"""
    ).fetchone() == ("computer.split_records", True)
    # Records that are not on the Computer are refused.
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute(
            "SELECT operations.split_computer_records(%s, %s, 'again')", (device, [split])
        )


def test_confirm_separate_records_each_computer_against_the_others(conn):
    a, b, c = (_computer(conn, "pc-same") for _ in range(3))
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        assert conn.execute(
            "SELECT operations.confirm_computers_separate(%s, 'different desks', 7)", ([a, b],)
        ).fetchone()[0] == 2
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute(
            "SELECT operations.confirm_computers_separate(%s, 'also different', 7)", ([a, c],)
        )
    values = dict(
        conn.execute(
            """SELECT device_id, value FROM operations.device_operator_decisions
                WHERE dimension = 'identity_separate' AND device_id = ANY(%s)""",
            ([a, b, c],),
        ).fetchall()
    )
    assert sorted(values[a]) == sorted([str(b), str(c)])
    assert values[b] == [str(a)] and values[c] == [str(a)]
    other_client = _computer(conn, "pc-same", client=uuid.uuid4())
    with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
        conn.execute("SELECT operations.confirm_computers_separate(%s, 'x')", ([a, other_client],))


def test_the_resolver_and_the_issue_actions_call_the_functions_as_defined(conn, monkeypatch):
    """The exact statements the callers send, with their parameter types.

    The first automatic merges failed in production because a Json parameter
    and an untyped NULL matched no signature; a fake cursor could not see it.
    """
    from types import SimpleNamespace

    from ingest.identity import resolver

    from apps.core.finding_actions import (
        CONFIRM_COMPUTERS_SEPARATE,
        MERGE_COMPUTERS,
        SPLIT_COMPUTER_RECORDS,
    )
    from apps.core.identity_actions import _apply

    survivor, absorbed = _computer(conn, "pc-call"), _computer(conn, "pc-call")
    monkeypatch.setattr(
        resolver, "planned_proven_merges", lambda cur: [(survivor, absorbed, "serial", "abc123")]
    )
    with conn.transaction(), conn.cursor() as cur:
        assert resolver.merge_proven_splits(cur) == 1
    assert conn.execute(
        "SELECT count(*) FROM operations.computer_merges WHERE absorbed_id = %s", (absorbed,)
    ).fetchone()[0] == 1

    a, b = _computer(conn, "pc-op"), _computer(conn, "pc-op")
    split_record = _observation(conn, a, "LogMeIn")
    finding = SimpleNamespace(
        id=uuid.uuid4(),
        subject_id=a,
        finding_details={
            "computers": [{"device_id": str(b)}],
            "proposed_split_observation_ids": [str(split_record)],
        },
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE operations_app")
        _apply(cur, finding, SPLIT_COMPUTER_RECORDS, "two machines", 7)
        _apply(cur, finding, CONFIRM_COMPUTERS_SEPARATE, "different desks", 7)
    c, d = _computer(conn, "pc-m"), _computer(conn, "pc-m")
    merge = SimpleNamespace(
        id=uuid.uuid4(), subject_id=c, finding_details={"computers": [{"device_id": str(d)}]}
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE operations_app")
        assert _apply(cur, merge, MERGE_COMPUTERS, "same machine", 7) == "Merged 1 Computer."


def test_ingest_cannot_call_the_operator_actions(conn):
    device = _computer(conn, "pc-ingest")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("SET LOCAL ROLE ninja_ingest")
        conn.execute("SELECT operations.split_computer_records(%s, %s, 'x')", (device, []))
