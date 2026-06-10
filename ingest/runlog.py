"""Run-log context manager.

Wraps each ingest module's work in a ninja_core.run_log row tracking
start/end timestamps, status, row counts, and error message.

Usage:
    from ingest.runlog import run_log

    with run_log("core.organizations") as stats:
        ...do work...
        stats["rows_upserted"] = N

On clean exit the row is updated to status='ok' with timings + counts.
On exception the row gets status='failed' with the exception text,
then the exception is re-raised so the caller still sees it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from ingest import db

_ERROR_TEXT_MAX = 5000


@contextmanager
def run_log(domain: str) -> Iterator[dict[str, int]]:
    started = datetime.now(timezone.utc)
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO ninja_core.run_log (domain, started_at, status) "
            "VALUES (%s, %s, 'running') RETURNING run_id",
            (domain, started),
        )
        run_id = cur.fetchone()[0]

    stats: dict[str, int] = {
        "run_id": run_id,
        "rows_upserted": 0,
        "rows_inserted": 0,
    }
    try:
        yield stats
    except Exception as exc:
        _finalize(run_id, started, "failed", stats, error=str(exc))
        raise
    _finalize(run_id, started, "ok", stats)


def _finalize(
    run_id: int,
    started: datetime,
    status: str,
    stats: dict[str, int],
    error: str | None = None,
) -> None:
    finished = datetime.now(timezone.utc)
    duration_ms = int((finished - started).total_seconds() * 1000)
    with db.transaction() as cur:
        cur.execute(
            "UPDATE ninja_core.run_log "
            "SET status=%s, finished_at=%s, duration_ms=%s, "
            "    rows_upserted=%s, rows_inserted=%s, error_text=%s "
            "WHERE run_id=%s",
            (
                status,
                finished,
                duration_ms,
                stats["rows_upserted"],
                stats["rows_inserted"],
                error[:_ERROR_TEXT_MAX] if error else None,
                run_id,
            ),
        )
