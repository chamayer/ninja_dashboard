"""Checks 5–6 — U04: a producer coalescing into a captured target before ack.

The findings job (ingest/operator_job_queue.py::_software_reconcile) captures
pending target IDs, releases that transaction, reconciles, then consumes the
captured IDs. Each step below commits on its own connection, which is exactly
the interleaving the code allows: no lock is held between capture and consume.
"""

from __future__ import annotations

import os
import re
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

from ingest.inventory.software import CHANGED_TITLES_SQL  # noqa: E402
from ingest.software_reconcile import (  # noqa: E402
    CONSUME_TARGETS_SQL,
    PENDING_TARGETS_SQL,
    scope_from_targets,
)

TITLE = "acme agent"

# Table shape and constraints from migrations 0250 and 0277. The tenants and
# catalog foreign keys and RLS policy are omitted; tenant_id = 1 is kept.
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
    CHECK (
        (software_version_id IS NOT NULL AND canonical_name = '')
        OR (software_version_id IS NULL AND canonical_name <> '')
    )
);
CREATE UNIQUE INDEX software_reclassification_targets_pending_unique
    ON operations.software_reclassification_targets (tenant_id, target_key, source)
    WHERE consumed_at IS NULL;
-- Stand-ins for the evidence the reconcile reads and the matcher compares.
CREATE TABLE operations.title_evidence (canonical_name text PRIMARY KEY, version text);
CREATE TABLE operations.cve_match (
    tenant_id bigint, canonical_name text, software_version_id bigint,
    cve_id text, match_kind text, version_range text, confidence text
);
"""


def _matcher_target_sql() -> str:
    """The matcher's target INSERT, read from current source."""
    source = (Path(__file__).parents[4] / "ingest/intel/matcher.py").read_text()
    match = re.search(
        r'"""\s*(INSERT INTO operations\.software_reclassification_targets'
        r".*?'cve_match'.*?DO UPDATE SET queued_at = now\(\))\s*\"\"\"",
        source,
        re.S,
    )
    assert match, "matcher target statement not found; re-inspect matcher.py"
    return match.group(1)


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


def _inventory_change(conn):
    """Inventory apply: a new version of TITLE, through CHANGED_TITLES_SQL."""
    with conn.transaction():
        conn.execute("UPDATE operations.title_evidence SET version = version || '+'")
        conn.execute(
            "CREATE TEMP TABLE inventory_delta (kind text, canonical_name text)"
            " ON COMMIT DROP"
        )
        conn.execute("INSERT INTO inventory_delta VALUES ('changed', %s)", (TITLE,))
        conn.execute(CHANGED_TITLES_SQL, {"tenant_id": 1})


def _matcher_change(conn, cve: str):
    """Intel matcher: TITLE gains a product-level CVE match."""
    with conn.transaction():
        conn.execute(
            "CREATE TEMP TABLE cve_match_before ON COMMIT DROP AS"
            " SELECT * FROM operations.cve_match WHERE tenant_id = 1"
        )
        conn.execute(
            "INSERT INTO operations.cve_match VALUES (1, %s, NULL, %s, 'product', '', 'high')",
            (TITLE, cve),
        )
        conn.execute(_matcher_target_sql(), (1, 1, 1))


def _capture(conn):
    with conn.transaction():
        targets = conn.execute(PENDING_TARGETS_SQL, {"tid": 1}).fetchall()
    return [str(row[0]) for row in targets], scope_from_targets(targets)


# What the reconcile reads for TITLE: its installation evidence, or its matches.
EVIDENCE_SQL = {
    "inventory": "SELECT version FROM operations.title_evidence",
    "cve_match": "SELECT count(*) FROM operations.cve_match WHERE canonical_name = '%s'" % TITLE,
}


def _reconcile_read(conn, producer_name="inventory"):
    with conn.transaction():
        return conn.execute(EVIDENCE_SQL[producer_name]).fetchone()[0]


def _consume(conn, ids):
    with conn.transaction():
        conn.execute(CONSUME_TARGETS_SQL, {"tid": 1, "ids": ids})


def _pending(conn):
    with conn.transaction():
        return conn.execute(
            "SELECT target_key, source FROM operations.software_reclassification_targets"
            " WHERE consumed_at IS NULL"
        ).fetchall()




@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_reproduces_post_read_change_is_acknowledged_away(conns, producer_name):
    consumer, producer = conns
    change = {
        "inventory": _inventory_change,
        "cve_match": lambda c: _matcher_change(c, "CVE-1"),
    }[producer_name]
    second = {
        "inventory": _inventory_change,
        "cve_match": lambda c: _matcher_change(c, "CVE-2"),
    }[producer_name]

    change(producer)                       # demand for TITLE exists
    ids, titles = _capture(consumer)       # barrier 1: consumer captures
    assert titles == [TITLE] and len(ids) == 1
    seen = _reconcile_read(consumer, producer_name)  # reconcile reads TITLE's evidence
    second(producer)                       # barrier 2: producer commits again
    assert _pending(consumer) == [(f"name:{TITLE}", producer_name)]
    _consume(consumer, ids)                # barrier 3: acknowledgment

    # The second change coalesced into the captured row and was consumed with
    # it: no pending demand remains for evidence the reconcile never read.
    assert _pending(consumer) == []
    assert seen != _reconcile_read(consumer, producer_name)


@pytest.mark.parametrize("producer_name", ["inventory", "cve_match"])
def test_control_change_before_read_or_after_ack_is_not_lost(conns, producer_name):
    consumer, producer = conns
    change = {
        "inventory": _inventory_change,
        "cve_match": lambda c: _matcher_change(c, "CVE-1"),
    }[producer_name]
    later = {
        "inventory": _inventory_change,
        "cve_match": lambda c: _matcher_change(c, "CVE-3"),
    }[producer_name]

    before_read = {
        "inventory": _inventory_change,
        "cve_match": lambda c: _matcher_change(c, "CVE-2"),
    }[producer_name]

    change(producer)
    ids, _ = _capture(consumer)
    before = _reconcile_read(consumer, producer_name)
    before_read(producer)                  # after capture, before the read
    seen = _reconcile_read(consumer, producer_name)
    assert seen != before                  # the read sees the new evidence
    _consume(consumer, ids)
    later(producer)                        # after the ack: a new pending row
    assert _pending(consumer) == [(f"name:{TITLE}", producer_name)]
