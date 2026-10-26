"""Check 10 — expiry of closed history with retained anchors and references.

Runs the real `operations.purge_closed_observation_history` (migration 0074)
over records written by the real observation primitives.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from conftest import OBSERVATION_SCHEMA, migration_function_sql, observation_row
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.observations import write_current_rows, write_daily_presence_rows

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
SCOPE = "Test"

# Daily presence per migration 0097 (RESTRICT, deferrable references to the
# current record and its first run); software history reduced to its purge key.
EXTRA_SCHEMA = """
ALTER TABLE operations.entity_observation_current
    ADD CONSTRAINT uq_current_ns UNIQUE (tenant_id, observation_id, external_namespace);
ALTER TABLE operations.observation_snapshot_runs
    ADD CONSTRAINT uq_runs_tenant UNIQUE (tenant_id, run_id);
CREATE TABLE operations.source_record_seen_daily (
    tenant_id bigint NOT NULL, source_record_id uuid NOT NULL,
    external_namespace varchar(120) NOT NULL, rollup_day date NOT NULL,
    first_snapshot_run_id uuid, backfilled_from_legacy boolean NOT NULL DEFAULT FALSE,
    PRIMARY KEY (tenant_id, source_record_id, rollup_day),
    CONSTRAINT ck_seen_daily_provenance CHECK (
        (backfilled_from_legacy IS FALSE AND first_snapshot_run_id IS NOT NULL)
        OR (backfilled_from_legacy IS TRUE AND first_snapshot_run_id IS NULL)),
    CONSTRAINT fk_seen_daily_source_record
        FOREIGN KEY (tenant_id, source_record_id, external_namespace)
        REFERENCES operations.entity_observation_current
            (tenant_id, observation_id, external_namespace)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_seen_daily_snapshot_run
        FOREIGN KEY (tenant_id, first_snapshot_run_id)
        REFERENCES operations.observation_snapshot_runs (tenant_id, run_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE operations.software_installation_history (
    id uuid PRIMARY KEY, effective_to timestamptz
);
"""


@pytest.fixture
def conn(postgres_dsn):
    with psycopg.connect(postgres_dsn, autocommit=True) as setup:
        setup.execute("DROP SCHEMA IF EXISTS operations CASCADE")
        setup.execute("CREATE SCHEMA operations")
        setup.execute(OBSERVATION_SCHEMA)
        setup.execute(EXTRA_SCHEMA)
        setup.execute(
            migration_function_sql(
                "0074_retire_legacy_observations_and_history_maintenance.py",
                "purge_closed_observation_history",
            )
        )
    with psycopg.connect(postgres_dsn) as connection:
        yield connection


def _snapshot(cur, binding, instance, at, present: list[str]):
    run_id, _ = begin_run(cur, 1, binding, SCOPE, at, expected_rows=len(present))
    rows = [observation_row(binding, instance, run_id, at, external_id=x) for x in present]
    write_current_rows(cur, rows)
    complete_run(cur, run_id, len(rows), is_complete_snapshot=True, identity_rows=rows)
    reconcile_complete_run(cur, run_id)
    cur.execute(
        "SELECT * FROM operations.entity_observation_current WHERE last_snapshot_run_id = %s",
        (run_id,),
    )
    columns = [c.name for c in cur.description]
    current = [dict(zip(columns, r)) for r in cur.fetchall() if r[columns.index("active")]]
    write_daily_presence_rows(cur, current, snapshot_run_id=run_id, observed_at=at)


def test_purge_keeps_open_versions_anchors_and_presence(conn):
    binding, instance = uuid.uuid4(), uuid.uuid4()
    t1, t2 = T0 + timedelta(days=10), T0 + timedelta(days=100)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "INSERT INTO operations.source_bindings VALUES (%s, 1, %s)", (binding, instance)
        )
        _snapshot(cur, binding, instance, T0, ["stays", "withdrawn", "returns"])
        _snapshot(cur, binding, instance, t1, ["stays"])               # two absent
        _snapshot(cur, binding, instance, t2, ["stays", "returns"])    # one reappears
        cur.execute(
            "INSERT INTO operations.software_installation_history VALUES"
            " (gen_random_uuid(), %s), (gen_random_uuid(), NULL)", (t1,)
        )

    cutoff = t1 + timedelta(days=1)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT * FROM operations.purge_closed_observation_history(%s)", (cutoff,))
        assert cur.fetchone() == (2, 1)  # two closed generic intervals, one software row

    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.external_id, c.active, c.withdrawn_at IS NOT NULL,"
            "  (SELECT COUNT(*) FROM operations.entity_observation_history h"
            "    WHERE h.external_id = c.external_id),"
            "  (SELECT MIN(h.effective_from) FROM operations.entity_observation_history h"
            "    WHERE h.external_id = c.external_id),"
            "  (SELECT MIN(d.rollup_day) FROM operations.source_record_seen_daily d"
            "    WHERE d.source_record_id = c.observation_id)"
            " FROM operations.entity_observation_current c ORDER BY 1"
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) FROM operations.software_installation_history"
            " WHERE effective_to IS NULL"
        )
        assert cur.fetchone() == (1,)

    assert rows == [
        # The returning record's first episode is gone: history starts at t2,
        # while daily presence still records T0 against the same current row.
        ("returns", True, False, 1, t2, T0.date()),
        # Open version untouched across the cutoff.
        ("stays", True, False, 1, T0, T0.date()),
        # Withdrawn record: closed history purged; current row keeps the anchor.
        ("withdrawn", False, True, 0, None, T0.date()),
    ]


def test_current_record_with_presence_cannot_be_deleted(conn):
    binding, instance = uuid.uuid4(), uuid.uuid4()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "INSERT INTO operations.source_bindings VALUES (%s, 1, %s)", (binding, instance)
        )
        _snapshot(cur, binding, instance, T0, ["a"])
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute("DELETE FROM operations.entity_observation_current")
