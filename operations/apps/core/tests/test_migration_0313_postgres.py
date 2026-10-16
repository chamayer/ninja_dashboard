"""Migration 0313 on a real PostgreSQL: vm.guest no longer names the Computer.

Production definitions (2026-10-16) for the authority policies, attribute
definitions and claim projection state; 0306 records the change.
"""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA

TABLES = """
CREATE TABLE operations.attribute_definitions (
    id bigint PRIMARY KEY, key varchar(120) NOT NULL
);
INSERT INTO operations.attribute_definitions VALUES (1, 'hostname'), (2, 'os_name');
CREATE TABLE operations.attribute_authority_policies (
    version integer NOT NULL, id uuid PRIMARY KEY, native_record_type varchar(80) NOT NULL,
    eligible boolean NOT NULL, authority_tier smallint NOT NULL, priority smallint NOT NULL,
    enabled boolean NOT NULL, reason varchar(160) NOT NULL, source_instance_id uuid NOT NULL,
    tenant_id bigint NOT NULL, attribute_definition_id bigint NOT NULL
);
CREATE TABLE operations.entity_observation_current (
    observation_id uuid PRIMARY KEY, tenant_id bigint NOT NULL, entity_type varchar(80) NOT NULL
);
CREATE TABLE operations.entity_attribute_projection_state (
    observation_id uuid PRIMARY KEY, projection_hash bytea NOT NULL,
    observation_active boolean NOT NULL, projection_contract_version integer NOT NULL,
    projected_at timestamptz NOT NULL, entity_id uuid NULL, entity_source_link_id uuid NULL,
    source_instance_id uuid NOT NULL, tenant_id bigint NOT NULL
);
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
            source = uuid.uuid4()
            for record_type, definition in (("vm.guest", 1), ("vm.guest", 2), ("agent.rmm", 1)):
                connection.execute(
                    """INSERT INTO operations.attribute_authority_policies VALUES
                           (1, %s, %s, true, 150, 0, true, 'backfill', %s, 1, %s)""",
                    (uuid.uuid4(), record_type, source, definition),
                )
            for entity_type in ("vm.guest", "agent.rmm"):
                observation = uuid.uuid4()
                connection.execute(
                    "INSERT INTO operations.entity_observation_current VALUES (%s, 1, %s)",
                    (observation, entity_type),
                )
                connection.execute(
                    """INSERT INTO operations.entity_attribute_projection_state VALUES
                           (%s, '\\x00', true, 1, now(), NULL, NULL, %s, 1)""",
                    (observation, source),
                )
            foundation = importlib.import_module(
                "apps.core.migrations.0306_change_history_foundation"
            )
            migration = importlib.import_module(
                "apps.core.migrations.0313_vm_guest_name_not_authoritative"
            )
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(migration.FORWARD_SQL)
            yield connection


def test_only_the_vm_guest_hostname_policy_becomes_ineligible(conn):
    rows = conn.execute(
        """SELECT p.native_record_type, d.key, p.eligible, p.version
             FROM operations.attribute_authority_policies p
             JOIN operations.attribute_definitions d ON d.id = p.attribute_definition_id
            ORDER BY 1, 2"""
    ).fetchall()
    assert rows == [
        ("agent.rmm", "hostname", True, 1),
        ("vm.guest", "hostname", False, 2),
        ("vm.guest", "os_name", True, 1),
    ]


def test_vm_guest_claims_are_projected_again(conn):
    remaining = conn.execute(
        """SELECT o.entity_type FROM operations.entity_attribute_projection_state s
             JOIN operations.entity_observation_current o ON o.observation_id = s.observation_id"""
    ).fetchall()
    assert remaining == [("agent.rmm",)]
