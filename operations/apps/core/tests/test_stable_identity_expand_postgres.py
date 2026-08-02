"""PostgreSQL coverage for the ADR-0009 shadow-identity backfill."""

from __future__ import annotations

import importlib
import os
import uuid

import psycopg
import pytest


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 to start a disposable Postgres container")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            yield connection


def test_backfill_maps_every_current_source_namespace(postgres_connection) -> None:
    migration = importlib.import_module(
        "operations.apps.core.migrations.0095_stable_observation_identity_expand"
    )
    source_rows = (
        (1, "Ninja", "agent.rmm", "device", "101", "101"),
        (1, "Ninja", "vm.guest", "device", "102", "102"),
        (1, "Ninja", "org", "organization", "103", "103"),
        (2, "SentinelOne", "agent.edr", "agent", "201", "201"),
        (2, "SentinelOne", "org", "site", "202", "202"),
        (
            3,
            "ScreenConnect",
            "agent.remote_access",
            "access-session",
            "301",
            "301",
        ),
        (3, "ScreenConnect", "org", "source-instance", "editable-key", "self"),
        (4, "LogMeIn", "agent.remote_access", "host", "401", "401"),
        (4, "LogMeIn", "org", "group", "402", "402"),
        (5, "Hudu", "cmdb.asset", "asset", "501", "501"),
        (5, "Hudu", "org", "company", "502", "502"),
    )

    with postgres_connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA operations")
        cursor.execute("""
            CREATE TABLE operations.sources (
                id integer PRIMARY KEY,
                name text NOT NULL
            );
            CREATE TABLE operations.source_instances (
                id uuid PRIMARY KEY,
                source_id integer NOT NULL REFERENCES operations.sources(id)
            );
            CREATE TABLE operations.source_bindings (
                id uuid PRIMARY KEY,
                source_instance_id uuid NOT NULL
                    REFERENCES operations.source_instances(id)
            );
            CREATE TABLE operations.entity_observation_current (
                id integer PRIMARY KEY,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NULL,
                last_seen_binding_id uuid NULL,
                entity_type text NOT NULL,
                entity_key text NOT NULL,
                external_namespace text NOT NULL DEFAULT '',
                parent_external_namespace text NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL DEFAULT ''
            );
            CREATE TABLE operations.entity_observation_history (
                id integer PRIMARY KEY,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NULL,
                last_seen_binding_id uuid NULL,
                entity_type text NOT NULL,
                entity_key text NOT NULL,
                external_namespace text NOT NULL DEFAULT '',
                parent_external_namespace text NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL DEFAULT ''
            );
            CREATE TABLE operations.observation_snapshot_runs (
                id integer PRIMARY KEY,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NULL,
                snapshot_at timestamptz NOT NULL,
                run_started_at timestamptz NULL,
                status text NOT NULL,
                is_complete_snapshot boolean NULL
            );
        """)

        source_instances: dict[int, uuid.UUID] = {}
        source_bindings: dict[int, uuid.UUID] = {}
        for source_id, source_name in sorted({(row[0], row[1]) for row in source_rows}):
            source_instance_id = uuid.uuid4()
            source_binding_id = uuid.uuid4()
            source_instances[source_id] = source_instance_id
            source_bindings[source_id] = source_binding_id
            cursor.execute(
                "INSERT INTO operations.sources VALUES (%s, %s)",
                (source_id, source_name),
            )
            cursor.execute(
                "INSERT INTO operations.source_instances VALUES (%s, %s)",
                (source_instance_id, source_id),
            )
            cursor.execute(
                "INSERT INTO operations.source_bindings VALUES (%s, %s)",
                (source_binding_id, source_instance_id),
            )

        for row_id, row in enumerate(source_rows, start=1):
            source_id, _source_name, entity_type, _namespace, legacy_id, _external_id = row
            values = (row_id, source_bindings[source_id], entity_type, legacy_id)
            cursor.execute(
                """
                INSERT INTO operations.entity_observation_current
                    (id, source_binding_id, entity_type, entity_key)
                VALUES (%s, %s, %s, %s)
                """,
                values,
            )
            cursor.execute(
                """
                INSERT INTO operations.entity_observation_history
                    (id, source_binding_id, entity_type, entity_key)
                VALUES (%s, %s, %s, %s)
                """,
                values,
            )

        complete_binding = source_bindings[1]
        failed_binding = source_bindings[2]
        cursor.execute(
            """
            INSERT INTO operations.observation_snapshot_runs
                (id, source_binding_id, snapshot_at, status)
            VALUES
                (1, %s, '2026-08-02T12:00:00Z', 'complete'),
                (2, %s, '2026-08-02T13:00:00Z', 'failed')
        """,
            (complete_binding, failed_binding),
        )

        cursor.execute(migration.BACKFILL_SQL)

        cursor.execute("""
            SELECT s.name, c.entity_type, c.external_namespace, c.entity_key,
                   c.external_id, c.source_instance_id, c.last_seen_binding_id,
                   c.parent_external_namespace, c.parent_external_id
            FROM operations.entity_observation_current c
            JOIN operations.source_instances si ON si.id = c.source_instance_id
            JOIN operations.sources s ON s.id = si.source_id
            ORDER BY c.id
        """)
        actual = cursor.fetchall()
        for expected, observed in zip(source_rows, actual, strict=True):
            source_id, source_name, entity_type, namespace, legacy_id, external_id = expected
            assert observed == (
                source_name,
                entity_type,
                namespace,
                legacy_id,
                external_id,
                source_instances[source_id],
                source_bindings[source_id],
                "",
                "",
            )

        cursor.execute("""
            SELECT COUNT(*)
            FROM operations.entity_observation_history h
            JOIN operations.entity_observation_current c USING (id)
            WHERE h.source_instance_id = c.source_instance_id
              AND h.last_seen_binding_id = c.last_seen_binding_id
              AND h.external_namespace = c.external_namespace
              AND h.external_id = c.external_id
        """)
        assert cursor.fetchone()[0] == len(source_rows)

        cursor.execute("""
            SELECT source_instance_id, run_started_at = snapshot_at,
                   is_complete_snapshot
            FROM operations.observation_snapshot_runs ORDER BY id
        """)
        assert cursor.fetchall() == [
            (source_instances[1], True, True),
            (source_instances[2], True, False),
        ]
