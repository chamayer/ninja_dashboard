"""Migration 0320 on a real PostgreSQL: the os_unknown_coverage finding type.

The RunPython step runs against production NOT NULL columns of
``finding_types`` and the policy table (2026-10-18), twice.
"""

from __future__ import annotations

import importlib
import os

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import FINDING_TYPES_SCHEMA, _SchemaEditor

MODULE = "apps.core.migrations.0320_os_unknown_coverage"


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
            yield connection


def test_the_type_and_policy_register_once(conn):
    module = importlib.import_module(MODULE)
    module.register_finding_type(None, _SchemaEditor(conn))
    module.register_finding_type(None, _SchemaEditor(conn))
    row = conn.execute(
        """SELECT display_name, issue_category, creates_device_exposure, alertable
             FROM operations.finding_types WHERE name = 'os_unknown_coverage'"""
    ).fetchone()
    assert row == (
        "Operating system unknown: coverage not evaluated",
        "Agents & reporting",
        False,
        False,
    )
    active = conn.execute(
        "SELECT version, policy FROM operations.condition_policy_versions WHERE active"
    ).fetchone()
    assert active[0] == "conditions-registry-6"
    assert [d["name"] for d in active[1]["definitions"]] == ["os_unknown_coverage"]
    assert (
        conn.execute("SELECT count(*) FROM operations.condition_policy_versions").fetchone()[0] == 2
    )
