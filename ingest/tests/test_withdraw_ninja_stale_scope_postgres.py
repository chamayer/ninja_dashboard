"""Opt-in PostgreSQL coverage for the retired Ninja-scope correction."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from ingest.withdraw_ninja_stale_scope import (
    NINJA_SOURCE_BINDING_ID,
    NINJA_SOURCE_INSTANCE_ID,
    StaleScopeBlocked,
    process,
)


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn) as connection:
            yield connection


def test_withdrawal_is_pinned_atomic_and_idempotent(postgres_connection) -> None:
    source_record_id = uuid.uuid4()
    canonical_device_id = uuid.uuid4()
    missing_since = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
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
                source_instance_id uuid NOT NULL
            );
            CREATE TABLE operations.devices (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL
            );
            CREATE TABLE ninja_core.devices (
                id integer PRIMARY KEY,
                is_current boolean NOT NULL,
                missing_since timestamptz
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
                device_id uuid,
                platform varchar(80) NOT NULL,
                observed_at timestamptz NOT NULL,
                last_seen_at timestamptz NOT NULL,
                last_received_at timestamptz NOT NULL,
                active boolean NOT NULL,
                withdrawn_at timestamptz,
                snapshot_scope varchar(120) NOT NULL,
                last_snapshot_run_id uuid,
                raw_data jsonb NOT NULL,
                material_hash bytea NOT NULL,
                material_projection_version integer NOT NULL
            );
            CREATE TABLE operations.entity_observation_history (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_instance_id uuid NOT NULL,
                external_namespace varchar(120) NOT NULL,
                parent_external_namespace varchar(120) NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL,
                effective_from timestamptz NOT NULL,
                effective_to timestamptz,
                last_seen_at timestamptz NOT NULL,
                active boolean NOT NULL,
                material_hash bytea NOT NULL,
                material_projection_version integer NOT NULL,
                closed_by_snapshot_run_id uuid
            );
            CREATE TABLE operations.source_record_seen_daily (
                tenant_id bigint NOT NULL,
                source_record_id uuid NOT NULL,
                rollup_day date NOT NULL,
                PRIMARY KEY (tenant_id, source_record_id, rollup_day)
            );
            """
        )
        cursor.execute("INSERT INTO operations.sources VALUES (1, 'Ninja')")
        cursor.execute(
            "INSERT INTO operations.source_instances VALUES (%s, 1, 1)",
            (NINJA_SOURCE_INSTANCE_ID,),
        )
        cursor.execute(
            "INSERT INTO operations.source_bindings VALUES (%s, 1, %s)",
            (NINJA_SOURCE_BINDING_ID, NINJA_SOURCE_INSTANCE_ID),
        )
        cursor.execute(
            "INSERT INTO operations.devices VALUES (%s, 1)",
            (canonical_device_id,),
        )
        cursor.execute(
            "INSERT INTO ninja_core.devices VALUES (42, FALSE, %s)",
            (missing_since,),
        )
        cursor.execute(
            """
            INSERT INTO operations.entity_observation_current
              (observation_id, tenant_id, source_binding_id, source_instance_id,
               last_seen_binding_id, external_namespace,
               parent_external_namespace, parent_external_id, external_id,
               device_id, platform, observed_at, last_seen_at, last_received_at,
               active, withdrawn_at, snapshot_scope, last_snapshot_run_id,
               raw_data, material_hash, material_projection_version)
            VALUES
              (%s, 1, %s, %s, %s, 'device', '', '', '42', %s, 'Ninja',
               '2026-07-20T12:00:00Z', '2026-07-20T12:00:00Z',
               '2026-07-22T12:00:00Z', TRUE, NULL, 'ninja_main', NULL,
               '{"retained":true}', decode(repeat('01', 32), 'hex'), 1)
            """,
            (
                source_record_id,
                NINJA_SOURCE_BINDING_ID,
                NINJA_SOURCE_INSTANCE_ID,
                NINJA_SOURCE_BINDING_ID,
                canonical_device_id,
            ),
        )
        cursor.execute(
            """
            INSERT INTO operations.entity_observation_history
              (id, tenant_id, source_instance_id, external_namespace,
               parent_external_namespace, parent_external_id, external_id,
               effective_from, effective_to, last_seen_at, active,
               material_hash, material_projection_version,
               closed_by_snapshot_run_id)
            VALUES
              (%s, 1, %s, 'device', '', '', '42',
               '2026-07-14T12:00:00Z', NULL, '2026-07-20T12:00:00Z', TRUE,
               decode(repeat('01', 32), 'hex'), 1, NULL)
            """,
            (uuid.uuid4(), NINJA_SOURCE_INSTANCE_ID),
        )
        cursor.execute(
            "INSERT INTO operations.source_record_seen_daily VALUES (1, %s, '2026-07-20')",
            (source_record_id,),
        )

        measured = process(cursor, tenant_id=1, apply=False)
        assert (
            measured.active_records,
            measured.eligible_records,
            measured.blocked_records,
            measured.updated_current_rows,
        ) == (1, 1, 0, 0)
        cursor.execute(
            "SELECT active, withdrawn_at FROM operations.entity_observation_current"
        )
        assert cursor.fetchone() == (True, None)

        with pytest.raises(StaleScopeBlocked, match="approved target"):
            process(
                cursor,
                tenant_id=1,
                apply=True,
                expected_count=1,
                expected_digest="0" * 64,
            )

        applied = process(
            cursor,
            tenant_id=1,
            apply=True,
            expected_count=measured.eligible_records,
            expected_digest=measured.eligible_identity_digest,
        )
        assert (applied.updated_current_rows, applied.closed_history_rows) == (1, 1)
        cursor.execute(
            """
            SELECT active, withdrawn_at, raw_data, device_id,
                   last_snapshot_run_id
              FROM operations.entity_observation_current
            """
        )
        assert cursor.fetchone() == (
            False,
            missing_since,
            {"retained": True},
            canonical_device_id,
            None,
        )
        cursor.execute(
            """
            SELECT effective_to, last_seen_at, active,
                   closed_by_snapshot_run_id
              FROM operations.entity_observation_history
            """
        )
        assert cursor.fetchone() == (
            missing_since,
            datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
            True,
            None,
        )
        cursor.execute(
            """
            -- The source-link stand-in and its count were dropped with
            -- migration 0121. withdraw_ninja_stale_scope never referenced
            -- that relation, so the assertion was vacuous rather than a
            -- guarantee about attachment.
            SELECT (SELECT COUNT(*) FROM operations.devices),
                   (SELECT COUNT(*) FROM operations.source_record_seen_daily)
            """
        )
        assert cursor.fetchone() == (1, 1)

        repeated = process(
            cursor,
            tenant_id=1,
            apply=True,
            expected_count=measured.eligible_records,
            expected_digest=measured.eligible_identity_digest,
        )
        assert (
            repeated.already_corrected_records,
            repeated.updated_current_rows,
            repeated.closed_history_rows,
        ) == (1, 0, 0)

        cursor.execute(
            "INSERT INTO ninja_core.devices VALUES (43, TRUE, '2026-07-21T12:00:00Z')"
        )
        blocker_record_id = uuid.uuid4()
        cursor.execute(
            """
            INSERT INTO operations.entity_observation_current
              (observation_id, tenant_id, source_binding_id, source_instance_id,
               last_seen_binding_id, external_namespace,
               parent_external_namespace, parent_external_id, external_id,
               platform, observed_at, last_seen_at, last_received_at,
               active, withdrawn_at, snapshot_scope, last_snapshot_run_id,
               raw_data, material_hash, material_projection_version)
            VALUES
              (%s, 1, %s, %s, %s, 'device', '', '', '43', 'Ninja',
               '2026-07-20T12:00:00Z', '2026-07-20T12:00:00Z',
               '2026-07-20T12:00:00Z', TRUE, NULL, 'ninja_main', NULL,
               '{}', decode(repeat('02', 32), 'hex'), 1)
            """,
            (
                blocker_record_id,
                NINJA_SOURCE_BINDING_ID,
                NINJA_SOURCE_INSTANCE_ID,
                NINJA_SOURCE_BINDING_ID,
            ),
        )
        cursor.execute(
            """
            INSERT INTO operations.entity_observation_history
              (id, tenant_id, source_instance_id, external_namespace,
               parent_external_namespace, parent_external_id, external_id,
               effective_from, effective_to, last_seen_at, active,
               material_hash, material_projection_version)
            VALUES
              (%s, 1, %s, 'device', '', '', '43',
               '2026-07-14T12:00:00Z', NULL, '2026-07-20T12:00:00Z', TRUE,
               decode(repeat('02', 32), 'hex'), 1)
            """,
            (uuid.uuid4(), NINJA_SOURCE_INSTANCE_ID),
        )
        blocked = process(cursor, tenant_id=1, apply=False)
        assert (blocked.blocked_records, blocked.current_legacy_device_blockers) == (
            1,
            1,
        )
        with pytest.raises(StaleScopeBlocked, match="eligibility blockers"):
            process(
                cursor,
                tenant_id=1,
                apply=True,
                expected_count=1,
                expected_digest=measured.eligible_identity_digest,
            )
