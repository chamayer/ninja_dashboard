"""Opt-in PostgreSQL coverage for shared-serial resolver findings."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from ingest.identity.resolver import (
    _upsert_cross_client_serial_findings,
    _upsert_shared_serial_findings,
)


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
        with psycopg.connect(dsn, autocommit=True) as conn:
            yield conn


@pytest.fixture
def postgres_schema(postgres_connection):
    with postgres_connection.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute("DROP SCHEMA IF EXISTS operations CASCADE")
        cur.execute("CREATE SCHEMA operations")
        cur.execute("""
            CREATE TABLE operations.devices (
                id uuid PRIMARY KEY,
                tenant_id bigint NOT NULL,
                client_id uuid NOT NULL,
                canonical_serial text NOT NULL DEFAULT '',
                canonical_hostname text NOT NULL DEFAULT '',
                deleted_at timestamptz NULL
            );
            CREATE TABLE operations.findings (
                id uuid PRIMARY KEY,
                version integer NOT NULL,
                tenant_id bigint NOT NULL,
                finding_type_id smallint NOT NULL,
                client_id uuid NULL,
                subject_type varchar(32) NOT NULL,
                subject_id uuid NOT NULL,
                subject_layer varchar(80) NOT NULL DEFAULT '',
                subject_layer_entity_id uuid NULL,
                finding_details jsonb NOT NULL DEFAULT '{}',
                condition_key varchar(255) NOT NULL,
                severity varchar(16) NOT NULL,
                confidence varchar(16) NOT NULL,
                status varchar(24) NOT NULL,
                first_seen_at timestamptz NOT NULL,
                last_seen_at timestamptz NOT NULL,
                last_detected_at timestamptz NOT NULL
            );
            CREATE UNIQUE INDEX findings_open_condition_key
                ON operations.findings (tenant_id, condition_key)
                WHERE condition_key > '' AND status IN ('open', 'acknowledged');
            CREATE TABLE operations.identity_value_rejections (
                value_kind text NOT NULL,
                normalized_value text NOT NULL,
                enabled boolean NOT NULL DEFAULT true
            );
            CREATE TABLE operations.entity_observation_current (
                tenant_id bigint NOT NULL,
                device_id uuid NOT NULL,
                active boolean NOT NULL DEFAULT true,
                canonical_data jsonb NOT NULL DEFAULT '{}'
            );
        """)


def test_shared_serial_finding_uses_uuid_subject_and_refreshes(
    postgres_schema,
) -> None:
    client_id = uuid.uuid4()
    first_device_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_device_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    with postgres_schema.cursor() as cur:
        cur.execute(
            """
            INSERT INTO operations.devices (
                id, tenant_id, client_id, canonical_serial, canonical_hostname
            ) VALUES
                (%s, 1, %s, 'shared-serial', 'first-host'),
                (%s, 1, %s, 'shared-serial', 'second-host')
            """,
            (first_device_id, client_id, second_device_id, client_id),
        )

        assert _upsert_shared_serial_findings(cur, 1) == 1
        cur.execute("""
            SELECT subject_id, pg_typeof(subject_id)::text,
                   finding_details ->> 'device_count',
                   finding_details -> 'device_ids'
              FROM operations.findings
        """)
        subject_id, subject_type, device_count, device_ids = cur.fetchone()
        assert subject_id == first_device_id
        assert subject_type == "uuid"
        assert device_count == "2"
        assert device_ids == [str(first_device_id), str(second_device_id)]

        assert _upsert_shared_serial_findings(cur, 1) == 1
        cur.execute("SELECT COUNT(*) FROM operations.findings")
        assert cur.fetchone()[0] == 1


def test_cross_client_serial_emits_one_finding_per_device(
    postgres_schema,
) -> None:
    first_client_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
    second_client_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
    first_device_id = uuid.UUID("00000000-0000-0000-0000-000000000011")
    second_device_id = uuid.UUID("00000000-0000-0000-0000-000000000021")

    with postgres_schema.cursor() as cur:
        cur.execute(
            """
            INSERT INTO operations.devices (
                id, tenant_id, client_id, canonical_serial, canonical_hostname
            ) VALUES
                (%s, 1, %s, 'real-cross-client-serial', 'first-client-host'),
                (%s, 1, %s, 'real-cross-client-serial', 'second-client-host')
            """,
            (first_device_id, first_client_id, second_device_id, second_client_id),
        )
        cur.execute(
            """
            INSERT INTO operations.entity_observation_current (
                tenant_id, device_id, canonical_data
            ) VALUES
                (1, %s, '{"service_tag": "real-cross-client-serial"}'),
                (1, %s, '{"serial_number": "real-cross-client-serial"}')
            """,
            (first_device_id, second_device_id),
        )

        assert _upsert_cross_client_serial_findings(cur, 2) == 2
        cur.execute(
            """
            SELECT subject_id, client_id, finding_details ->> 'client_count'
            FROM operations.findings
            WHERE finding_type_id = 2
            ORDER BY subject_id
            """
        )
        assert cur.fetchall() == [
            (first_device_id, first_client_id, "2"),
            (second_device_id, second_client_id, "2"),
        ]

        # A second sweep refreshes both conditions rather than adding copies.
        assert _upsert_cross_client_serial_findings(cur, 2) == 2
        cur.execute("SELECT COUNT(*) FROM operations.findings WHERE finding_type_id = 2")
        assert cur.fetchone()[0] == 2
