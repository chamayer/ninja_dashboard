"""U04 candidate: a generation fence on software reclassification targets.

Design under test (not implemented in source):
  * the target table gains `generation bigint NOT NULL DEFAULT 1`;
  * every producer's `ON CONFLICT ... WHERE consumed_at IS NULL` clause becomes
    `DO UPDATE SET generation = target.generation + 1` (the matcher keeps its
    `queued_at` bump);
  * the consumer captures `(id, generation)` and acknowledges only rows whose
    generation is still the captured one.

The producer statements are the current ones, rewritten mechanically, so the
test fails loudly if the source statements change shape. The same four
interleavings as Phase 2 check 5/6 run, plus an in-flight producer
transaction that is uncommitted at capture and commits before the
acknowledgment, and one that is still uncommitted when the acknowledgment
runs.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import psycopg
import pytest

from ingest.inventory.software import CHANGED_TITLES_SQL

TITLE = "acme agent"
ROOT = Path(__file__).resolve().parents[4]

SCHEMA = """
CREATE TABLE operations.software_reclassification_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL CHECK (tenant_id = 1),
    target_key TEXT NOT NULL CHECK (length(target_key) BETWEEN 3 AND 300),
    software_version_id BIGINT,
    canonical_name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 80),
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at TIMESTAMPTZ,
    cursor_device_id UUID,
    generation BIGINT NOT NULL DEFAULT 1,
    CHECK (
        (software_version_id IS NOT NULL AND canonical_name = '')
        OR (software_version_id IS NULL AND canonical_name <> '')
    )
);
CREATE UNIQUE INDEX software_reclassification_targets_pending_unique
    ON operations.software_reclassification_targets (tenant_id, target_key, source)
    WHERE consumed_at IS NULL;
CREATE TABLE operations.title_evidence (canonical_name text PRIMARY KEY, version text);
CREATE TABLE operations.cve_match (
    tenant_id bigint, canonical_name text, software_version_id bigint,
    cve_id text, match_kind text, version_range text, confidence text
);
"""

FENCED_CAPTURE_SQL = """
SELECT id, generation FROM operations.software_reclassification_targets
 WHERE tenant_id = 1 AND consumed_at IS NULL
"""
FENCED_CONSUME_SQL = """
UPDATE operations.software_reclassification_targets target
   SET consumed_at = now()
  FROM unnest(%(ids)s::uuid[], %(generations)s::bigint[]) AS captured(id, generation)
 WHERE target.tenant_id = 1 AND target.id = captured.id
   AND target.generation = captured.generation AND target.consumed_at IS NULL
"""


def _fence_inventory(sql: str) -> str:
    clause = "ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL DO NOTHING"
    assert sql.count(clause) == 1, "inventory producer changed shape; re-inspect"
    sql = sql.replace(
        "INSERT INTO operations.software_reclassification_targets",
        "INSERT INTO operations.software_reclassification_targets AS target",
    )
    return sql.replace(
        clause,
        "ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL"
        " DO UPDATE SET generation = target.generation + 1",
    )


def _fenced_matcher_sql() -> str:
    source = (ROOT / "ingest/intel/matcher.py").read_text()
    match = re.search(
        r'"""\s*(INSERT INTO operations\.software_reclassification_targets'
        r".*?'cve_match'.*?DO UPDATE SET queued_at = now\(\))\s*\"\"\"",
        source,
        re.S,
    )
    assert match, "matcher target statement not found; re-inspect matcher.py"
    sql = match.group(1).replace(
        "INSERT INTO operations.software_reclassification_targets",
        "INSERT INTO operations.software_reclassification_targets AS target",
        1,
    )
    return sql.replace(
        "DO UPDATE SET queued_at = now()",
        "DO UPDATE SET queued_at = now(), generation = target.generation + 1",
    )


EVIDENCE_SQL = {
    "inventory": "SELECT version FROM operations.title_evidence",
    "cve_match": "SELECT count(*) FROM operations.cve_match",
}


@pytest.fixture
def conns(postgres_dsn):
    with psycopg.connect(postgres_dsn, autocommit=True) as setup:
        setup.execute("DROP SCHEMA IF EXISTS operations CASCADE")
        setup.execute("CREATE SCHEMA operations")
        setup.execute(SCHEMA)
        setup.execute("INSERT INTO operations.title_evidence VALUES (%s, '1.0')", (TITLE,))
    with psycopg.connect(postgres_dsn) as consumer, psycopg.connect(
        postgres_dsn
    ) as producer:
        yield consumer, producer


def _inventory_statements(conn):
    conn.execute("UPDATE operations.title_evidence SET version = version || '+'")
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS inventory_delta (kind text, canonical_name text)"
    )
    conn.execute("DELETE FROM inventory_delta")
    conn.execute("INSERT INTO inventory_delta VALUES ('changed', %s)", (TITLE,))
    conn.execute(_fence_inventory(CHANGED_TITLES_SQL), {"tenant_id": 1})


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
    conn.execute(_fenced_matcher_sql(), (1, 1, 1))


PRODUCE = {"inventory": _inventory_statements, "cve_match": _matcher_statements}


def _change(conn, producer_name):
    with conn.transaction():
        PRODUCE[producer_name](conn)


def _capture(conn):
    with conn.transaction():
        rows = conn.execute(FENCED_CAPTURE_SQL).fetchall()
    return [str(r[0]) for r in rows], [r[1] for r in rows]


def _read(conn, producer_name):
    with conn.transaction():
        return conn.execute(EVIDENCE_SQL[producer_name]).fetchone()[0]


def _consume(conn, captured):
    ids, generations = captured
    with conn.transaction():
        conn.execute(FENCED_CONSUME_SQL, {"ids": ids, "generations": generations})


def _pending(conn):
    with conn.transaction():
        return conn.execute(
            "SELECT source FROM operations.software_reclassification_targets"
            " WHERE consumed_at IS NULL"
        ).fetchall()


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_post_read_change_stays_pending(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    captured = _capture(consumer)
    seen = _read(consumer, producer_name)
    _change(producer, producer_name)          # the Phase 2 losing interleaving
    _consume(consumer, captured)
    assert seen != _read(consumer, producer_name)
    assert _pending(consumer) == [(producer_name,)]   # demand survives


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_controls_still_acknowledge(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    captured = _capture(consumer)
    _read(consumer, producer_name)
    _consume(consumer, captured)              # no interleaving: acknowledged
    assert _pending(consumer) == []
    _change(producer, producer_name)          # after the ack: new pending row
    assert _pending(consumer) == [(producer_name,)]


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_in_flight_producer_committing_before_ack_stays_pending(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    producer.execute("BEGIN")
    PRODUCE[producer_name](producer)          # bumps generation, uncommitted
    captured = _capture(consumer)             # sees the old generation
    _read(consumer, producer_name)            # does not see the new evidence
    producer.execute("COMMIT")
    _consume(consumer, captured)
    assert _pending(consumer) == [(producer_name,)]


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_in_flight_producer_at_ack_blocks_then_stays_pending(conns, producer_name):
    consumer, producer = conns
    _change(producer, producer_name)
    captured = _capture(consumer)
    _read(consumer, producer_name)
    producer.execute("BEGIN")
    PRODUCE[producer_name](producer)          # holds the target row lock
    done = threading.Event()

    def ack():
        _consume(consumer, captured)
        done.set()

    thread = threading.Thread(target=ack)
    thread.start()
    assert not done.wait(1.5), "acknowledgment should wait on the producer's row lock"
    producer.execute("COMMIT")
    thread.join(timeout=10)
    assert done.is_set()
    assert _pending(consumer) == [(producer_name,)]
