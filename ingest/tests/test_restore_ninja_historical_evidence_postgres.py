"""Opt-in PostgreSQL coverage for historical Ninja evidence restoration."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import psycopg
import pytest

from ingest.backfill_ninja_daily_rollup import process_day
from ingest.restore_ninja_historical_evidence import (
    INTERNAL_COLLECTOR_INSTANCE_ID,
    NINJA_SOURCE_BINDING_ID,
    RestorationBlocked,
    process_range,
)


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


def test_restore_closed_evidence_then_backfill(postgres_connection) -> None:
    source_instance_id = uuid.uuid4()
    with postgres_connection.transaction(), postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE SCHEMA operations;
            CREATE SCHEMA ninja_core;
            CREATE TABLE operations.sources (
                id bigint PRIMARY KEY,
                name text NOT NULL
            );
            CREATE TABLE operations.source_instances (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_id bigint NOT NULL
            );
            CREATE TABLE operations.source_bindings (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_instance_id uuid NOT NULL,
                collector_instance_id uuid NOT NULL
            );
            CREATE TABLE operations.device_links (
                tenant_id bigint NOT NULL,
                source_id bigint NOT NULL,
                external_id text NOT NULL,
                device_id uuid NOT NULL
            );
            CREATE TABLE ninja_core.devices (
                id integer PRIMARY KEY,
                uid uuid NOT NULL,
                node_class text NOT NULL,
                display_name text,
                system_name text,
                dns_name text,
                os_name text,
                serial_number text,
                is_virtual_machine boolean,
                mac_addresses text[],
                data jsonb NOT NULL,
                first_seen_at timestamptz NOT NULL,
                last_seen_at timestamptz NOT NULL,
                is_current boolean NOT NULL,
                missing_since timestamptz
            );
            CREATE TABLE ninja_core.device_snapshots (
                snapshot_at timestamptz NOT NULL,
                device_id integer NOT NULL,
                offline boolean,
                last_contact timestamptz,
                last_boot timestamptz,
                needs_reboot boolean,
                needs_reboot_reasons text[],
                last_user text,
                maintenance_status text,
                maintenance_start timestamptz,
                maintenance_end timestamptz
            );
            CREATE TABLE operations.entity_observation_current (
                observation_id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NOT NULL,
                last_seen_binding_id uuid,
                external_namespace varchar(120) NOT NULL,
                parent_external_namespace varchar(120) NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL,
                collector_instance_id uuid NOT NULL,
                client_id uuid,
                device_id uuid,
                entity_type varchar(80) NOT NULL,
                parent_source_key text NOT NULL DEFAULT '',
                entity_key text NOT NULL,
                platform varchar(80) NOT NULL,
                subplatform varchar(120) NOT NULL DEFAULT '',
                observed_at timestamptz NOT NULL,
                last_seen_at timestamptz NOT NULL,
                last_received_at timestamptz NOT NULL,
                active boolean NOT NULL,
                withdrawn_at timestamptz,
                snapshot_scope varchar(120) NOT NULL DEFAULT '',
                last_snapshot_run_id uuid,
                raw_data jsonb NOT NULL,
                canonical_data jsonb NOT NULL,
                raw_hash bytea,
                material_hash bytea NOT NULL,
                hash_algorithm_version integer NOT NULL,
                material_projection_version integer NOT NULL,
                batch_id uuid NOT NULL,
                collector_version varchar(80) NOT NULL DEFAULT '',
                schema_version integer NOT NULL,
                UNIQUE (
                    tenant_id, source_instance_id, external_namespace,
                    parent_external_namespace, parent_external_id, external_id
                )
            );
            CREATE TABLE operations.entity_observation_history (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NOT NULL,
                last_seen_binding_id uuid,
                external_namespace varchar(120) NOT NULL,
                parent_external_namespace varchar(120) NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL,
                collector_instance_id uuid NOT NULL,
                client_id uuid,
                device_id uuid,
                entity_type varchar(80) NOT NULL,
                platform varchar(80) NOT NULL,
                parent_source_key text NOT NULL DEFAULT '',
                entity_key text NOT NULL,
                effective_from timestamptz NOT NULL,
                effective_to timestamptz,
                last_seen_at timestamptz NOT NULL,
                received_at timestamptz NOT NULL,
                material_data jsonb NOT NULL,
                material_hash bytea NOT NULL,
                hash_algorithm_version integer NOT NULL,
                material_projection_version integer NOT NULL,
                active boolean NOT NULL,
                closed_by_snapshot_run_id uuid
            );
            CREATE TABLE operations.source_record_seen_daily (
                tenant_id bigint NOT NULL,
                source_record_id uuid NOT NULL,
                external_namespace varchar(120) NOT NULL,
                rollup_day date NOT NULL,
                first_snapshot_run_id uuid,
                backfilled_from_legacy boolean NOT NULL DEFAULT FALSE,
                PRIMARY KEY (tenant_id, source_record_id, rollup_day)
            );
            """
        )
        cursor.execute("INSERT INTO operations.sources VALUES (1, 'Ninja')")
        cursor.execute(
            "INSERT INTO operations.source_instances VALUES (%s, 1, 1)",
            (source_instance_id,),
        )
        cursor.execute(
            """INSERT INTO operations.source_bindings
               VALUES (%s, 1, %s, %s)""",
            (
                NINJA_SOURCE_BINDING_ID,
                source_instance_id,
                INTERNAL_COLLECTOR_INSTANCE_ID,
            ),
        )
        cursor.execute(
            """
            INSERT INTO ninja_core.devices
              (id, uid, node_class, display_name, system_name, dns_name,
               os_name, serial_number, is_virtual_machine, mac_addresses,
               data, first_seen_at, last_seen_at, is_current, missing_since)
            VALUES
              (42, %s, 'HYPERV_VMM_GUEST', 'historical', 'historical-system',
               'historical.example.invalid', 'Windows Server', 'redacted',
               TRUE, ARRAY['00:11:22:33:44:55'],
               '{"id":42,"powerState":"POWERED_ON","parentDeviceId":7,
                 "lastBootTime":1785589200}',
               '2026-06-01T12:00:00Z', '2026-06-03T12:00:00Z', FALSE,
               '2026-06-04T12:00:00Z')
            """,
            (uuid.uuid4(),),
        )
        cursor.execute(
            """
            INSERT INTO ninja_core.device_snapshots
              (snapshot_at, device_id, offline, last_contact, last_boot,
               needs_reboot, needs_reboot_reasons, last_user,
               maintenance_status, maintenance_start, maintenance_end)
            VALUES
              ('2026-06-02T12:00:00Z', 42, FALSE, '2026-06-02T11:55:00Z',
               '2026-06-01T09:00:00Z', FALSE, ARRAY[]::text[], NULL,
               NULL, NULL, NULL),
              ('2026-06-03T12:00:00Z', 42, TRUE, '2026-06-03T11:55:00Z',
               '2026-06-01T09:00:00Z', TRUE, ARRAY['patch'], NULL,
               'SCHEDULED', '2026-06-04T01:00:00Z',
               '2026-06-04T02:00:00Z')
            """
        )

        measured = process_range(
            cursor,
            tenant_id=1,
            start_day=date(2026, 6, 2),
            end_day=date(2026, 6, 3),
            apply=False,
        )
        assert (
            measured.legacy_identities,
            measured.existing_generic_identities,
            measured.missing_generic_identities,
            measured.eligible_identities,
            measured.blocker_count,
            measured.inserted_current_rows,
        ) == (1, 0, 1, 1, 0, 0)
        cursor.execute("SELECT COUNT(*) FROM operations.entity_observation_current")
        assert cursor.fetchone() == (0,)

        applied = process_range(
            cursor,
            tenant_id=1,
            start_day=date(2026, 6, 2),
            end_day=date(2026, 6, 3),
            apply=True,
        )
        assert (applied.inserted_current_rows, applied.inserted_history_rows) == (
            1,
            1,
        )
        cursor.execute(
            """
            SELECT active, observed_at, last_seen_at, withdrawn_at,
                   client_id, device_id, last_snapshot_run_id,
                   external_namespace, external_id,
                   canonical_data ->> 'entity_type',
                   canonical_data ->> 'power_state',
                   canonical_data ->> 'parent_ninja_id',
                   canonical_data ->> 'last_boot_time_at',
                   canonical_data ->> 'hypervisor_reported_boot_time_at',
                   material_projection_version,
                   octet_length(raw_hash), octet_length(material_hash)
              FROM operations.entity_observation_current
            """
        )
        assert cursor.fetchone() == (
            False,
            datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
            datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
            datetime(2026, 6, 4, 12, tzinfo=timezone.utc),
            None,
            None,
            None,
            "device",
            "42",
            "vm.guest",
            "powered_on",
            "7",
            "2026-06-01T09:00:00+00:00",
            "2026-08-01T13:00:00+00:00",
            3,
            32,
            32,
        )
        cursor.execute(
            """
            SELECT effective_from, effective_to, last_seen_at, active,
                   closed_by_snapshot_run_id, client_id, device_id,
                   material_projection_version
              FROM operations.entity_observation_history
            """
        )
        assert cursor.fetchone() == (
            datetime(2026, 6, 1, 12, tzinfo=timezone.utc),
            datetime(2026, 6, 4, 12, tzinfo=timezone.utc),
            datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
            True,
            None,
            None,
            None,
            3,
        )
        assert (
            process_day(
                cursor,
                tenant_id=1,
                rollup_day=date(2026, 6, 2),
                apply=True,
            ).inserted_rows
            == 1
        )
        repeated = process_range(
            cursor,
            tenant_id=1,
            start_day=date(2026, 6, 2),
            end_day=date(2026, 6, 3),
            apply=True,
        )
        assert (
            repeated.existing_generic_identities,
            repeated.missing_generic_identities,
            repeated.inserted_current_rows,
            repeated.inserted_history_rows,
        ) == (1, 0, 0, 0)
        cursor.execute("SELECT COUNT(*) FROM operations.device_links")
        assert cursor.fetchone() == (0,)

        cursor.executemany(
            """
            INSERT INTO ninja_core.devices
              (id, uid, node_class, data, first_seen_at, last_seen_at,
               is_current, missing_since)
            VALUES (%s, %s, 'WINDOWS_WORKSTATION', %s,
                    %s, %s, %s, %s)
            """,
            [
                (
                    43,
                    uuid.uuid4(),
                    '{"id":43}',
                    datetime(2026, 6, 2, 12, tzinfo=timezone.utc),
                    datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
                    True,
                    datetime(2026, 6, 4, 12, tzinfo=timezone.utc),
                ),
                (
                    44,
                    uuid.uuid4(),
                    "{}",
                    datetime(2026, 6, 2, 12, tzinfo=timezone.utc),
                    datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
                    False,
                    datetime(2026, 6, 4, 12, tzinfo=timezone.utc),
                ),
                (
                    45,
                    uuid.uuid4(),
                    '{"id":45}',
                    datetime(2026, 6, 2, 12, tzinfo=timezone.utc),
                    datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
                    False,
                    datetime(2026, 6, 4, 12, tzinfo=timezone.utc),
                ),
                (
                    46,
                    uuid.uuid4(),
                    '{"id":46}',
                    datetime(2026, 6, 2, 12, tzinfo=timezone.utc),
                    datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
                    False,
                    datetime(2026, 6, 4, 12, tzinfo=timezone.utc),
                ),
                (
                    47,
                    uuid.uuid4(),
                    '{"id":47}',
                    datetime(2026, 6, 2, 12, tzinfo=timezone.utc),
                    datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
                    False,
                    None,
                ),
                (
                    48,
                    uuid.uuid4(),
                    '{"id":48}',
                    datetime(2026, 6, 2, 12, tzinfo=timezone.utc),
                    datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
                    False,
                    datetime(2026, 6, 4, 12, tzinfo=timezone.utc),
                ),
            ],
        )
        cursor.executemany(
            """
            INSERT INTO ninja_core.device_snapshots (snapshot_at, device_id)
            VALUES ('2026-06-03T12:00:00Z', %s)
            """,
            [(device_id,) for device_id in range(43, 49)],
        )
        cursor.execute(
            """
            INSERT INTO operations.device_links
            VALUES (1, 1, '45', %s)
            """,
            (uuid.uuid4(),),
        )
        cursor.execute(
            """
            INSERT INTO operations.entity_observation_history
              (id, tenant_id, source_binding_id, source_instance_id,
               last_seen_binding_id, external_namespace,
               parent_external_namespace, parent_external_id, external_id,
               collector_instance_id, client_id, device_id, entity_type,
               platform, parent_source_key, entity_key, effective_from,
               effective_to, last_seen_at, received_at, material_data,
               material_hash, hash_algorithm_version,
               material_projection_version, active,
               closed_by_snapshot_run_id)
            SELECT %s, tenant_id, source_binding_id, source_instance_id,
                   last_seen_binding_id, external_namespace,
                   parent_external_namespace, parent_external_id, '48',
                   collector_instance_id, NULL, NULL, entity_type, platform,
                   parent_source_key, '48', effective_from, effective_to,
                   last_seen_at, received_at, material_data, material_hash,
                   hash_algorithm_version, material_projection_version,
                   active, closed_by_snapshot_run_id
              FROM operations.entity_observation_history
             WHERE external_id = '42'
            """,
            (uuid.uuid4(),),
        )
        blocked = process_range(
            cursor,
            tenant_id=1,
            start_day=date(2026, 6, 2),
            end_day=date(2026, 6, 3),
            apply=False,
        )
        assert (
            blocked.current_legacy_blockers,
            blocked.withdrawal_boundary_blockers,
            blocked.raw_evidence_blockers,
            blocked.canonical_link_blockers,
            blocked.history_evidence_blockers,
            blocked.interval_blockers,
        ) == (1, 1, 1, 1, 1, 1)
        assert blocked.blocked_identities == 6
        with pytest.raises(RestorationBlocked, match="fail-closed"):
            process_range(
                cursor,
                tenant_id=1,
                start_day=date(2026, 6, 2),
                end_day=date(2026, 6, 3),
                apply=True,
            )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
