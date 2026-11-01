"""PostgreSQL coverage for Computer-page source-finding history overlap."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from operations.apps.core.source_record_findings import (
    associated_source_record_finding_ids,
)


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


def test_only_active_finding_episodes_overlapping_device_link_history_are_included(
    postgres_connection,
):
    connection = postgres_connection
    device_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    record_ids = [uuid.uuid4() for _ in range(6)]
    findings = [uuid.uuid4() for _ in record_ids]
    jan1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    jan3 = datetime(2026, 1, 3, tzinfo=timezone.utc)
    jan4 = datetime(2026, 1, 4, tzinfo=timezone.utc)
    jan5 = datetime(2026, 1, 5, tzinfo=timezone.utc)
    jan10 = datetime(2026, 1, 10, tzinfo=timezone.utc)
    with connection.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA operations;
            CREATE TABLE operations.findings (
                id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
                subject_type text NOT NULL, subject_id uuid NOT NULL,
                condition_namespace text NOT NULL, status text NOT NULL,
                first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL
            );
            CREATE TABLE operations.source_record_subjects (
                id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
                subject_kind text NOT NULL, source_instance_id uuid NOT NULL,
                external_namespace text NOT NULL,
                parent_external_namespace text NOT NULL,
                parent_external_id text NOT NULL, external_id text NOT NULL
            );
            CREATE TABLE operations.entity_source_link_history (
                tenant_id bigint NOT NULL, source_instance_id uuid NOT NULL,
                external_namespace text NOT NULL,
                parent_external_namespace text NOT NULL,
                parent_external_id text NOT NULL, external_id text NOT NULL,
                entity_class_id text NOT NULL, entity_id uuid NOT NULL,
                effective_from timestamptz NOT NULL, effective_to timestamptz
            );
            """
        )
        subjects = [
            (record_ids[0], 1, "record", instance_id, "agent", "", "", "overlap"),
            (record_ids[1], 1, "record", instance_id, "agent", "", "", "boundary"),
            (record_ids[2], 1, "record", instance_id, "agent", "", "", "other-device"),
            (record_ids[3], 1, "record", instance_id, "agent", "", "", "later-link"),
            (record_ids[4], 1, "record", instance_id, "agent", "", "", "resolved"),
            (record_ids[5], 2, "record", instance_id, "agent", "", "", "other-tenant"),
        ]
        cur.executemany(
            "INSERT INTO operations.source_record_subjects VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            subjects,
        )
        finding_rows = [
            (
                findings[0],
                1,
                "source_record",
                record_ids[0],
                "entity",
                "open",
                jan3,
                jan5,
            ),
            (
                findings[1],
                1,
                "source_record",
                record_ids[1],
                "entity",
                "open",
                jan10,
                jan10,
            ),
            (
                findings[2],
                1,
                "source_record",
                record_ids[2],
                "entity",
                "open",
                jan3,
                jan5,
            ),
            (
                findings[3],
                1,
                "source_record",
                record_ids[3],
                "entity",
                "open",
                jan1,
                jan3,
            ),
            (
                findings[4],
                1,
                "source_record",
                record_ids[4],
                "entity",
                "resolved",
                jan3,
                jan5,
            ),
            (
                findings[5],
                2,
                "source_record",
                record_ids[5],
                "entity",
                "open",
                jan3,
                jan5,
            ),
        ]
        cur.executemany(
            "INSERT INTO operations.findings VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            finding_rows,
        )
        histories = [
            (
                1,
                instance_id,
                "agent",
                "",
                "",
                "overlap",
                "device",
                device_id,
                jan1,
                jan10,
            ),
            (
                1,
                instance_id,
                "agent",
                "",
                "",
                "boundary",
                "device",
                device_id,
                jan1,
                jan10,
            ),
            (
                1,
                instance_id,
                "agent",
                "",
                "",
                "other-device",
                "device",
                uuid.uuid4(),
                jan1,
                None,
            ),
            (
                1,
                instance_id,
                "agent",
                "",
                "",
                "later-link",
                "device",
                device_id,
                jan4,
                None,
            ),
            (
                1,
                instance_id,
                "agent",
                "",
                "",
                "resolved",
                "device",
                device_id,
                jan1,
                None,
            ),
            (
                2,
                instance_id,
                "agent",
                "",
                "",
                "other-tenant",
                "device",
                device_id,
                jan1,
                None,
            ),
        ]
        cur.executemany(
            "INSERT INTO operations.entity_source_link_history VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            histories,
        )
        cur.execute(
            """INSERT INTO operations.entity_source_link_history VALUES
                   (1,%s,'agent','','','overlap','org',%s,%s,NULL)""",
            (instance_id, device_id, jan1),
        )
    connection.commit()

    with connection.cursor() as cur:
        associated = associated_source_record_finding_ids(
            cur, 1, device_id, ["open", "acknowledged"]
        )
    assert associated == [record_ids[0]]
