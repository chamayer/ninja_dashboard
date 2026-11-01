"""Bounded PostgreSQL check for durable malformed-intake subjects."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from ingest.source_observations import _persist_intake_errors


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


def test_intake_errors_are_durable_and_idempotent(postgres_connection):
    source_instance_id = uuid.uuid4()
    run_id = uuid.uuid4()
    errors = [
        (2, "missing stable source-record identity", "agent.test"),
        (7, "missing stable container identity", "agent.test"),
    ]
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute("CREATE SCHEMA operations")
        cur.execute(
            """
            CREATE TABLE operations.source_record_subjects (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id bigint NOT NULL,
                subject_kind text NOT NULL,
                source_instance_id uuid NOT NULL,
                source_run_id uuid NOT NULL,
                item_ordinal integer NOT NULL,
                intake_error text NOT NULL,
                platform varchar(80) NOT NULL,
                entity_type varchar(80) NOT NULL
            );
            CREATE UNIQUE INDEX uq_source_record_subjects_intake_error
                ON operations.source_record_subjects (tenant_id, source_run_id, item_ordinal)
                WHERE subject_kind = 'intake_error';
            """
        )
        _persist_intake_errors(cur, 1, source_instance_id, run_id, "Test", errors)
        _persist_intake_errors(cur, 1, source_instance_id, run_id, "Test", errors)
        cur.execute(
            """
            SELECT item_ordinal, intake_error, platform, entity_type
              FROM operations.source_record_subjects
             WHERE tenant_id = 1 AND subject_kind = 'intake_error'
             ORDER BY item_ordinal
            """
        )
        assert cur.fetchall() == [
            (2, "missing stable source-record identity", "Test", "agent.test"),
            (7, "missing stable container identity", "Test", "agent.test"),
        ]
