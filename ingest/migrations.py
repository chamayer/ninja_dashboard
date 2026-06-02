"""Schema migration runner.

Discovers sql/migrations/*.sql in filename order, checks which versions
have been applied (read from ninja_core.schema_migrations), and applies
pending in a transaction per file.

Bootstrap quirk: the schema_migrations table itself is created by
001_init_core.sql. On a fresh DB the read fails with UndefinedTable,
which we treat as "no migrations applied" — 001 then creates the table
and the version is recorded.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

from ingest import db  # import module, not name — db.pool is rebound at runtime

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "sql" / "migrations"


def apply_pending() -> list[str]:
    """Apply all pending migrations in filename order. Returns the list
    of versions applied this run (empty if nothing pending)."""
    applied = _applied_versions()
    new: list[str] = []
    for path in _discover():
        version = path.stem
        if version in applied:
            continue
        log.info("Applying migration %s", version)
        _apply_one(path, version)
        new.append(version)
    if new:
        log.info("Applied %d migration(s): %s", len(new), ", ".join(new))
    else:
        log.info("No pending migrations.")
    return new


def _discover() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _applied_versions() -> set[str]:
    with db.pool.connection() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT version FROM ninja_core.schema_migrations")
            return {row[0] for row in cur.fetchall()}
        except psycopg.errors.UndefinedTable:
            # Fresh DB — 001 will create the table.
            conn.rollback()
            return set()


def _apply_one(path: Path, version: str) -> None:
    body = path.read_text(encoding="utf-8")
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(body)
        cur.execute(
            "INSERT INTO ninja_core.schema_migrations (version) VALUES (%s) "
            "ON CONFLICT (version) DO NOTHING",
            (version,),
        )
