"""Postgres helpers: connection pool, transaction context, bulk upsert.

The pool is module-level so all ingest modules share connections.
`pool.connection()` commits on clean exit and rolls back on exception,
so per-domain ingest is atomic — partial-run failures don't pollute
prior state.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import sql
from psycopg_pool import ConnectionPool

from shared.findings_contract import (
    FINDING_CONTRACT,
    database_findings_contract,
    guard_findings_writes,
)

log = logging.getLogger(__name__)


class _NotInitialized:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("db.init(dsn) must be called before using the pool")


pool: Any = _NotInitialized()


def init(dsn: str, min_size: int = 1, max_size: int = 4) -> None:
    """Initialize the module-level connection pool. Idempotent: a second
    call is a no-op (avoids accidental double-init from reimports)."""
    global pool
    if not isinstance(pool, _NotInitialized):
        return
    # application_name names this process in change history (ADR-0033): a
    # change written without an explicit action is attributed to it.
    pool = ConnectionPool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        open=True,
        kwargs={"application_name": "ingest"},
    )
    log.info("Postgres pool initialized (min=%d, max=%d)", min_size, max_size)


@contextmanager
def transaction() -> Iterator[Any]:
    """Yield a cursor inside a transaction. Commit on clean exit,
    rollback on exception (handled by the pool's connection context)."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur


def wait_for_findings_contract(poll_seconds: float = 10.0) -> None:
    """Block until the database accepts this build's findings contract.

    Operations publishes the contract when it applies its migrations, which may
    finish after this process starts. Until then no producer, Job or notifier
    work is admitted; liveness stays up so the container is not restarted.
    """
    while True:
        with transaction() as cur:
            current = database_findings_contract(cur)
        if current == FINDING_CONTRACT:
            return
        log.warning(
            "Findings contract %s required, database has %s; waiting before admitting work",
            FINDING_CONTRACT,
            current,
        )
        time.sleep(poll_seconds)


@contextmanager
def findings_transaction(tenant_id: int) -> Iterator[Any]:
    """Like ``transaction`` for work that writes findings, assessments or
    participants: the exclusive tenant guard and findings contract are taken
    before anything else (PLAN-003 R2)."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            guard_findings_writes(cur, tenant_id)
            yield cur


def upsert(
    cur: Any,
    table: str,
    rows: list[dict[str, Any]],
    conflict_keys: list[str],
    update_cols: list[str] | None = None,
) -> int:
    """Bulk upsert. `table` may be schema-qualified ("ninja_core.devices").
    Columns are inferred from rows[0].keys(); all rows must share the
    same shape. `update_cols` controls which columns are written on
    conflict — defaults to all non-key columns. Pass an explicit subset
    for SCD-2 tables that must preserve some columns (e.g. first_observed_at).
    Returns row count affected."""
    if not rows:
        return 0
    columns = list(rows[0].keys())
    if update_cols is None:
        update_cols = [c for c in columns if c not in conflict_keys]
    table_ident = sql.SQL(".").join(sql.Identifier(p) for p in table.split("."))
    stmt = sql.SQL(
        "INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        "ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
    ).format(
        table=table_ident,
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        placeholders=sql.SQL(", ").join(sql.Placeholder(c) for c in columns),
        conflict=sql.SQL(", ").join(sql.Identifier(c) for c in conflict_keys),
        updates=sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c))
            for c in update_cols
        ),
    )
    cur.executemany(stmt, rows)
    return cur.rowcount


def insert_ignore(
    cur: Any,
    table: str,
    rows: list[dict[str, Any]],
    conflict_keys: list[str],
) -> int:
    """Bulk INSERT ... ON CONFLICT DO NOTHING. Returns row count
    inserted (excludes duplicates). Use for immutable-event tables
    like ninja_activities.activities where the source provides a
    stable PK and we never want to overwrite existing rows."""
    if not rows:
        return 0
    columns = list(rows[0].keys())
    table_ident = sql.SQL(".").join(sql.Identifier(p) for p in table.split("."))
    stmt = sql.SQL(
        "INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        "ON CONFLICT ({conflict}) DO NOTHING"
    ).format(
        table=table_ident,
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        placeholders=sql.SQL(", ").join(sql.Placeholder(c) for c in columns),
        conflict=sql.SQL(", ").join(sql.Identifier(c) for c in conflict_keys),
    )
    cur.executemany(stmt, rows)
    return cur.rowcount
