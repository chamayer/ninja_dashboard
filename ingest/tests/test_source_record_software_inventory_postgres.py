"""PostgreSQL coverage for source-record software current and history writes."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from ingest.inventory.software import _apply_source_record_rows


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 to start disposable Postgres")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn) as connection:
            yield connection


def test_software_source_rows_open_change_and_unchanged_history(postgres_connection):
    connection = postgres_connection
    subject_id = uuid.uuid4()
    first = datetime(2026, 10, 1, tzinfo=timezone.utc)
    changed = datetime(2026, 10, 2, tzinfo=timezone.utc)
    refreshed = datetime(2026, 10, 3, tzinfo=timezone.utc)
    relisted = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with connection.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA operations;
            CREATE TABLE operations.source_record_software_current (
                tenant_id bigint NOT NULL, source_record_id uuid NOT NULL,
                canonical_name text NOT NULL, display_name text NOT NULL,
                publisher text, version text, install_location text,
                install_date date, product_code text, size_bytes bigint,
                is_system_component boolean, material_hash bytea NOT NULL,
                first_observed_at timestamptz NOT NULL,
                last_observed_at timestamptz NOT NULL, refreshed_at timestamptz NOT NULL,
                stale_since timestamptz, stale_reason text NOT NULL,
                PRIMARY KEY (tenant_id, source_record_id, canonical_name)
            );
            CREATE TABLE operations.source_record_software_history (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
                source_record_id uuid NOT NULL, canonical_name text NOT NULL,
                display_name text NOT NULL, publisher text, version text,
                install_location text, install_date date, product_code text,
                size_bytes bigint, is_system_component boolean, material_hash bytea NOT NULL,
                effective_from timestamptz NOT NULL, effective_to timestamptz,
                last_seen_at timestamptz NOT NULL, received_at timestamptz NOT NULL,
                active boolean NOT NULL
            );
            CREATE TABLE operations.source_record_assessment_queue (
                tenant_id bigint NOT NULL, target_kind text NOT NULL,
                target_id uuid NOT NULL, PRIMARY KEY (tenant_id, target_kind, target_id)
            );
            CREATE FUNCTION operations.source_record_enqueue(
                p_tenant bigint, p_kind text, p_target uuid
            ) RETURNS void LANGUAGE SQL AS $$
                INSERT INTO operations.source_record_assessment_queue
                    VALUES (p_tenant, p_kind, p_target) ON CONFLICT DO NOTHING
            $$;
            """
        )
    connection.commit()

    def row(version: str, digest: bytes, collected_at: datetime):
        return (
            subject_id,
            "sample app",
            "Sample App",
            "Vendor",
            version,
            None,
            None,
            None,
            None,
            False,
            digest,
            collected_at,
        )

    for listed, at, expected in (
        ((("1.0", b"one"),), first, 1),
        ((("2.0", b"two"),), changed, 1),
        ((("2.0", b"two"),), refreshed, 0),
        # A list naming the title twice: one history row, the last listed wins.
        ((("3.0", b"three"), ("3.1", b"three-one")), relisted, 1),
    ):
        rows = [row(version, digest, at) for version, digest in listed]
        with connection.transaction(), connection.cursor() as cur:
            assert _apply_source_record_rows(cur, rows, at) == expected
    with connection.cursor() as cur:
        cur.execute(
            """SELECT version, effective_from, effective_to, active
                 FROM operations.source_record_software_history
                ORDER BY effective_from"""
        )
        history = cur.fetchall()
        assert history == [
            ("1.0", first, changed, False),
            ("2.0", changed, relisted, False),
            ("3.1", relisted, None, True),
        ]
        cur.execute(
            """SELECT version, first_observed_at, last_observed_at
                 FROM operations.source_record_software_current"""
        )
        assert cur.fetchone() == ("3.1", first, relisted)
        cur.execute("SELECT target_id FROM operations.source_record_assessment_queue")
        assert cur.fetchall() == [(subject_id,)]
