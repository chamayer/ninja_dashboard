from __future__ import annotations

import importlib
import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.types.json import Json


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn) as connection:
            yield connection


def test_health_evidence_does_not_duplicate_device_presence(
    postgres_connection,
) -> None:
    migration = importlib.import_module(
        "apps.core.migrations.0098_exclude_health_from_device_presence"
    )
    device_id = uuid.uuid4()
    observed_at = datetime(2026, 8, 3, 12, tzinfo=UTC)

    with postgres_connection.transaction(), postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE ROLE operations_app;
            CREATE ROLE ninja_ingest;
            CREATE ROLE operations_readonly;
            CREATE ROLE metabase_ro;
            CREATE ROLE operations_migrate;
            CREATE SCHEMA operations;
            CREATE SCHEMA ninja_core;

            CREATE TABLE operations.devices (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                client_id uuid NOT NULL,
                version integer NOT NULL DEFAULT 1,
                canonical_hostname text NOT NULL DEFAULT '',
                canonical_serial text NOT NULL DEFAULT '',
                canonical_vm_uuid text NOT NULL DEFAULT '',
                device_type text NOT NULL,
                device_role text NOT NULL DEFAULT '',
                lifecycle_status text NOT NULL DEFAULT 'active',
                os_name text NOT NULL DEFAULT '',
                os_family text NOT NULL DEFAULT '',
                os_group text NOT NULL DEFAULT '',
                created_at timestamptz NOT NULL,
                created_reason text NOT NULL DEFAULT '',
                updated_at timestamptz NOT NULL,
                updated_reason text NOT NULL DEFAULT '',
                stale_since timestamptz NULL,
                stale_reason text NOT NULL DEFAULT '',
                deleted_at timestamptz NULL,
                deleted_reason text NOT NULL DEFAULT ''
            );
            CREATE TABLE operations.entity_observation_current (
                tenant_id bigint NOT NULL,
                device_id uuid NULL,
                entity_type text NOT NULL,
                platform text NOT NULL,
                subplatform text NOT NULL,
                external_namespace text NOT NULL,
                observed_at timestamptz NOT NULL,
                canonical_data jsonb NOT NULL,
                active boolean NOT NULL
            );
            CREATE TABLE ninja_core.device_snapshots (
                device_id integer NOT NULL,
                needs_reboot boolean NOT NULL,
                last_boot timestamptz NULL,
                snapshot_at timestamptz NOT NULL
            );
            CREATE TABLE operations.sources (
                id uuid PRIMARY KEY,
                name text NOT NULL
            );
            CREATE TABLE operations.device_links (
                device_id uuid NOT NULL,
                source_id uuid NOT NULL,
                external_id text NOT NULL
            );
            CREATE TABLE operations.device_operator_decisions (
                tenant_id bigint NOT NULL,
                device_id uuid NOT NULL,
                dimension text NOT NULL,
                value jsonb NOT NULL
            );
            CREATE TABLE operations.device_patching_scope_current (
                tenant_id bigint NOT NULL,
                device_id uuid NOT NULL,
                scope_derived text NULL,
                scope_reason text NULL,
                computed_at timestamptz NULL
            );
            CREATE TABLE operations.device_patching_override (
                tenant_id bigint NOT NULL,
                device_id uuid NOT NULL,
                scope text NULL,
                reason text NULL
            );
            CREATE TABLE operations.run_log (
                tenant_id bigint NOT NULL,
                kind text NOT NULL,
                ok boolean NOT NULL,
                ended_at timestamptz NULL,
                rows integer NULL,
                error text NULL,
                started_at timestamptz NOT NULL
            );

            CREATE MATERIALIZED VIEW operations.device_agent_presence_current
                AS SELECT 1 AS placeholder WITH NO DATA;
            CREATE MATERIALIZED VIEW operations.device_session_current
                AS SELECT 1 AS placeholder WITH NO DATA;
            CREATE MATERIALIZED VIEW operations.source_health_current
                AS SELECT 1 AS placeholder WITH NO DATA;
            CREATE VIEW operations.v_device AS SELECT 1 AS placeholder;
            """
        )
        cursor.execute(
            """
            INSERT INTO operations.devices
              (id, tenant_id, client_id, device_type, created_at, updated_at)
            VALUES (%s, 1, %s, 'virtual', %s, %s)
            """,
            (device_id, uuid.uuid4(), observed_at, observed_at),
        )
        cursor.executemany(
            """
            INSERT INTO operations.entity_observation_current
              (tenant_id, device_id, entity_type, platform, subplatform,
               external_namespace, observed_at, canonical_data, active)
            VALUES (1, %s, 'vm.guest', 'Ninja', %s, %s, %s, %s, TRUE)
            """,
            [
                (
                    device_id,
                    "",
                    "device",
                    observed_at,
                    Json(
                        {
                            "last_seen_at": observed_at.isoformat(),
                            "offline": False,
                            "power_state": "poweredon",
                        }
                    ),
                ),
                (
                    device_id,
                    "device-health",
                    "device-health",
                    observed_at,
                    Json({"offline": False, "health_status": "GOOD"}),
                ),
            ],
        )

        cursor.execute(migration.FORWARD_SQL)
        cursor.execute(
            """
            SELECT COUNT(*), MIN(subplatform), MAX(observation_count),
                   BOOL_AND(reported_online), MIN(last_power_state)
              FROM operations.device_agent_presence_current
            """
        )
        assert cursor.fetchone() == (1, "", 1, True, "poweredon")
        cursor.execute(
            """
            SELECT to_regclass('operations.device_session_current') IS NOT NULL,
                   to_regclass('operations.v_device') IS NOT NULL,
                   to_regclass('operations.source_health_current') IS NOT NULL
            """
        )
        assert cursor.fetchone() == (True, True, True)
