"""Opt-in PostgreSQL coverage for migration 0097's additive shadow schema."""

from __future__ import annotations

import importlib
import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from ingest.backfill_ninja_daily_rollup import process_day


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://",
            "postgresql://",
        )
        with psycopg.connect(dsn) as connection:
            yield connection


def test_expand_schema_rollup_and_shadow_views(postgres_connection) -> None:
    migration = importlib.import_module(
        "operations.apps.core.migrations.0097_ninja_snapshot_expand"
    )
    scope_migration = importlib.import_module(
        "operations.apps.core.migrations.0099_ninja_shadow_scope_correction"
    )
    source_record_id = uuid.uuid4()
    health_record_id = uuid.uuid4()
    historical_record_id = uuid.uuid4()
    source_instance_id = uuid.UUID(scope_migration.NINJA_SOURCE_INSTANCE_ID)
    other_source_instance_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with postgres_connection.transaction(), postgres_connection.cursor() as cursor:
        cursor.execute("""
            CREATE ROLE operations_app;
            CREATE ROLE operations_readonly;
            CREATE ROLE ninja_ingest;
            CREATE ROLE operations_migrate;
            CREATE SCHEMA operations;
            CREATE SCHEMA ninja_core;
            GRANT USAGE ON SCHEMA operations
                TO operations_app, operations_readonly, ninja_ingest;
            CREATE TABLE ninja_core.device_snapshots (
                snapshot_at timestamptz NOT NULL,
                device_id integer NOT NULL
            );
            CREATE TABLE operations.tenants (id bigint PRIMARY KEY);
            CREATE TABLE operations.entity_observation_current (
                observation_id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL REFERENCES operations.tenants(id),
                source_instance_id uuid NOT NULL,
                external_namespace varchar(120) NOT NULL,
                parent_external_namespace varchar(120) NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL,
                platform text NOT NULL,
                observed_at timestamptz NOT NULL,
                active boolean NOT NULL,
                snapshot_scope varchar(120) NOT NULL DEFAULT '',
                raw_data jsonb NOT NULL,
                canonical_data jsonb NOT NULL,
                raw_hash bytea,
                material_hash bytea NOT NULL,
                material_projection_version integer NOT NULL DEFAULT 1
            );
            CREATE TABLE operations.observation_snapshot_runs (
                run_id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL REFERENCES operations.tenants(id)
            );
        """)
        cursor.execute(migration.FORWARD_SQL)
        cursor.execute("INSERT INTO operations.tenants VALUES (1)")
        cursor.execute(
            "INSERT INTO operations.observation_snapshot_runs VALUES (%s, 1)",
            (run_id,),
        )
        cursor.execute(
            """
            INSERT INTO operations.entity_observation_current
              (observation_id, tenant_id, source_instance_id,
               external_namespace, external_id, platform, observed_at, active,
               snapshot_scope,
               raw_data, canonical_data, raw_hash, material_hash,
               material_projection_version)
            VALUES
              (%s, 1, %s, 'device', '42', 'Ninja', clock_timestamp(), TRUE,
               'Ninja',
               '{"deviceId":42}',
               '{"offline":false,
                 "last_contact_at":"2026-08-03T12:00:00Z",
                 "last_boot_time_at":"2026-08-01T09:00:00Z",
                 "needs_reboot":true,
                 "needs_reboot_reasons":["patch"],
                 "last_user":"example-user",
                 "maintenance_status":"SCHEDULED",
                 "maintenance_start_at":"2026-08-04T01:00:00Z",
                 "maintenance_end_at":"2026-08-04T02:00:00Z"}',
               decode(repeat('01', 32), 'hex'),
               decode(repeat('02', 32), 'hex'), 3),
              (%s, 1, %s, 'device', '43', 'Ninja', clock_timestamp(), TRUE,
               'ninja_main', '{"deviceId":43}',
               '{"last_boot_time_at":"1785589200"}',
               decode(repeat('05', 32), 'hex'),
               decode(repeat('06', 32), 'hex'), 1),
              (%s, 1, %s, 'device', '44', 'Ninja', clock_timestamp(), TRUE,
               'Ninja', '{"deviceId":44}', '{}',
               decode(repeat('07', 32), 'hex'),
               decode(repeat('08', 32), 'hex'), 3),
              (%s, 1, %s, 'device', '45', 'Ninja', clock_timestamp(), TRUE,
               'Ninja', '{"deviceId":45}', '{}',
               decode(repeat('09', 32), 'hex'),
               decode(repeat('0a', 32), 'hex'), 2),
              (%s, 1, %s, 'device', '46', 'Ninja', clock_timestamp(), FALSE,
               'ninja_main', '{"deviceId":46}', '{}',
               decode(repeat('0b', 32), 'hex'),
               decode(repeat('0c', 32), 'hex'), 1)
            """,
            (
                source_record_id,
                source_instance_id,
                uuid.uuid4(),
                source_instance_id,
                uuid.uuid4(),
                other_source_instance_id,
                uuid.uuid4(),
                source_instance_id,
                historical_record_id,
                source_instance_id,
            ),
        )
        cursor.execute(
            """
            INSERT INTO operations.entity_observation_current
              (observation_id, tenant_id, source_instance_id,
               external_namespace, external_id, platform, observed_at, active,
               snapshot_scope,
               raw_data, canonical_data, raw_hash, material_hash,
               material_projection_version)
            VALUES
              (%s, 1, %s, 'device-health', '42', 'Ninja',
               clock_timestamp(), TRUE, 'Ninja.device-health', '{"deviceId":42}',
               '{"pending_reboot_reason":"WINDOWS_UPDATE",
                 "pending_os_patches_count":3,
                 "health_status":"WARNING",
                 "offline":false,
                 "parent_offline":true,
                 "products_installation_statuses":{"agent":"INSTALLED"}}',
               decode(repeat('03', 32), 'hex'),
               decode(repeat('04', 32), 'hex'), 1)
            """,
            (health_record_id, source_instance_id),
        )
        cursor.execute("SET LOCAL operations.tenant_id = '1'")
        cursor.execute(
            """
            INSERT INTO operations.source_record_seen_daily
              (tenant_id, source_record_id, external_namespace, rollup_day,
               first_snapshot_run_id)
            VALUES (1, %s, 'device', DATE '2026-08-03', %s)
            """,
            (source_record_id, run_id),
        )
        cursor.execute(
            """
            INSERT INTO operations.source_record_seen_daily
              (tenant_id, source_record_id, external_namespace, rollup_day,
               backfilled_from_legacy)
            VALUES (1, %s, 'device', DATE '2026-08-01', TRUE)
            """,
            (historical_record_id,),
        )
        cursor.execute(scope_migration.FORWARD_SQL)
        cursor.execute(
            """
            SELECT has_table_privilege(
                       'operations_readonly',
                       'operations.ninja_device_detail_current_shadow',
                       'SELECT'
                   ),
                   has_table_privilege(
                       'operations_readonly',
                       'operations.ninja_device_health_current_shadow',
                       'SELECT'
                   ),
                   has_table_privilege(
                       'operations_readonly',
                       'operations.ninja_device_seen_daily_shadow',
                       'SELECT'
                   )
            """
        )
        assert cursor.fetchone() == (True, True, True)
        cursor.execute(
            """
            SELECT device_id, offline, last_contact, last_boot, needs_reboot,
                   needs_reboot_reasons, last_user, maintenance_status,
                   material_projection_version
              FROM operations.ninja_device_detail_current_shadow
            """
        )
        assert cursor.fetchone() == (
            42,
            False,
            datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
            True,
            ["patch"],
            "example-user",
            "SCHEDULED",
            3,
        )
        cursor.execute(
            """
            SELECT device_id, pending_reboot_reason,
                   pending_os_patches_count, health_status, offline,
                   parent_offline, products_installation_statuses,
                   material_projection_version
              FROM operations.ninja_device_health_current_shadow
            """
        )
        assert cursor.fetchone() == (
            42,
            "WINDOWS_UPDATE",
            3,
            "WARNING",
            False,
            True,
            {"agent": "INSTALLED"},
            1,
        )
        cursor.execute(
            """
            SELECT rollup_day, device_id
              FROM operations.ninja_device_seen_daily_shadow
             ORDER BY rollup_day, device_id
            """
        )
        assert cursor.fetchall() == [
            (datetime(2026, 8, 1, tzinfo=timezone.utc).date(), 46),
            (datetime(2026, 8, 3, tzinfo=timezone.utc).date(), 42),
        ]
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
              FROM pg_class
             WHERE oid = 'operations.source_record_seen_daily'::regclass
            """
        )
        assert cursor.fetchone() == (True, True)

        cursor.execute(
            """
            INSERT INTO ninja_core.device_snapshots (snapshot_at, device_id)
            VALUES ('2026-08-02T01:00:00Z', 42),
                   ('2026-08-02T13:00:00Z', 42)
            """
        )
        cursor.execute("SET LOCAL TIME ZONE 'America/New_York'")
        measured = process_day(
            cursor,
            tenant_id=1,
            rollup_day=datetime(2026, 8, 2, tzinfo=timezone.utc).date(),
            apply=False,
        )
        assert (
            measured.legacy_devices,
            measured.matched_devices,
            measured.unmatched_devices,
            measured.ambiguous_devices,
            measured.inserted_rows,
        ) == (1, 1, 0, 0, 0)
        applied = process_day(
            cursor,
            tenant_id=1,
            rollup_day=datetime(2026, 8, 2, tzinfo=timezone.utc).date(),
            apply=True,
        )
        repeated = process_day(
            cursor,
            tenant_id=1,
            rollup_day=datetime(2026, 8, 2, tzinfo=timezone.utc).date(),
            apply=True,
        )
        assert applied.inserted_rows == 1
        assert repeated.inserted_rows == 0
        cursor.execute(
            """
            SELECT first_snapshot_run_id, backfilled_from_legacy
              FROM operations.source_record_seen_daily
             WHERE rollup_day = DATE '2026-08-02'
            """
        )
        assert cursor.fetchone() == (None, True)

        cursor.execute(
            """
            INSERT INTO ninja_core.device_snapshots (snapshot_at, device_id)
            VALUES ('2026-08-01T01:00:00Z', 99)
            """
        )
        with pytest.raises(RuntimeError, match="unmatched=1, ambiguous=0"):
            process_day(
                cursor,
                tenant_id=1,
                rollup_day=datetime(2026, 8, 1, tzinfo=timezone.utc).date(),
                apply=True,
            )
        cursor.execute("SET LOCAL ROLE operations_readonly")
        cursor.execute("SELECT set_config('operations.tenant_id', '1', TRUE)")
        cursor.execute("SELECT COUNT(*) FROM operations.source_record_seen_daily")
        assert cursor.fetchone() == (3,)
        cursor.execute("SELECT set_config('operations.tenant_id', '2', TRUE)")
        cursor.execute("SELECT COUNT(*) FROM operations.source_record_seen_daily")
        assert cursor.fetchone() == (0,)
        cursor.execute("RESET ROLE")
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(scope_migration.REVERSE_SQL)
        cursor.execute(migration.REVERSE_SQL)
