"""Source run demand queue.

Operator-triggered runs for Ninja, SentinelOne, ScreenConnect, LogMeIn.
One pending entry per source (df) enforced by partial unique index.

df values:
  'Ninja'        — full patching/device ingest run
  'SentinelOne'  — S1 observations → entity_observations
  'ScreenConnect' — SC observations → entity_observations
  'LogMeIn'      — LMI observations → entity_observations

Demand entries fire in their own thread immediately on enqueue.
Stale processing entries (lease expired, thread died) are marked failed —
there is no background worker to re-pick them up; operator must resubmit.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from ingest import db

log = logging.getLogger(__name__)

_TABLE = "operations.source_run_queue"
_LEASE_MINUTES = 30

SOURCES = ("Ninja", "SentinelOne", "ScreenConnect", "LogMeIn")


# ── Enqueue ─────────────────────────────────────────────────────────


def enqueue(source: str, reason: str = "") -> int:
    """Insert a pending entry for source. Returns entry id.

    Deduped: if a pending entry already exists for this source, returns
    the existing id without inserting.
    """
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {_TABLE} (df, reason) VALUES (%s, %s) "
            "ON CONFLICT (df) WHERE status = 'pending' DO NOTHING RETURNING id",
            (source, reason),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute(
            f"SELECT id FROM {_TABLE} WHERE df = %s AND status = 'pending'",
            (source,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


# ── Status queries ───────────────────────────────────────────────────


def get_status(entry_id: int) -> dict | None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, df, reason, status, attempts, max_attempts,
                   queued_at, started_at, completed_at, rows_seen, error
            FROM {_TABLE} WHERE id = %s
            """,
            (entry_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    cols = [
        "id", "df", "reason", "status", "attempts", "max_attempts",
        "queued_at", "started_at", "completed_at", "rows_seen", "error",
    ]
    return dict(zip(cols, row))


def queue_details() -> dict:
    """Return counts + active + recent rows."""
    _cols = [
        "id", "df", "status", "attempts", "max_attempts",
        "started_at", "completed_at", "rows_seen", "error",
    ]
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT status, COUNT(*) FROM {_TABLE} GROUP BY status")
        counts = {row[0]: int(row[1]) for row in cur.fetchall()}

        cur.execute(
            f"""
            SELECT {', '.join(_cols)} FROM {_TABLE}
            WHERE status = 'processing' ORDER BY started_at LIMIT 20
            """
        )
        active = [dict(zip(_cols, row)) for row in cur.fetchall()]

        cur.execute(
            f"""
            SELECT {', '.join(_cols)} FROM {_TABLE}
            WHERE status IN ('done', 'failed')
            ORDER BY completed_at DESC LIMIT 40
            """
        )
        recent = [dict(zip(_cols, row)) for row in cur.fetchall()]

    return {"counts": counts, "active": active, "recent": recent}


# ── Stale recovery ───────────────────────────────────────────────────


def recover_stale() -> int:
    """Mark stale processing entries as failed. Called on each drain tick."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {_TABLE}
            SET status = 'failed', completed_at = NOW(),
                error = COALESCE(NULLIF(error, '') || ' | ', '') || 'lease expired — resubmit'
            WHERE status = 'processing'
              AND started_at < NOW() - INTERVAL '{_LEASE_MINUTES} minutes'
            """
        )
        n = cur.rowcount
    if n:
        log.warning("source_run_queue: expired %d stale entries", n)
    return n


# ── Demand worker ────────────────────────────────────────────────────


def process_entry(entry_id: int) -> None:
    """Claim and execute one demand entry. Run in a dedicated thread."""
    # Late imports to avoid circular deps at module load time.
    from ingest.source_observations import run_source_observations
    from ingest.agent_compliance.config_loader import load_sources
    from ingest.identity.resolver import drain_resolution

    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {_TABLE}
            SET status = 'processing', started_at = NOW(), attempts = attempts + 1
            WHERE id = %s AND status = 'pending'
            RETURNING df, attempts, max_attempts
            """,
            (entry_id,),
        )
        row = cur.fetchone()

    if not row:
        log.warning("source_run_queue: entry %d not claimable (already running?)", entry_id)
        return

    df, attempts, max_attempts = row
    log.info("source_run_queue: processing entry=%d source=%s attempt=%d", entry_id, df, attempts)

    rows_seen = 0
    error: str | None = None
    try:
        if df == "Ninja":
            from ingest.main import run_patching_once
            run_patching_once()
        elif df in ("SentinelOne", "ScreenConnect", "LogMeIn"):
            sources = [s for s in load_sources() if s.platform == df]
            observed_at = datetime.now(timezone.utc)
            counts = run_source_observations(sources, observed_at)
            rows_seen = sum(counts.values())
            if rows_seen:
                drain_resolution(batch_size=500)
        else:
            raise ValueError(f"Unknown source: {df!r}")
    except Exception as exc:
        error = str(exc)[:2000]
        log.exception("source_run_queue: entry %d failed: %s", entry_id, df)

    status = "failed" if error else "done"
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {_TABLE}
            SET status = %s, completed_at = NOW(), rows_seen = %s, error = %s
            WHERE id = %s
            """,
            (status, rows_seen or None, error, entry_id),
        )
    log.info(
        "source_run_queue: entry=%d source=%s status=%s rows=%s",
        entry_id, df, status, rows_seen,
    )


def enqueue_and_run(source: str, reason: str = "") -> int:
    """Enqueue source and fire its entry in a daemon thread. Returns entry id."""
    entry_id = enqueue(source, reason)
    if entry_id:
        threading.Thread(target=process_entry, args=(entry_id,), daemon=True).start()
    return entry_id
