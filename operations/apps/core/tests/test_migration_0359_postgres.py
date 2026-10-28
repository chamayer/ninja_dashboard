"""Migration 0359 drops metabase_ro, and no later migration may name it again."""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import psycopg
import pytest

MODULE = "apps.core.migrations.0359_drop_metabase_ro_role"
REPO = Path(__file__).resolve().parents[4]

SCHEMA = """
CREATE ROLE metabase_ro NOLOGIN;
CREATE SCHEMA operations;
CREATE TABLE operations.t (id int);
GRANT USAGE ON SCHEMA operations TO metabase_ro;
GRANT SELECT ON operations.t TO metabase_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA operations GRANT SELECT ON TABLES TO metabase_ro;
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
            connection.execute(SCHEMA)
            yield connection


def test_role_with_grants_and_default_privileges_is_dropped(conn):
    module = importlib.import_module(MODULE)
    conn.execute(module.FORWARD_SQL)
    assert conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'metabase_ro'").fetchone() is None
    # Running again, as on a database that never had the role, is a no-op.
    conn.execute(module.FORWARD_SQL)


def test_no_metabase_ro_after_retirement():
    django_dir = REPO / "operations" / "apps" / "core" / "migrations"
    sql_dir = REPO / "sql" / "migrations"
    later = [p for p in django_dir.glob("[0-9]*.py") if int(p.name[:4]) > 359]
    later += [p for p in sql_dir.glob("[0-9]*.sql") if int(re.match(r"\d+", p.name)[0]) > 118]
    offenders = [p.name for p in later if "metabase_ro" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"metabase_ro was dropped by 0359; remove it from {offenders}"
