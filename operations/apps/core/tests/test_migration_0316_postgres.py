"""Migration 0316 on a real PostgreSQL: device_source_record_withdrawn is retired.

Both operations run (the SQL and the RunPython policy step) against
production column definitions for findings, finding types and policies.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import (
    FINDING_TYPES_SCHEMA,
    _SchemaEditor,
)
from apps.core.tests.test_migration_0306_postgres import (
    SCHEMA as FOUNDATION_SCHEMA,
)

FINDINGS = """
CREATE TABLE operations.findings (
    id uuid PRIMARY KEY, finding_type_id smallint NOT NULL, status varchar(24) NOT NULL,
    closed_at timestamptz NULL, last_seen_at timestamptz NOT NULL,
    finding_details jsonb NOT NULL, tenant_id bigint NOT NULL
);
INSERT INTO operations.finding_types (name, default_severity, runbook_path, description,
    finding_class, source_module, auto_resolvable, subject_scope, suppressed_by_approval,
    drilldown_evidence_key, concern_signal, default_decision_scope, alertable, display_name,
    issue_category, issue_group, sort_order, covered_by, cover_note)
SELECT n, 'medium', '', 'x', 'entity', 'evaluator', true, 'device', false, '', false,
       'global', false, n, 'Inventory', 'x', 10, '[]', ''
  FROM unnest(ARRAY['device_source_record_withdrawn', 'device_missing_from_source']) n;
UPDATE operations.condition_policy_versions SET policy = jsonb_set(policy, '{definitions}',
    '[{"name": "device_source_record_withdrawn", "rules": ["identity"], "lifecycle": "active"},
      {"name": "device_missing_from_source", "rules": ["identity"], "lifecycle": "active"}]');
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
            connection.execute(FINDING_TYPES_SCHEMA)
            connection.execute(FINDINGS)
            for name, status in (
                ("device_source_record_withdrawn", "open"),
                ("device_source_record_withdrawn", "resolved"),
                ("device_missing_from_source", "open"),
            ):
                connection.execute(
                    """INSERT INTO operations.findings
                       SELECT %s, id, %s, NULL, now(), '{}', 1 FROM operations.finding_types
                        WHERE name = %s""",
                    (uuid.uuid4(), status, name),
                )
            foundation = importlib.import_module(
                "apps.core.migrations.0306_change_history_foundation"
            )
            migration = importlib.import_module(
                "apps.core.migrations.0316_retire_source_record_withdrawn"
            )
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(migration.FORWARD_SQL)
            migration.activate_policy(None, _SchemaEditor(connection))
            yield connection


def test_open_withdrawn_findings_close_with_the_reason_and_others_stay(conn):
    rows = conn.execute(
        """SELECT ft.name, f.status, f.finding_details -> 'resolution' ->> 'reason'
             FROM operations.findings f JOIN operations.finding_types ft ON ft.id = f.finding_type_id
            ORDER BY 1, 2"""
    ).fetchall()
    assert sorted(rows, key=str) == sorted(
        [
            ("device_missing_from_source", "open", None),
            ("device_source_record_withdrawn", "resolved", "finding_type_retired"),
            ("device_source_record_withdrawn", "resolved", None),
        ],
        key=str,
    )


def test_the_policy_marks_the_type_historical(conn):
    active = conn.execute(
        "SELECT version, policy FROM operations.condition_policy_versions WHERE active"
    ).fetchone()
    assert active[0] == "conditions-registry-5"
    lifecycles = {d["name"]: d["lifecycle"] for d in active[1]["definitions"]}
    assert lifecycles == {
        "device_source_record_withdrawn": "historical",
        "device_missing_from_source": "active",
    }
