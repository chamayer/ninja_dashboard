"""PostgreSQL coverage for grouped source-role health assessment and clearing."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.types.json import Jsonb

from ingest import platform_findings


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


def test_policy_gap_groups_by_source_and_reassesses_disappeared_episode(
    postgres_connection, monkeypatch
):
    connection = postgres_connection
    source_a, source_b = uuid.uuid4(), uuid.uuid4()
    stale_signal = uuid.uuid4()
    with connection.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA operations;
            CREATE TABLE operations.source_record_subjects (
                tenant_id bigint NOT NULL, subject_kind text NOT NULL,
                source_instance_id uuid NOT NULL, platform text NOT NULL,
                entity_type text NOT NULL, record_role text NOT NULL,
                presence text NOT NULL
            );
            CREATE TABLE operations.findings (
                id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
                condition_namespace text NOT NULL, finding_type_id integer NOT NULL,
                condition_key text NOT NULL, subject_ref jsonb NOT NULL,
                status text NOT NULL
            );
            """,
        )
        cur.executemany(
            """INSERT INTO operations.source_record_subjects VALUES
                   (1, 'record', %s, 'Ninja', %s, %s, 'present')""",
            [
                (source_a, "agent.rmm", "unclassified"),
                (source_a, "agent.rmm", "unclassified"),
                (source_b, "agent.edr", "unclassified"),
                (source_a, "agent.rmm", "endpoint_agent"),
            ],
        )
        cur.execute(
            """INSERT INTO operations.source_record_subjects VALUES
                   (2, 'record', %s, 'Ninja', 'agent.rmm', 'unclassified', 'present')""",
            (source_a,),
        )
        cur.execute(
            """INSERT INTO operations.findings VALUES
                   (%s, 1, 'admin', 385,
                    'source_record_policy_incomplete:old:agent.rmm', %s, 'open')""",
            (uuid.uuid4(), Jsonb({"signal_id": str(stale_signal)})),
        )
    connection.commit()

    upserts = []
    assessments = []

    def upsert(cur, **kwargs):
        upserts.append(kwargs)
        finding_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO operations.findings
                   (id, tenant_id, condition_namespace, finding_type_id,
                    condition_key, subject_ref, status)
               VALUES (%s, 1, 'admin', %s, %s, %s, 'open')""",
            (
                finding_id,
                kwargs["finding_type_id"],
                kwargs["condition_key"],
                Jsonb(kwargs["subject_ref"]),
            ),
        )
        return finding_id

    monkeypatch.setattr(platform_findings, "_upsert_admin_finding", upsert)
    monkeypatch.setattr(
        platform_findings,
        "_record_platform_assessment",
        lambda _cur,
        finding_id,
        key,
        rule,
        subject_id,
        _now,
        measured: assessments.append((finding_id, key, rule, subject_id, measured)),
    )
    counts = {"source_record_policy_incomplete": 0}
    with connection.cursor() as cur:
        keys = platform_findings._eval_source_record_policy_gaps(
            cur, 385, datetime.now(timezone.utc), counts, dry_run=False
        )

    expected = {
        f"source_record_policy_incomplete:{source_a}:agent.rmm",
        f"source_record_policy_incomplete:{source_b}:agent.edr",
    }
    assert set(keys) == expected
    assert counts["source_record_policy_incomplete"] == 2
    assert {row["details"]["affected_record_count"] for row in upserts} == {1, 2}
    assert {assessment[1] for assessment in assessments} == expected | {
        "source_record_policy_incomplete:old:agent.rmm"
    }
    assert all(assessment[4] is True for assessment in assessments)
