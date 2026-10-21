"""Migration 0333 on a real PostgreSQL: requirement applicability (ADR-0036).

Runs 0332 then 0333 against the production ``finding_types`` columns and role
attributes. ``begin_change`` and ``refresh_finding_state`` are recording stubs
with the production signatures; ``finding_state`` holds the attention the
drift check reads.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import FINDING_TYPES_SCHEMA

M0332 = "apps.core.migrations.0332_device_requirement_state"
M0333 = "apps.core.migrations.0333_requirement_applicability"

SCHEMA = """
CREATE ROLE operations_migrate NOLOGIN SUPERUSER BYPASSRLS;
CREATE ROLE operations_app NOLOGIN;
CREATE ROLE operations_readonly NOLOGIN;
CREATE ROLE ninja_ingest NOLOGIN;
CREATE ROLE metabase_ro NOLOGIN;
CREATE SCHEMA operations;
GRANT USAGE ON SCHEMA operations TO operations_app, operations_readonly, ninja_ingest;
CREATE TABLE operations.change_history_registry (
    table_name text PRIMARY KEY, classification text NOT NULL, reason text NOT NULL,
    recorded_columns text[] NOT NULL, secret_columns text[] NOT NULL, key_columns text[] NOT NULL,
    computer_column text NULL, computer_condition_column text NULL,
    computer_condition_value text NULL, client_column text NULL, is_global boolean NOT NULL,
    capture text NULL, enforce_action boolean NOT NULL DEFAULT false
);
CREATE TABLE operations.findings (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, finding_type_id smallint NOT NULL,
    subject_type varchar(32) NOT NULL, subject_id uuid NOT NULL,
    finding_details jsonb NOT NULL DEFAULT '{}', status varchar(16) NOT NULL
);
CREATE TABLE operations.finding_state (
    finding_id uuid PRIMARY KEY, tenant_id bigint NOT NULL, finding_type_id smallint NOT NULL,
    attention text, reason text NOT NULL DEFAULT '', computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE operations.calls (fn text, arg text);
CREATE FUNCTION operations.begin_change(
    p_action text, p_reason text, p_evidence jsonb, p_actor_kind text, p_actor_id bigint,
    p_process text, p_process_version text, p_tenant_id bigint, p_explicit boolean
) RETURNS uuid LANGUAGE sql AS $$
    INSERT INTO operations.calls VALUES ('begin_change', p_action);
    SELECT gen_random_uuid();
$$;
CREATE FUNCTION operations.refresh_finding_state(p_ids uuid[]) RETURNS integer LANGUAGE sql AS $$
    INSERT INTO operations.calls
    SELECT 'refresh', current_setting('operations.tenant_id', true) || ':' || coalesce(cardinality(p_ids), 0);
    SELECT coalesce(cardinality(p_ids), 0);
$$;
"""

TYPES = """
INSERT INTO operations.finding_types (
    name, default_severity, finding_class, source_module, subject_scope,
    creates_device_exposure, auto_resolvable, suppressed_by_approval, concern_signal,
    default_decision_scope, drilldown_evidence_key, runbook_path, description, display_name,
    issue_category, issue_group, sort_order, alertable, covered_by, cover_note
) VALUES
    ('missing_required_platform', 'high', 'entity', 'evaluator', 'device', TRUE, TRUE, FALSE,
     FALSE, 'global', '', '', 'd', 'Required agent not installed', 'Agents & reporting',
     'Coverage', 10, TRUE, '["device_missing_from_source"]', 'n'),
    ('stale_required_platform', 'medium', 'entity', 'evaluator', 'device', TRUE, TRUE, FALSE,
     FALSE, 'global', '', '', 'd', 'Required agent stale', 'Agents & reporting', 'Coverage',
     20, TRUE, '["device_offline", "device_missing_from_source"]', 'n'),
    ('os_unknown_coverage', 'medium', 'entity', 'evaluator', 'device', FALSE, TRUE, FALSE,
     FALSE, 'global', '', '', 'd', 'Operating system unknown: coverage not evaluated',
     'Agents & reporting', 'Coverage', 40, FALSE, '["device_missing_from_source"]', 'n');
"""

DEVICE = uuid.UUID("00000000-0000-4000-8000-0000000000d1")


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
            connection.execute(FINDING_TYPES_SCHEMA.split("CREATE TABLE operations.condition_policy_versions")[0])
            connection.execute(TYPES)
            connection.execute("SET ROLE operations_migrate")
            connection.execute(importlib.import_module(M0332).FORWARD_SQL)
            connection.execute(
                "INSERT INTO operations.device_requirement_state "
                "(tenant_id, device_id, entity_type, platform, verdict) "
                "VALUES (1, %s, 'agent.rmm', 'Ninja', 'not_evaluated')",
                (DEVICE,),
            )
            with connection.transaction():
                connection.execute(importlib.import_module(M0333).FORWARD_SQL)
            connection.execute("RESET ROLE")
            yield connection


def test_not_evaluated_becomes_os_unknown_and_the_new_verdicts_are_allowed(conn):
    assert conn.execute(
        "SELECT verdict FROM operations.device_requirement_state WHERE device_id = %s", (DEVICE,)
    ).fetchone() == ("os_unknown",)
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            "UPDATE operations.device_requirement_state SET verdict = 'not_evaluated'"
        )
    with conn.transaction():
        conn.execute(
            "UPDATE operations.device_requirement_state SET verdict = 'pending_cleanup'"
        )
        raise psycopg.Rollback()


def test_findings_that_stop_applying_are_covered_and_the_os_finding_is_reworded(conn):
    rows = dict(conn.execute(
        "SELECT name, covered_by FROM operations.finding_types ORDER BY name"
    ).fetchall())
    for name in ("missing_required_platform", "stale_required_platform"):
        assert {"device_offline", "os_unknown_coverage"} <= set(rows[name])
        assert "device_missing_from_source" in rows[name]
    assert rows["os_unknown_coverage"] == ["device_missing_from_source"]
    assert conn.execute(
        "SELECT display_name FROM operations.finding_types WHERE name = 'os_unknown_coverage'"
    ).fetchone() == ("Operating system unknown: agent requirements not applied",)
    assert conn.execute("SELECT fn, arg FROM operations.calls ORDER BY fn").fetchall() == [
        ("begin_change", "finding_type.cover"),
        ("refresh", "1:0"),
    ]


def test_a_covered_finding_next_to_a_not_applied_verdict_is_not_drift(conn):
    missing_type = conn.execute(
        "SELECT id FROM operations.finding_types WHERE name = 'missing_required_platform'"
    ).fetchone()[0]
    covered, uncovered = uuid.uuid4(), uuid.uuid4()
    other = uuid.uuid4()
    details = json.dumps({"entity_type": "agent.rmm", "platform": "Ninja"})
    conn.execute(
        "INSERT INTO operations.findings VALUES (%s, 1, %s, 'device', %s, %s, 'open'), "
        "(%s, 1, %s, 'device', %s, %s, 'open')",
        (covered, missing_type, DEVICE, details, uncovered, missing_type, other, details),
    )
    conn.execute(
        "INSERT INTO operations.device_requirement_state "
        "(tenant_id, device_id, entity_type, platform, verdict) "
        "VALUES (1, %s, 'agent.rmm', 'Ninja', 'pending_cleanup')",
        (other,),
    )
    conn.execute(
        "INSERT INTO operations.finding_state (finding_id, tenant_id, finding_type_id, attention) "
        "VALUES (%s, 1, %s, 'covered'), (%s, 1, %s, 'needs_action')",
        (covered, missing_type, uncovered, missing_type),
    )
    with conn.transaction():
        conn.execute("SELECT set_config('operations.tenant_id', '1', true)")
        drift = conn.execute(
            "SELECT device_id, disagreement, verdict "
            "FROM operations.device_requirement_state_disagreements(1)"
        ).fetchall()
    # Covered + os_unknown agrees; a finding that is not covered still disagrees.
    assert drift == [(other, "finding_without_verdict", "pending_cleanup")]
