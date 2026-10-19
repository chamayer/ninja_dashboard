"""Migration 0321 on a real PostgreSQL: os_unknown_coverage gains its cover rule.

Runs the whole RunSQL step against the production ``finding_types`` columns
(2026-10-19); ``begin_change`` and ``refresh_finding_state`` are recording
stubs with the production signatures.
"""

from __future__ import annotations

import importlib
import os

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import FINDING_TYPES_SCHEMA

MODULE = "apps.core.migrations.0321_os_unknown_coverage_cover"

STUBS = """
CREATE TABLE operations.findings (
    id uuid PRIMARY KEY, tenant_id bigint NOT NULL, finding_type_id smallint NOT NULL,
    status varchar(16) NOT NULL
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
INSERT INTO operations.finding_types (
    name, default_severity, finding_class, source_module, subject_scope,
    creates_device_exposure, auto_resolvable, suppressed_by_approval, concern_signal,
    default_decision_scope, drilldown_evidence_key, runbook_path, description, display_name,
    issue_category, issue_group, sort_order, alertable, covered_by, cover_note
) VALUES ('os_unknown_coverage', 'medium', 'entity', 'evaluator', 'device', FALSE, TRUE, FALSE,
          FALSE, 'global', '', '', 'd', 'Operating system unknown: coverage not evaluated',
          'Agents & reporting', 'Coverage', 40, FALSE, '[]', '');
INSERT INTO operations.findings
SELECT gen_random_uuid(), 1, (SELECT id FROM operations.finding_types), s
  FROM unnest(ARRAY['open', 'acknowledged', 'resolved']) s;
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
            connection.execute("CREATE SCHEMA operations")
            connection.execute(FINDING_TYPES_SCHEMA)
            connection.execute(STUBS)
            yield connection


def test_the_cover_rule_is_set_and_open_findings_refreshed(conn):
    module = importlib.import_module(MODULE)
    with conn.transaction():
        conn.execute(module.FORWARD_SQL)
    row = conn.execute(
        "SELECT covered_by, cover_note FROM operations.finding_types "
        "WHERE name = 'os_unknown_coverage'"
    ).fetchone()
    assert row[0] == ["device_missing_from_source"]
    assert row[1]
    assert conn.execute("SELECT fn, arg FROM operations.calls").fetchall() == [
        ("begin_change", "finding_type.cover"),
        ("refresh", "1:2"),
    ]
