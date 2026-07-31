"""Opt-in PostgreSQL coverage for shared-serial resolver findings."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from ingest.identity.resolver import _upsert_shared_serial_findings


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


def test_shared_serial_finding_uses_uuid_subject_and_refreshes(
    postgres_connection,
) -> None:
    client_id = uuid.uuid4()
    first_device_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_device_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    with postgres_connection.cursor() as cur:
        cur.execute("CREATE EXTENSION pgcrypto")
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
        """)
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
