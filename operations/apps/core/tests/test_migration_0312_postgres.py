"""Migration 0312 on a real PostgreSQL: Hudu documentation is required.

Production definitions (2026-10-16) for agents, requirement profiles and
coverage requirements, including NOT NULL columns, checks and the profile
item shape index; runs after 0306 so the change is recorded.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA

TABLES = """
CREATE TABLE operations.agents (
    id smallint PRIMARY KEY, name varchar(80) UNIQUE NOT NULL, entity_type varchar(80) NOT NULL,
    supported_os_groups jsonb NOT NULL, default_severity varchar(16) NOT NULL,
    default_gap_after_hours integer NOT NULL CHECK (default_gap_after_hours >= 0),
    default_confidence_probable integer NOT NULL CHECK (default_confidence_probable >= 0),
    default_confidence_confirmed integer NOT NULL CHECK (default_confidence_confirmed >= 0)
);
INSERT INTO operations.agents VALUES
    (1, 'Ninja', 'agent.rmm', '["Windows"]', 'critical', 720, 1440, 2160),
    (5, 'R-U-ON', 'agent.monitoring', '["Windows"]', 'high', 720, 1440, 2160);
CREATE TABLE operations.requirement_profiles (
    version integer NOT NULL, id uuid PRIMARY KEY, name varchar(120) NOT NULL,
    description text NOT NULL, is_tenant_default boolean NOT NULL,
    created_at timestamptz NOT NULL, tenant_id bigint NOT NULL
);
CREATE TABLE operations.requirement_profile_items (
    version integer NOT NULL CHECK (version >= 0), id uuid PRIMARY KEY,
    entity_type varchar(80) NOT NULL, platform varchar(80) NOT NULL,
    device_scope varchar(16) NOT NULL, severity varchar(16) NOT NULL,
    gap_after_hours integer NOT NULL CHECK (gap_after_hours >= 0),
    confidence_probable integer NOT NULL CHECK (confidence_probable >= 0),
    confidence_confirmed integer NOT NULL CHECK (confidence_confirmed >= 0),
    profile_id uuid NOT NULL REFERENCES operations.requirement_profiles(id),
    tenant_id bigint NOT NULL, agent_id smallint NULL REFERENCES operations.agents(id),
    applicable_os_groups jsonb NULL
);
CREATE UNIQUE INDEX uq_requirement_profile_items_shape ON operations.requirement_profile_items
    (tenant_id, profile_id, entity_type, platform, device_scope);
CREATE TABLE operations.coverage_requirements (
    version integer NOT NULL CHECK (version >= 0), id uuid PRIMARY KEY,
    entity_type varchar(80) NOT NULL, platform varchar(80) NOT NULL,
    device_scope varchar(16) NOT NULL, severity varchar(16) NOT NULL,
    gap_after_hours integer NOT NULL CHECK (gap_after_hours >= 0),
    confidence_probable integer NOT NULL CHECK (confidence_probable >= 0),
    confidence_confirmed integer NOT NULL CHECK (confidence_confirmed >= 0),
    enabled boolean NOT NULL, created_at timestamptz NOT NULL, client_id uuid NULL,
    tenant_id bigint NOT NULL, agent_id smallint NULL REFERENCES operations.agents(id),
    applicable_os_groups jsonb NULL
);
INSERT INTO operations.coverage_requirements VALUES
    (1, gen_random_uuid(), 'agent.rmm', 'Ninja', 'all', 'critical', 720, 1440, 2160, true,
     now(), NULL, 1, 1, NULL);
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
            for name in ("Standard", "UTA policy"):
                connection.execute(
                    "INSERT INTO operations.requirement_profiles VALUES (1, %s, %s, '', false, now(), 1)",
                    (uuid.uuid4(), name),
                )
            foundation = importlib.import_module(
                "apps.core.migrations.0306_change_history_foundation"
            )
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            yield connection


def _apply(conn):
    migration = importlib.import_module("apps.core.migrations.0312_hudu_documentation_required")
    with conn.transaction():
        conn.execute("SET LOCAL ROLE operations_migrate")
        conn.execute(migration.FORWARD_SQL)


def test_hudu_is_required_in_every_profile_and_globally_once(conn):
    _apply(conn)
    _apply(conn)  # running it again adds nothing
    agent = conn.execute(
        "SELECT id, entity_type, supported_os_groups FROM operations.agents WHERE name = 'Hudu'"
    ).fetchone()
    assert agent[0] == 6 and agent[1] == "cmdb.asset" and "Unknown" in agent[2]
    assert conn.execute(
        """SELECT count(*), count(DISTINCT profile_id) FROM operations.requirement_profile_items
            WHERE platform = 'Hudu' AND entity_type = 'cmdb.asset' AND agent_id = 6"""
    ).fetchone() == (2, 2)
    assert conn.execute(
        """SELECT count(*) FROM operations.coverage_requirements
            WHERE platform = 'Hudu' AND client_id IS NULL AND enabled"""
    ).fetchone()[0] == 1
