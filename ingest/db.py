"""Postgres helpers: connection pool, transaction context, bulk upsert.

The pool is module-level so all ingest modules share connections.
`pool.connection()` commits on clean exit and rolls back on exception,
so per-domain ingest is atomic — partial-run failures don't pollute
prior state.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import sql
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)


class _NotInitialised:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("db.init(dsn) must be called before using the pool")


pool: Any = _NotInitialised()


def init(dsn: str, min_size: int = 1, max_size: int = 4) -> None:
    """Initialise the module-level connection pool. Idempotent: a second
    call is a no-op (avoids accidental double-init from reimports)."""
    global pool
    if not isinstance(pool, _NotInitialised):
        return
    pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, open=True)
    log.info("Postgres pool initialised (min=%d, max=%d)", min_size, max_size)


@contextmanager
def transaction() -> Iterator[Any]:
    """Yield a cursor inside a transaction. Commit on clean exit,
    rollback on exception (handled by the pool's connection context)."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur


def upsert(
    cur: Any,
    table: str,
    rows: list[dict[str, Any]],
    conflict_keys: list[str],
) -> int:
    """Bulk upsert. `table` may be schema-qualified ("ninja_core.devices").
    Columns are inferred from rows[0].keys(); all rows must share the
    same shape. Conflict-key columns are excluded from the UPDATE SET.
    Returns row count affected."""
    if not rows:
        return 0
    columns = list(rows[0].keys())
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
