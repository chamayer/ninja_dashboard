"""Migration 0328 on a real PostgreSQL: one writer for Computer names (ADR-0034 section 6).

Builds the 0325 chain (production column types) and runs every statement of
0328, then checks the writer, the guard and the creation check.
"""

from __future__ import annotations

import importlib
import os

import psycopg
import pytest

from apps.core.tests.test_migration_0306_postgres import FINDING_TYPES_SCHEMA, _SchemaEditor
from apps.core.tests.test_migration_0306_postgres import SCHEMA as FOUNDATION_SCHEMA
from apps.core.tests.test_migration_0308_postgres import TABLES, _computer
from apps.core.tests.test_migration_0315_postgres import LINKS
from apps.core.tests.test_migration_0318_postgres import HISTORY
from apps.core.tests.test_migration_0322_postgres import CHAIN, EXTRA, _record
from apps.core.tests.test_migration_0325_postgres import (
    CLIENT,
    DECISION_REGISTRY,
    DECISION_TRIGGER,
)


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            for ddl in (
                FOUNDATION_SCHEMA,
                TABLES,
                LINKS,
                HISTORY,
                EXTRA,
                FINDING_TYPES_SCHEMA,
                DECISION_REGISTRY,
                DECISION_TRIGGER,
            ):
                connection.execute(ddl)
            # Production: unique index uq_obs_current_tenant_observation.
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_obs_current_tenant_observation "
                "ON operations.entity_observation_current (tenant_id, observation_id)"
            )
            # Production: operations_migrate is a superuser (bootstrap-roles.sql).
            connection.execute("ALTER ROLE operations_migrate SUPERUSER")
            for name in (
                *CHAIN,
                "0322_record_names_and_shadow_naming",
                "0325_computer_name_collision_guard",
                "0328_computer_name_writer",
            ):
                module = importlib.import_module(f"apps.core.migrations.{name}")
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE operations_migrate")
                    connection.execute(
                        getattr(module, "FOUNDATION_SQL", None) or module.FORWARD_SQL
                    )
                if hasattr(module, "register_finding_type"):
                    module.register_finding_type(None, _SchemaEditor(connection))
            connection.execute("SELECT set_config('operations.tenant_id', '1', false)")
            yield connection


def _create(conn, name, record_name):
    """Create a Computer the way promotion does: insert, attach, name, commit."""
    with conn.transaction():
        device = _computer(conn, name, CLIENT)
        observation, _key = _record(conn, device, "Ninja", "agent.rmm", record_name, online=True)
        conn.execute("SELECT operations.write_computer_names(%s::uuid[], 1)", ([device],))
    return device, observation


def _stored(conn, device):
    return conn.execute(
        "SELECT canonical_hostname, name_rule, name_observation_id FROM operations.devices "
        "WHERE id = %s",
        (device,),
    ).fetchone()


def test_creation_names_the_computer_and_records_the_rename(conn):
    device, observation = _create(conn, "placeholder", "pc-real")
    assert _stored(conn, device) == ("pc-real", "reporting_os", observation)
    action = conn.execute(
        "SELECT reason, evidence ->> 'rule' FROM operations.change_actions "
        "WHERE action = 'computer.rename' AND evidence ->> 'device_id' = %s",
        (str(device),),
    ).fetchone()
    assert action == ("Named by reporting_os", "reporting_os")


def test_an_unchanged_decision_writes_nothing(conn):
    device, _ = _create(conn, "pc-same", "pc-same")
    assert (
        conn.execute("SELECT operations.write_computer_names(%s::uuid[], 1)", ([device],))
        .fetchone()[0]
        == 0
    )


def test_a_computer_left_pending_is_refused_at_commit(conn):
    with pytest.raises(psycopg.errors.RaiseException, match="without a name decision"):
        with conn.transaction():
            _computer(conn, "never-named", CLIENT)


@pytest.mark.parametrize("role", ["operations_app", "ninja_ingest"])
def test_direct_name_writes_are_refused(conn, role):
    device, _ = _create(conn, "pc-guard", "pc-guard")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.transaction():
            conn.execute(f"SET LOCAL ROLE {role}")
            conn.execute(
                "UPDATE operations.devices SET canonical_hostname = 'hijack' WHERE id = %s",
                (device,),
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.transaction():
            conn.execute(f"SET LOCAL ROLE {role}")
            conn.execute(
                "UPDATE operations.devices SET name_rule = 'operator' WHERE id = %s", (device,)
            )


def test_the_writer_needs_the_session_tenant(conn):
    device, _ = _create(conn, "pc-tenant", "pc-tenant")
    with pytest.raises(psycopg.errors.RaiseException, match="session tenant"):
        with conn.transaction():
            conn.execute("SELECT operations.write_computer_names(%s::uuid[], 2)", ([device],))


def test_operator_name_and_reset(conn):
    device, observation = _create(conn, "pc-op", "pc-op")
    with conn.transaction():
        conn.execute(
            """INSERT INTO operations.device_operator_decisions
                   (version, id, dimension, value, reason, set_by, set_at, tenant_id, device_id)
               VALUES (1, gen_random_uuid(), 'name', '{"name": "front-desk"}', 'asked', 'x',
                       now(), 1, %s)""",
            (device,),
        )
        conn.execute("SELECT operations.write_computer_names(%s::uuid[], 1)", ([device],))
    assert _stored(conn, device) == ("front-desk", "operator", None)
    with conn.transaction():
        conn.execute(
            "DELETE FROM operations.device_operator_decisions WHERE device_id = %s", (device,)
        )
        conn.execute("SELECT operations.write_computer_names(%s::uuid[], 1)", ([device],))
    assert _stored(conn, device) == ("pc-op", "reporting_os", observation)
