"""Migration 0307 on a real PostgreSQL: policy rows and constraint, recorded as one action.

``identity_match_policies`` mirrors production (2026-10-16: columns, NOT NULL,
constraints and the five rows). 0306's foundation runs first so the update is
recorded in the change history under the migration's explicit action.
"""

from __future__ import annotations

import importlib
import os

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA

POLICIES = """
CREATE TABLE operations.tenants (id bigint PRIMARY KEY);
INSERT INTO operations.tenants VALUES (1);
CREATE TABLE operations.identity_match_policies (
    version integer NOT NULL CHECK (version >= 0), id uuid PRIMARY KEY,
    matcher varchar(32) NOT NULL, display_name varchar(120) NOT NULL,
    description varchar(300) NOT NULL, priority smallint NOT NULL CHECK (priority >= 0),
    requires_client_scope boolean NOT NULL, requires_unique_candidate boolean NOT NULL,
    avoid_same_stream_duplicates boolean NOT NULL, blocking_signal_keys jsonb NOT NULL,
    confidence numeric(4,3) NOT NULL, enabled boolean NOT NULL, reason varchar(160) NOT NULL,
    tenant_id bigint NOT NULL REFERENCES operations.tenants(id),
    CONSTRAINT ck_identity_match_policy_blockers CHECK (
        jsonb_typeof(blocking_signal_keys) = 'array'
        AND blocking_signal_keys <@ '["vm_uuid"]'::jsonb),
    CONSTRAINT uq_identity_match_policy UNIQUE (tenant_id, matcher),
    CONSTRAINT uq_identity_match_policy_priority UNIQUE (tenant_id, priority)
);
ALTER TABLE operations.identity_match_policies OWNER TO operations_migrate;
INSERT INTO operations.identity_match_policies VALUES
 (1, gen_random_uuid(), 'source_identity', 'Same source record', 'd', 10, false, true, false, '[]', 1.000, true, 'seed', 1),
 (1, gen_random_uuid(), 'serial', 'Matching serial number', 'd', 20, true, true, false, '[]', 1.000, true, 'seed', 1),
 (1, gen_random_uuid(), 'vm_uuid', 'Matching VM UUID', 'd', 30, true, true, false, '[]', 1.000, true, 'seed', 1),
 (1, gen_random_uuid(), 'hostname_mac', 'Matching name and MAC address', 'd', 40, true, true, false, '["vm_uuid"]', 0.990, true, 'seed', 1),
 (1, gen_random_uuid(), 'hostname', 'Matching name', 'd', 50, true, true, true, '["vm_uuid"]', 0.700, true, 'seed', 1);
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
            connection.execute(POLICIES)
            foundation = importlib.import_module(
                "apps.core.migrations.0306_change_history_foundation"
            )
            module = importlib.import_module(
                "apps.core.migrations.0307_identity_match_hard_conflicts"
            )
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(foundation.FOUNDATION_SQL)
            with connection.transaction():
                connection.execute("SET LOCAL ROLE operations_migrate")
                connection.execute(module.FORWARD_SQL)
            yield connection


def test_policies_use_hard_conflicts(conn):
    rows = conn.execute(
        """SELECT matcher, requires_unique_candidate, avoid_same_stream_duplicates,
                  blocking_signal_keys
             FROM operations.identity_match_policies ORDER BY priority"""
    ).fetchall()
    assert rows == [
        ("source_identity", True, False, []),
        ("serial", False, False, ["vm_uuid"]),
        ("vm_uuid", False, False, ["serial"]),
        ("hostname_mac", False, False, ["serial", "vm_uuid", "same_source_live"]),
        ("hostname", False, False, ["serial", "vm_uuid", "same_source_live"]),
    ]


def test_the_constraint_allows_only_known_signals(conn):
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            """UPDATE operations.identity_match_policies
                  SET blocking_signal_keys = '["domain"]' WHERE matcher = 'hostname'"""
        )


def test_the_change_is_one_explicit_action(conn):
    actions = conn.execute(
        """SELECT DISTINCT a.action, a.explicit, a.actor_kind
             FROM operations.identity_match_policies_change_history h
             JOIN operations.change_actions a ON a.id = h.action_id"""
    ).fetchall()
    assert actions == [("identity_policy.hard_conflicts", True, "migration")]
    assert (
        conn.execute(
            "SELECT count(*) FROM operations.identity_match_policies_change_history"
        ).fetchone()[0]
        == 5
    )
