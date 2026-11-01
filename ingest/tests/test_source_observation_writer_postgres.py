"""Bounded PostgreSQL check of the shared observation writer's partial intake."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest

from ingest import source_observations


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


def test_writer_marks_partial_snapshot_failed_and_skips_reconciliation(
    postgres_connection, monkeypatch
):
    connection = postgres_connection
    source_instance_id = uuid.uuid4()
    binding_id = uuid.uuid4()
    with connection.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA operations;
            CREATE TABLE operations.source_bindings (
                id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
                source_instance_id uuid NOT NULL
            );
            CREATE TABLE operations.observation_snapshot_runs (
                run_id uuid PRIMARY KEY, tenant_id bigint NOT NULL,
                source_binding_id uuid NOT NULL, source_instance_id uuid NOT NULL,
                snapshot_scope text NOT NULL, snapshot_at timestamptz NOT NULL,
                run_started_at timestamptz NOT NULL,
                is_complete_snapshot boolean, status text NOT NULL,
                expected_rows integer NOT NULL, written_rows integer NOT NULL,
                failed_rows integer NOT NULL, error text NOT NULL,
                observed_identity_count integer NOT NULL,
                completed_at timestamptz, observed_identity_digest bytea
            );
            CREATE TABLE operations.source_record_subjects (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id bigint NOT NULL, subject_kind text NOT NULL,
                source_instance_id uuid NOT NULL, source_run_id uuid NOT NULL,
                item_ordinal integer NOT NULL, intake_error text NOT NULL,
                platform varchar(80) NOT NULL, entity_type varchar(80) NOT NULL
            );
            CREATE UNIQUE INDEX uq_test_intake_error_run_ordinal
                ON operations.source_record_subjects (tenant_id, source_run_id, item_ordinal)
                WHERE subject_kind = 'intake_error';
            CREATE VIEW operations.v_client_source_link AS
                SELECT NULL::integer AS source_id, NULL::text AS external_id,
                       NULL::uuid AS client_id WHERE FALSE;
            CREATE TABLE operations.placeholder_org_names (
                tenant_id bigint, normalized_name text
            );
            """,
        )
        cur.execute(
            """INSERT INTO operations.source_bindings
                   (id, tenant_id, source_instance_id) VALUES (%s, 1, %s)""",
            (binding_id, source_instance_id),
        )
    connection.commit()

    @contextmanager
    def transaction():
        with connection.transaction(), connection.cursor() as cur:
            yield cur

    monkeypatch.setattr(source_observations.db, "transaction", transaction)
    monkeypatch.setattr(
        source_observations, "load_identity_match_policies", lambda *_: {}
    )
    monkeypatch.setattr(
        source_observations, "identity_entity_types", lambda *_: {"agent.test"}
    )
    monkeypatch.setattr(
        source_observations, "record_name_short", lambda *_args: "host-a"
    )
    monkeypatch.setattr(
        source_observations, "resolve_device_fast", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(source_observations, "attachments", lambda *_args: [])
    monkeypatch.setattr(
        source_observations, "name_changed_attachments", lambda *_args: None
    )
    written_rows = []
    monkeypatch.setattr(
        source_observations,
        "write_current_rows",
        lambda _cur, rows: written_rows.extend(rows) or len(rows),
    )
    reconciled = []
    monkeypatch.setattr(
        source_observations,
        "reconcile_complete_run",
        lambda *_args: reconciled.append(True),
    )
    source = SimpleNamespace(
        source_key="writer-check",
        source_name="Writer check",
        source_binding_id=binding_id,
        source_instance_id=source_instance_id,
        platform="Test",
        entity_type="agent.test",
        is_shared=True,
        client_id=None,
        ops_source_id=None,
        is_partial_snapshot=False,
    )

    with pytest.raises(source_observations.PartialIntakeError) as exc:
        source_observations.write_observations(
            source,
            [
                {
                    "entity_key": "valid-agent",
                    "external_namespace": "test-agent",
                    "entity_type": "agent.test",
                    "hostname": "host-a",
                },
                {
                    "external_namespace": "test-agent",
                    "entity_type": "agent.test",
                },
            ],
            uuid.uuid4(),
            datetime.now(timezone.utc),
        )

    assert (exc.value.written_rows, exc.value.rejected_rows) == (1, 1)
    assert len(written_rows) == 1
    assert reconciled == []
    with connection.cursor() as cur:
        cur.execute(
            """SELECT status, is_complete_snapshot, expected_rows,
                      written_rows, failed_rows
                 FROM operations.observation_snapshot_runs"""
        )
        assert cur.fetchone() == ("failed", False, 2, 1, 1)
        cur.execute(
            """SELECT item_ordinal, intake_error
                 FROM operations.source_record_subjects
                WHERE subject_kind = 'intake_error'"""
        )
        assert cur.fetchall() == [(1, "missing stable source-record identity")]
