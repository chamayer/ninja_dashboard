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

Neither path survives the process being killed (SIGKILL, OOM, container
stop), which leaves the row stuck at 'running' forever — 96 such rows had
accumulated since 2026-06-03 before this was addressed. `reap_orphaned()`
runs at startup (nothing can still be running across a restart) and
`reap_stale()` runs periodically to catch hangs where the process lives
but the work does not.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from ingest import db

log = logging.getLogger(__name__)

_ERROR_TEXT_MAX = 5000

# A run still 'running' past this is treated as hung. Set well above the
# slowest observed healthy run (inventory.software.scoped is the longest).
STALE_RUN_MINUTES = 180

REASON_TERMINATED = "process terminated (service restart) — no completion recorded"
REASON_STALE = f"exceeded {STALE_RUN_MINUTES}m without completing — presumed hung"


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


def _reap(where_sql: str, params: tuple, reason: str, label: str) -> int:
    """Close orphaned 'running' rows. Returns how many were closed."""
    with db.transaction() as cur:
        cur.execute(
            f"""
            UPDATE ninja_core.run_log
               SET status      = 'failed',
                   finished_at = now(),
                   duration_ms = GREATEST(
                       0, (EXTRACT(EPOCH FROM (now() - started_at)) * 1000)::bigint
                   ),
                   error_text  = %s
             WHERE status = 'running' AND {where_sql}
            """,
            (reason, *params),
        )
        closed = cur.rowcount
    if closed:
        log.warning("run_log: closed %d orphaned run(s) — %s", closed, label)
    return closed


def reap_orphaned() -> int:
    """Close every 'running' row. Only safe at startup, where nothing from a
    previous process can still be running."""
    return _reap("TRUE", (), REASON_TERMINATED, "service restart")


def reap_stale(minutes: int = STALE_RUN_MINUTES) -> int:
    """Close 'running' rows older than `minutes` — hung, not merely slow."""
    return _reap(
        "started_at < now() - make_interval(mins => %s)",
        (minutes,),
        REASON_STALE,
        f"older than {minutes}m",
    )


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
