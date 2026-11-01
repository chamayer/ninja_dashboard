"""PostgreSQL coverage for native Hudu reference finding ownership lifecycle."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from ingest import source_records


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


def test_native_reference_finding_resolves_when_link_is_corrected(
    postgres_connection, monkeypatch
):
    connection = postgres_connection
    target_id = uuid.uuid4()
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    with connection.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA operations;
            CREATE TABLE operations.findings (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(), version integer NOT NULL,
                tenant_id bigint NOT NULL, finding_type_id integer NOT NULL,
                client_id uuid, subject_type text NOT NULL, subject_id uuid NOT NULL,
                subject_layer text NOT NULL, finding_details jsonb NOT NULL,
                condition_key text NOT NULL, episode_key text, severity text NOT NULL,
                confidence text NOT NULL, status text NOT NULL,
                first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
                last_detected_at timestamptz NOT NULL, closed_at timestamptz,
                condition_namespace text NOT NULL DEFAULT 'entity'
            );
            CREATE UNIQUE INDEX uq_test_active_finding_condition
                ON operations.findings (tenant_id, condition_namespace, condition_key)
                WHERE condition_key > ''
                  AND status IN ('open', 'acknowledged', 'investigating', 'suppressed');
            """
        )
    connection.commit()

    recorded_conditions = []
    monkeypatch.setattr(
        source_records,
        "_record_condition",
        lambda _cur, _tenant, finding_id, *_args: recorded_conditions.append(
            finding_id
        ),
    )
    record = {
        "platform": "Hudu",
        "entity_type": "cmdb.asset",
        "record_role": "documentation",
        "presence": "present",
        "device_id": None,
        "device_live": False,
        "restricted": False,
        "canonical_data": {"link_verdict": "stale"},
    }
    reference = next(
        item
        for item in source_records.evaluate_record(record, {})
        if item["rule"] == "record.reference"
    )
    type_ids = {"source_record_reference_review": 386}

    with connection.cursor() as cur:
        finding_id = source_records.publish_finding(
            cur,
            1,
            type_ids,
            "source_record",
            target_id,
            reference,
            now,
            client_id=None,
            context={"platform": "Hudu", "entity_type": "cmdb.asset"},
        )
        assert finding_id is not None
        assert recorded_conditions == [finding_id]

        cur.execute(
            "SELECT status, finding_details->>'platform' FROM operations.findings"
        )
        assert cur.fetchone() == ("open", "Hudu")

        linked_record = {**record, "canonical_data": {"link_verdict": "linked"}}
        linked = next(
            item
            for item in source_records.evaluate_record(linked_record, {})
            if item["rule"] == "record.reference"
        )
        assert (
            source_records.publish_finding(
                cur,
                1,
                type_ids,
                "source_record",
                target_id,
                linked,
                now,
                client_id=None,
                context={"platform": "Hudu", "entity_type": "cmdb.asset"},
            )
            is None
        )
        cur.execute("SELECT status, closed_at FROM operations.findings")
        status, closed_at = cur.fetchone()
        assert status == "resolved" and closed_at == now
