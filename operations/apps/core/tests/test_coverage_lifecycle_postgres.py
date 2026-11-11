"""Coverage's Hudu query preserves lifecycle policy and tenant visibility."""

from __future__ import annotations

import ast
import importlib
import os
from collections import Counter
from pathlib import Path

import psycopg
import pytest

from apps.core.computer_reads import current_computer_sql
from apps.core.tests.test_migration_0310_postgres import TABLES

SCHEMA = """
CREATE SCHEMA operations;
CREATE ROLE operations_view_owner NOLOGIN BYPASSRLS;
CREATE ROLE operations_app NOLOGIN;
CREATE ROLE operations_readonly NOLOGIN;
CREATE ROLE ninja_ingest NOLOGIN;
CREATE ROLE metabase_ro NOLOGIN;
GRANT USAGE ON SCHEMA operations TO operations_view_owner, operations_app;
CREATE TABLE operations.devices (
    tenant_id bigint, id uuid, client_id uuid, deleted_at timestamptz,
    lifecycle_status text DEFAULT 'active'
);
CREATE TABLE operations.computer_client_ownership (
    tenant_id bigint, device_id uuid, effective_client_id uuid, state text
);
-- Only the columns consumed by the initial Hudu query; duplicate rows are deliberate.
CREATE TABLE operations.v_hudu_computer_inventory_observation_current (
    tenant_id bigint, observation_id uuid, device_id uuid, client_id uuid,
    hostname text, has_relayed_cards boolean
);
"""

ORIGINAL_JOIN = """LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle
                  ON lifecycle.tenant_id = hudu.tenant_id
                 AND lifecycle.observation_id = hudu.observation_id"""


def _queries():
    """Extract the shipped query without invoking unrelated page phases."""
    source = Path(__file__).resolve().parents[1] / "views.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "fleet_coverage"
    )
    expressions = [
        node.args[0]
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and node.args
        and "v_hudu_computer_inventory_observation_current" in ast.unparse(node.args[0])
    ]
    assert len(expressions) == 1
    # Evaluate only the repository's SQL f-string, with its existing selector.
    query = eval(
        compile(ast.Expression(expressions[0]), str(source), "eval"),
        {"current_computer_sql": current_computer_sql},
    )
    start = query.index("LEFT JOIN LATERAL (")
    end = query.index(") lifecycle ON TRUE", start) + len(") lifecycle ON TRUE")
    original = query[:start] + ORIGINAL_JOIN + query[end:]
    return query, original


@pytest.fixture(scope="module")
def database():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for disposable PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    migration = importlib.import_module(
        "apps.core.migrations.0158_source_record_lifecycle_contract"
    )
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA)
            # Reuse the existing lifecycle fixture's inputs, but install the actual
            # security-barrier view and grants rather than its historical view copy.
            conn.execute(TABLES.split("-- Production view definition", 1)[0])
            conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA operations TO operations_view_owner")
            conn.execute(migration.VIEW_SQL)
            for table in (
                "devices",
                "computer_client_ownership",
                "v_hudu_computer_inventory_observation_current",
            ):
                conn.execute(f"ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY")
                conn.execute(
                    f"CREATE POLICY tenant_scope ON operations.{table} "
                    "USING (tenant_id = operations.current_tenant_id())"
                )
                conn.execute(f"GRANT SELECT ON operations.{table} TO operations_app")
            yield conn


def _id(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def _record(conn, number, *, tenant=1, data="{}", lifecycle=True, copies=1):
    instance, observation, device, client = (_id(number * 10 + n) for n in range(4))
    conn.execute(
        "INSERT INTO operations.source_instances VALUES (%s, '{}', true, 5, %s)",
        (instance, tenant),
    )
    conn.execute(
        "INSERT INTO operations.devices (tenant_id, id, client_id) VALUES (%s, %s, %s)",
        (tenant, device, client),
    )
    conn.execute(
        "INSERT INTO operations.computer_client_ownership VALUES (%s, %s, %s, 'resolved')",
        (tenant, device, client),
    )
    for _ in range(copies):
        conn.execute(
            "INSERT INTO operations.v_hudu_computer_inventory_observation_current "
            "VALUES (%s, %s, %s, %s, %s, true)",
            (tenant, observation, device, client, f"fixture-{number}"),
        )
    if lifecycle:
        conn.execute(
            "INSERT INTO operations.entity_observation_current VALUES "
            "(%s, %s, %s, %s, 'Hudu', 'cmdb.asset', '', %s, true, now(), %s::jsonb)",
            (observation, tenant, device, instance, str(number), data),
        )
    return observation


def _compare(conn, tenant):
    candidate, original = _queries()
    with conn.transaction(force_rollback=True):
        conn.execute("SET LOCAL ROLE operations_app")
        conn.execute("SELECT set_config('operations.tenant_id', %s, true)", (str(tenant),))
        result = conn.execute(candidate).fetchall()
        assert Counter(result) == Counter(conn.execute(original).fetchall())
    return result


@pytest.mark.integration
def test_coverage_lifecycle_policy_and_left_join_parity(database):
    with database.transaction(force_rollback=True):
        _record(database, 1, data='{"archived": true}', copies=2)
        _record(database, 2, data='{"archived": false}')
        _record(database, 3)
        _record(database, 4, lifecycle=False)
        rows = _compare(database, 1)
        assert Counter((row[3], row[4]) for row in rows) == Counter(
            [
                ("fixture-1", True),
                ("fixture-1", True),
                ("fixture-2", False),
                ("fixture-3", False),
                ("fixture-4", None),
            ]
        )
        # An enabled higher-priority rule overrides the archived default; a
        # disabled rule must not win. Recheck after policy edits without new data.
        database.execute(
            """INSERT INTO operations.source_record_lifecycle_mappings
               (source_id, external_namespace, entity_type, canonical_field,
                match_value, lifecycle, counts_as_current_computer_evidence, priority, enabled)
               VALUES (NULL, '', '', 'archived', 'true', 'active', true, 10, true),
                      (5, '', '', 'archived', 'true', 'archived', false, 1, false)"""
        )
        rows = _compare(database, 1)
        assert [row[4] for row in rows if row[3] == "fixture-1"] == [False, False]


@pytest.mark.integration
def test_coverage_lifecycle_tenant_visibility(database):
    with database.transaction(force_rollback=True):
        observation = _record(database, 5, tenant=1, data='{"archived": true}')
        _record(database, 6, tenant=2, data='{"archived": false}')
        _record(database, 7, tenant=2, lifecycle=False)
        # A visible Hudu row cannot acquire another tenant's lifecycle evidence.
        database.execute(
            "UPDATE operations.v_hudu_computer_inventory_observation_current "
            "SET observation_id = %s WHERE hostname = 'fixture-7'",
            (observation,),
        )
        assert [(row[3], row[4]) for row in _compare(database, 1)] == [("fixture-5", True)]
        assert Counter((row[3], row[4]) for row in _compare(database, 2)) == Counter(
            [("fixture-6", False), ("fixture-7", None)]
        )
