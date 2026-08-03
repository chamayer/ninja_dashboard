"""Opt-in PostgreSQL coverage for the ADR-0009 stable-identity cutover."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.observations import write_current_rows


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_INTEGRATION_TESTS=1 to start a disposable Postgres container"
        )
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn) as connection:
            yield connection


def test_current_history_and_run_dual_write(postgres_connection) -> None:
    binding_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    observation_id = uuid.uuid4()
    collector_id = uuid.uuid4()
    observed_at = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)

    with postgres_connection.transaction(), postgres_connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA operations")
        cursor.execute("""
            CREATE TABLE operations.source_bindings (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_instance_id uuid NOT NULL
            );
            CREATE TABLE operations.observation_snapshot_runs (
                run_id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NOT NULL,
                snapshot_scope text NOT NULL,
                snapshot_at timestamptz NOT NULL,
                run_started_at timestamptz NULL,
                is_complete_snapshot boolean NULL,
                status text NOT NULL,
                expected_rows integer NOT NULL,
                written_rows integer NOT NULL,
                failed_rows integer NOT NULL,
                error text NOT NULL,
                completed_at timestamptz NULL,
                observed_identity_count integer NOT NULL,
                observed_identity_digest bytea NULL
            );
            CREATE TABLE operations.entity_observation_current (
                observation_id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NOT NULL,
                last_seen_binding_id uuid NULL,
                external_namespace text NOT NULL DEFAULT '',
                parent_external_namespace text NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL DEFAULT '',
                collector_instance_id uuid NOT NULL,
                client_id uuid NULL,
                device_id uuid NULL,
                entity_type text NOT NULL,
                parent_source_key text NOT NULL DEFAULT '',
                entity_key text NOT NULL,
                platform text NOT NULL,
                subplatform text NOT NULL,
                observed_at timestamptz NOT NULL,
                last_seen_at timestamptz NOT NULL,
                last_received_at timestamptz NOT NULL,
                active boolean NOT NULL,
                withdrawn_at timestamptz NULL,
                snapshot_scope text NOT NULL,
                last_snapshot_run_id uuid NULL,
                raw_data jsonb NOT NULL,
                canonical_data jsonb NOT NULL,
                raw_hash bytea NULL,
                material_hash bytea NOT NULL,
                hash_algorithm_version smallint NOT NULL,
                batch_id uuid NOT NULL,
                collector_version text NOT NULL,
                schema_version smallint NOT NULL,
                UNIQUE (tenant_id, source_instance_id, external_namespace,
                        parent_external_namespace, parent_external_id, external_id)
            );
            CREATE TABLE operations.entity_observation_history (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                source_binding_id uuid NOT NULL,
                source_instance_id uuid NOT NULL,
                last_seen_binding_id uuid NULL,
                external_namespace text NOT NULL DEFAULT '',
                parent_external_namespace text NOT NULL DEFAULT '',
                parent_external_id text NOT NULL DEFAULT '',
                external_id text NOT NULL DEFAULT '',
                collector_instance_id uuid NOT NULL,
                client_id uuid NULL,
                device_id uuid NULL,
                entity_type text NOT NULL,
                platform text NOT NULL,
                parent_source_key text NOT NULL DEFAULT '',
                entity_key text NOT NULL,
                effective_from timestamptz NOT NULL,
                effective_to timestamptz NULL,
                last_seen_at timestamptz NOT NULL,
                received_at timestamptz NOT NULL,
                material_data jsonb NOT NULL,
                material_hash bytea NOT NULL,
                hash_algorithm_version smallint NOT NULL,
                active boolean NOT NULL,
                closed_by_snapshot_run_id uuid NULL
            );
            CREATE UNIQUE INDEX uq_test_history_stable
                ON operations.entity_observation_history
                   (tenant_id, source_instance_id, external_namespace,
                    parent_external_namespace, parent_external_id, external_id)
                WHERE effective_to IS NULL;
        """)
        cursor.execute(
            "INSERT INTO operations.source_bindings VALUES (%s, 1, %s)",
            (binding_id, instance_id),
        )

        run_id, resolved_instance_id = begin_run(
            cursor, 1, binding_id, "Ninja", observed_at, expected_rows=1
        )
        assert resolved_instance_id == instance_id

        first_row = {
            "observation_id": observation_id,
            "tenant_id": 1,
            "source_binding_id": binding_id,
            "source_instance_id": instance_id,
            "last_seen_binding_id": binding_id,
            "external_namespace": "device",
            "parent_external_namespace": "",
            "parent_external_id": "",
            "external_id": "42",
            "collector_instance_id": collector_id,
            "client_id": None,
            "device_id": None,
            "entity_type": "agent.rmm",
            "parent_source_key": "",
            "entity_key": "42",
            "platform": "Ninja",
            "subplatform": "",
            "observed_at": observed_at,
            "last_seen_at": observed_at,
            "last_received_at": observed_at,
            "active": True,
            "withdrawn_at": None,
            "snapshot_scope": "Ninja",
            "last_snapshot_run_id": run_id,
            "raw_data": {"record": 42},
            "canonical_data": {"hostname": "test-host"},
            "raw_hash": b"r" * 32,
            "batch_id": uuid.uuid4(),
            "collector_version": "",
            "schema_version": 1,
        }
        written = write_current_rows(cursor, [first_row])
        assert written == 1
        complete_run(
            cursor,
            run_id,
            written,
            is_complete_snapshot=True,
            identity_rows=[first_row],
        )

        cursor.execute("""
            SELECT c.source_instance_id, c.last_seen_binding_id,
                   c.external_namespace, c.parent_external_namespace,
                   c.parent_external_id, c.external_id,
                   h.source_instance_id = c.source_instance_id,
                   h.last_seen_binding_id = c.last_seen_binding_id,
                   h.external_namespace = c.external_namespace,
                   h.external_id = c.external_id
              FROM operations.entity_observation_current c
              JOIN operations.entity_observation_history h
                ON h.id = c.observation_id
        """)
        assert cursor.fetchone() == (
            instance_id,
            binding_id,
            "device",
            "",
            "",
            "42",
            True,
            True,
            True,
            True,
        )
        cursor.execute(
            """
            SELECT source_instance_id, run_started_at = snapshot_at,
                   status, is_complete_snapshot, observed_identity_count,
                   octet_length(observed_identity_digest)
              FROM operations.observation_snapshot_runs
             WHERE run_id = %s
        """,
            (run_id,),
        )
        assert cursor.fetchone() == (instance_id, True, "complete", True, 1, 32)

        absent_at = datetime(2026, 8, 2, 13, 0, tzinfo=timezone.utc)
        absent_run, _ = begin_run(
            cursor, 1, binding_id, "Ninja", absent_at, expected_rows=0
        )
        complete_run(
            cursor,
            absent_run,
            0,
            is_complete_snapshot=True,
            identity_rows=[],
        )
        assert reconcile_complete_run(cursor, absent_run) == 1

        cursor.execute("""
            SELECT c.active, c.withdrawn_at, c.last_snapshot_run_id,
                   h.active, h.effective_to, h.last_seen_at,
                   h.closed_by_snapshot_run_id
              FROM operations.entity_observation_current c
              JOIN operations.entity_observation_history h
                ON h.source_instance_id = c.source_instance_id
               AND h.external_namespace = c.external_namespace
               AND h.external_id = c.external_id
        """)
        assert cursor.fetchone() == (
            False,
            absent_at,
            absent_run,
            True,
            absent_at,
            observed_at,
            absent_run,
        )

        replacement_binding_id = uuid.uuid4()
        cursor.execute(
            "INSERT INTO operations.source_bindings VALUES (%s, 1, %s)",
            (replacement_binding_id, instance_id),
        )
        restored_at = datetime(2026, 8, 2, 14, 0, tzinfo=timezone.utc)
        restored_run, _ = begin_run(
            cursor, 1, replacement_binding_id, "Ninja", restored_at, expected_rows=1
        )
        restored_row = dict(first_row)
        restored_row.update(
            observation_id=uuid.uuid4(),
            source_binding_id=replacement_binding_id,
            last_seen_binding_id=replacement_binding_id,
            entity_type="vm.guest",
            entity_key="mutable-legacy-key",
            observed_at=restored_at,
            last_seen_at=restored_at,
            last_received_at=restored_at,
            active=True,
            withdrawn_at=None,
            last_snapshot_run_id=restored_run,
            batch_id=uuid.uuid4(),
        )
        assert write_current_rows(cursor, [restored_row]) == 1
        complete_run(
            cursor,
            restored_run,
            1,
            is_complete_snapshot=True,
            identity_rows=[restored_row],
        )
        assert reconcile_complete_run(cursor, restored_run) == 0

        cursor.execute(
            """
            SELECT COUNT(*), BOOL_AND(active),
                   COUNT(DISTINCT source_binding_id) = 1,
                   COUNT(DISTINCT entity_type) = 1
              FROM operations.entity_observation_current
             WHERE source_instance_id = %s
               AND external_namespace = 'device'
               AND external_id = '42'
        """,
            (instance_id,),
        )
        assert cursor.fetchone() == (1, True, True, True)
        cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE effective_to IS NULL)
              FROM operations.entity_observation_history
             WHERE source_instance_id = %s
               AND external_namespace = 'device'
               AND external_id = '42'
        """,
            (instance_id,),
        )
        assert cursor.fetchone() == (2, 1)


def test_begin_run_holds_one_scope_lock_for_the_source_transaction(
    postgres_connection,
) -> None:
    with postgres_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, source_instance_id
              FROM operations.source_bindings
             ORDER BY id
             LIMIT 1
            """
        )
        binding_id, instance_id = cursor.fetchone()

    with psycopg.connect(
        postgres_connection.info.dsn, password="test"
    ) as competing_connection:
        with postgres_connection.transaction(), postgres_connection.cursor() as cursor:
            begin_run(
                cursor,
                1,
                binding_id,
                "Ninja",
                datetime(2026, 8, 2, 15, 0, tzinfo=timezone.utc),
            )
            with competing_connection.cursor() as competing_cursor:
                competing_cursor.execute(
                    """
                    SELECT pg_try_advisory_xact_lock(
                        hashtextextended(%s || '|' || %s || '|' || %s, 0)
                    )
                    """,
                    ("1", str(instance_id), "Ninja"),
                )
                assert competing_cursor.fetchone()[0] is False
