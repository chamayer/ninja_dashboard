"""Opt-in PostgreSQL coverage for the software target generation fence (U04).

Run with ``RUN_POSTGRES_INTEGRATION_TESTS=1``. The test uses a disposable
Postgres container; it never connects to a configured Operations environment.

PLAN-017 Phase 2 checks 5-6 reproduced the loss: a change coalesced into a
pending target after the findings run captured it was consumed by that run's
acknowledgment. Phase 4 proved a generation fence. These tests run the real
statements against the real 0250/0277/0349 migration SQL, as ``ninja_ingest``
under row-level security, on two independent connections.
"""

from __future__ import annotations

import importlib
import os
import re
import threading
from pathlib import Path

import psycopg
import pytest

for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

from ingest import software_reconcile  # noqa: E402
from ingest.inventory.software import CHANGED_TITLES_SQL  # noqa: E402

TITLE = "acme agent"
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = (
    "0250_software_reclassification_targets",
    "0277_software_reclassification_target_cursor",
    "0349_software_target_generation",
)


@pytest.fixture(scope="module")
def postgres_dsn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_INTEGRATION_TESTS=1 to start a disposable Postgres container"
        )
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )


@pytest.fixture
def conns(postgres_dsn):
    with psycopg.connect(postgres_dsn, autocommit=True) as setup:
        setup.execute("DROP SCHEMA IF EXISTS operations, catalog CASCADE")
        for role in ("operations_migrate", "operations_app", "operations_readonly",
                     "metabase_ro", "ninja_ingest"):
            setup.execute(
                f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        setup.execute("CREATE SCHEMA operations; CREATE SCHEMA catalog")
        setup.execute("CREATE TABLE operations.tenants (id bigint PRIMARY KEY)")
        setup.execute("INSERT INTO operations.tenants VALUES (1)")
        setup.execute("CREATE TABLE catalog.software_versions (id bigint PRIMARY KEY)")
        for name in MIGRATIONS:
            module = importlib.import_module(f"operations.apps.core.migrations.{name}")
            setup.execute(module.FORWARD_SQL)
        # Producer-side stand-ins: title evidence the run reads, and the
        # matcher's match table.
        setup.execute(
            "CREATE TABLE operations.title_evidence (canonical_name text PRIMARY KEY, version text)"
        )
        setup.execute(
            "CREATE TABLE operations.cve_match (tenant_id bigint, canonical_name text,"
            " software_version_id bigint, cve_id text, match_kind text,"
            " version_range text, confidence text)"
        )
        setup.execute("INSERT INTO operations.title_evidence VALUES (%s, '1.0')", (TITLE,))
        setup.execute("GRANT USAGE ON SCHEMA operations TO ninja_ingest")
        setup.execute(
            "GRANT SELECT, INSERT, UPDATE ON operations.title_evidence, operations.cve_match"
            " TO ninja_ingest"
        )
    with psycopg.connect(postgres_dsn) as consumer, psycopg.connect(postgres_dsn) as producer:
        for conn in (consumer, producer):
            conn.execute("SET ROLE ninja_ingest")
            conn.execute("SET operations.tenant_id = '1'")
            conn.commit()
        yield consumer, producer


def _matcher_sql() -> str:
    source = (ROOT / "ingest/intel/matcher.py").read_text(encoding="utf-8")
    match = re.search(
        r'"""\s*(INSERT INTO operations\.software_reclassification_targets'
        r".*?'cve_match'.*?DO UPDATE SET[^\n]*)\s*\"\"\"",
        source,
        re.S,
    )
    assert match, "matcher target statement not found; re-inspect matcher.py"
    return match.group(1)


def _inventory_statements(conn):
    conn.execute("UPDATE operations.title_evidence SET version = version || '+'")
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS inventory_delta (kind text, canonical_name text)"
    )
    conn.execute("DELETE FROM inventory_delta")
    conn.execute("INSERT INTO inventory_delta VALUES ('changed', %s)", (TITLE,))
    conn.execute(CHANGED_TITLES_SQL, {"tenant_id": 1})


_cves = iter(range(1, 1000))


def _matcher_statements(conn):
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS cve_match_before AS"
        " SELECT * FROM operations.cve_match WITH NO DATA"
    )
    conn.execute("DELETE FROM cve_match_before")
    conn.execute("INSERT INTO cve_match_before SELECT * FROM operations.cve_match")
    conn.execute(
        "INSERT INTO operations.cve_match VALUES (1, %s, NULL, %s, 'product', '', 'high')",
        (TITLE, f"CVE-{next(_cves)}"),
    )
    conn.execute(_matcher_sql(), (1, 1, 1))


def _whole_fleet_statements(conn):
    conn.execute(
        software_reconcile.RECORD_WHOLE_FLEET_SQL, {"tid": 1, "source": "whole_fleet"}
    )


PRODUCE = {
    "inventory": _inventory_statements,
    "cve_match": _matcher_statements,
    "whole_fleet": _whole_fleet_statements,
}
EVIDENCE_SQL = {
    "inventory": "SELECT version FROM operations.title_evidence",
    "cve_match": "SELECT count(*) FROM operations.cve_match",
}


def _change(conn, producer_name):
    with conn.transaction():
        PRODUCE[producer_name](conn)


def _capture(conn):
    with conn.transaction():
        rows = conn.execute(software_reconcile.PENDING_TARGETS_SQL, {"tid": 1}).fetchall()
    return [(str(row[0]), int(row[4])) for row in rows]


def _consume(conn, captured):
    with conn.transaction():
        conn.execute(
            software_reconcile.CONSUME_TARGETS_SQL,
            {
                "tid": 1,
                "ids": [target_id for target_id, _ in captured],
                "generations": [generation for _, generation in captured],
            },
        )


def _pending(conn):
    with conn.transaction():
        return conn.execute(
            "SELECT source FROM operations.software_reclassification_targets"
            " WHERE consumed_at IS NULL"
        ).fetchall()


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match", "whole_fleet"])
def test_change_after_capture_stays_pending(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    captured = _capture(consumer)
    _change(producer, producer_name)          # the Phase 2 losing interleaving
    _consume(consumer, captured)
    assert _pending(consumer) == [(producer_name,)]


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match", "whole_fleet"])
def test_uncontended_capture_is_acknowledged(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    _consume(consumer, _capture(consumer))
    assert _pending(consumer) == []
    _change(producer, producer_name)          # after the ack: a new pending row
    assert _pending(consumer) == [(producer_name,)]


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_in_flight_producer_committing_before_ack_stays_pending(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    with producer.transaction():
        PRODUCE[producer_name](producer)      # bumps generation, uncommitted
        captured = _capture(consumer)         # sees the old generation
        with consumer.transaction():
            consumer.execute(EVIDENCE_SQL[producer_name])
    _consume(consumer, captured)
    assert _pending(consumer) == [(producer_name,)]


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_in_flight_producer_at_ack_blocks_then_stays_pending(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    captured = _capture(consumer)
    done = threading.Event()

    def ack():
        _consume(consumer, captured)
        done.set()

    with producer.transaction():
        PRODUCE[producer_name](producer)      # holds the target row lock
        thread = threading.Thread(target=ack)
        thread.start()
        assert not done.wait(1.5), "acknowledgment should wait on the producer's row lock"
    thread.join(timeout=10)
    assert done.is_set()
    assert _pending(consumer) == [(producer_name,)]
