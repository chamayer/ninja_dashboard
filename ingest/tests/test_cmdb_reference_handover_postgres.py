"""Bounded PostgreSQL coverage for CMDB-to-source-record finding handover."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from ingest.cmdb_findings import _enqueue_reference_reassessments


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


def test_only_uncovered_reference_owners_are_requeued(postgres_connection):
    instance_id = uuid.uuid4()
    current_subject, missing_subject, wrong_owner_subject = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA operations;
            CREATE TABLE operations.source_record_subjects (
                id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
                subject_kind text NOT NULL, platform text NOT NULL,
                entity_type text NOT NULL, source_instance_id uuid NOT NULL,
                external_id text NOT NULL
            );
            CREATE TABLE operations.source_record_assessment_current (
                tenant_id bigint NOT NULL, target_kind text NOT NULL,
                target_id uuid NOT NULL, rule_key text NOT NULL,
                dimension text NOT NULL, work_owner text NOT NULL
            );
            CREATE TABLE operations.source_record_assessment_queue (
                tenant_id bigint NOT NULL, target_kind text NOT NULL,
                target_id uuid NOT NULL, PRIMARY KEY (tenant_id, target_kind, target_id)
            );
            CREATE FUNCTION operations.source_record_enqueue(
                p_tenant bigint, p_kind text, p_target uuid, p_key jsonb DEFAULT '{}'::jsonb
            ) RETURNS void LANGUAGE sql AS $$
                INSERT INTO operations.source_record_assessment_queue
                VALUES (p_tenant, p_kind, p_target)
                ON CONFLICT DO NOTHING
            $$;
            """
        )
        cur.executemany(
            """
            INSERT INTO operations.source_record_subjects
            VALUES (%s, 1, 'record', 'Hudu', 'cmdb.asset', %s, %s)
            """,
            [
                (current_subject, instance_id, "stale-1"),
                (missing_subject, instance_id, "stale-2"),
                (wrong_owner_subject, instance_id, "divergent-1"),
            ],
        )
        cur.execute(
            """
            INSERT INTO operations.source_record_assessment_current
            VALUES (1, 'source_record', %s, 'record.reference',
                    'hudu_device_reference', 'legacy:cmdb_asset_stale'),
                   (1, 'source_record', %s, 'record.reference',
                    'hudu_device_reference', '')
            """,
            (current_subject, wrong_owner_subject),
        )

        _enqueue_reference_reassessments(
            cur,
            {
                (instance_id, "stale-1", "legacy:cmdb_asset_stale"),
                (instance_id, "stale-2", "legacy:cmdb_asset_stale"),
                (instance_id, "divergent-1", "legacy:cmdb_link_incorrect"),
            },
        )

        cur.execute(
            "SELECT target_id FROM operations.source_record_assessment_queue ORDER BY target_id"
        )
        assert {row[0] for row in cur.fetchall()} == {
            missing_subject,
            wrong_owner_subject,
        }
