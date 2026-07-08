"""Software refresh queue — enqueue helpers and background drain worker.

Three queues (all in ninja_core):
  software_scheduled_queue  Q1  one entry per Ninja org, filled by
                                enqueue_all_orgs() on a schedule
  software_demand_queue     Q2  operator-triggered; fired immediately
                                on enqueue, status tracked per job
  software_activity_queue   Q3  device-level, filled by activity
                                processor on SOFTWARE_* events

Background worker drains Q3 first (higher priority), then Q1.
Q2 fires in its own thread and is never touched by the background worker.

Failure handling:
  - Lease expiry: processing entries older than _LEASE_MINUTES are reset
    to pending (Q1/Q3) or failed (Q2 — no worker to pick up re-pending).
  - Retry cap: on failure, attempts is incremented; reset to pending until
    max_attempts is reached, then left as failed permanently.
"""

from __future__ import annotations

import logging

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.inventory import software as _sw

log = logging.getLogger(__name__)

_LEASE_MINUTES = 30
_ERROR_MAX = 2000

SOFTWARE_ACTIVITY_TYPES: frozenset[str] = frozenset((
    "SOFTWARE_ADDED",
    "SOFTWARE_REMOVED",
    "SOFTWARE_UPDATED",
))

_BACKGROUND_QUEUES = (
    "ninja_core.software_activity_queue",   # drained first (higher priority)
    "ninja_core.software_scheduled_queue",
)
_DEMAND_TABLE = "ninja_core.software_demand_queue"


# ── Enqueue helpers ─────────────────────────────────────────────────


def enqueue_scheduled(ninja_org_id: int, reason: str = "") -> bool:
    """Insert org into Q1. Returns True if inserted, False if deduped."""
    return _enqueue("ninja_core.software_scheduled_queue", f"org={ninja_org_id}", reason)


def enqueue_activity(ninja_device_id: int, reason: str = "") -> bool:
    """Insert device into Q3. Returns True if inserted, False if deduped."""
    return _enqueue("ninja_core.software_activity_queue", f"id={ninja_device_id}", reason)


def enqueue_demand(df: str, reason: str = "") -> int:
    """Insert into Q2. Returns the entry id (existing if already pending)."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ninja_core.software_demand_queue (df, reason) "
            "VALUES (%s, %s) "
            "ON CONFLICT (df) WHERE status = 'pending' DO NOTHING "
            "RETURNING id",
            (df, reason),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        # Already pending with same df — return existing id.
        cur.execute(
            "SELECT id FROM ninja_core.software_demand_queue "
            "WHERE df = %s AND status = 'pending'",
            (df,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def get_demand_status(entry_id: int) -> dict | None:
    """Return the demand queue row as a dict, or None if not found."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, df, reason, status, attempts, max_attempts,
                   queued_at, started_at, completed_at, rows_seen, error
            FROM ninja_core.software_demand_queue
            WHERE id = %s
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


def queue_details() -> dict[str, dict]:
    """Return counts + active + recent rows for all three queues."""
    tables = {
        "scheduled": "ninja_core.software_scheduled_queue",
        "demand":    "ninja_core.software_demand_queue",
        "activity":  "ninja_core.software_activity_queue",
    }
    result: dict[str, dict] = {}
    with db.pool.connection() as conn, conn.cursor() as cur:
        for name, table in tables.items():
            cur.execute(f"SELECT status, COUNT(*) FROM {table} GROUP BY status")
            counts = {row[0]: int(row[1]) for row in cur.fetchall()}

            cur.execute(
                f"""
                SELECT id, df, status, attempts, started_at, completed_at, rows_seen, error
                FROM {table}
                WHERE status = 'processing'
                ORDER BY started_at
                LIMIT 20
                """
            )
            cols = ["id", "df", "status", "attempts", "started_at", "completed_at", "rows_seen", "error"]
            active = [dict(zip(cols, row)) for row in cur.fetchall()]

            cur.execute(
                f"""
                SELECT id, df, status, attempts, started_at, completed_at, rows_seen, error
                FROM {table}
                WHERE status IN ('done', 'failed')
                ORDER BY completed_at DESC
                LIMIT 20
                """
            )
            recent = [dict(zip(cols, row)) for row in cur.fetchall()]

            result[name] = {"counts": counts, "active": active, "recent": recent}
    return result


def queue_counts() -> dict[str, dict[str, int]]:
    """Return {queue_name: {status: count}} for all three queues."""
    tables = {
        "scheduled": "ninja_core.software_scheduled_queue",
        "demand":    "ninja_core.software_demand_queue",
        "activity":  "ninja_core.software_activity_queue",
    }
    result: dict[str, dict[str, int]] = {}
    with db.pool.connection() as conn, conn.cursor() as cur:
        for name, table in tables.items():
            cur.execute(
                f"SELECT status, COUNT(*) FROM {table} GROUP BY status",
            )
            result[name] = {row[0]: int(row[1]) for row in cur.fetchall()}
    return result


# ── Background worker (Q1 + Q3) ────────────────────────────────────


def recover_stale_entries() -> int:
    """Reset stale processing entries back to pending (Q1/Q3) or failed (Q2).
    Called at the start of each background worker tick."""
    total = 0
    for table in _BACKGROUND_QUEUES:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {table}
                SET status = 'pending', started_at = NULL, worker_id = NULL
                WHERE status = 'processing'
                  AND started_at < NOW() - INTERVAL '{_LEASE_MINUTES} minutes'
                """,
            )
            n = cur.rowcount
            if n:
                log.warning("Recovered %d stale entries in %s", n, table)
            total += n

    # Demand entries with no live thread → mark failed so operator sees it.
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {_DEMAND_TABLE}
            SET status = 'failed',
                completed_at = NOW(),
                error = CASE
                    WHEN error IS NOT NULL AND error <> ''
                    THEN error || ' | lease expired — resubmit'
                    ELSE 'lease expired — resubmit'
                END
            WHERE status = 'processing'
              AND started_at < NOW() - INTERVAL '{_LEASE_MINUTES} minutes'
            """,
        )
        n = cur.rowcount
        if n:
            log.warning("Expired %d stale demand entries (no live thread)", n)
        total += n

    return total


def drain_background(client: NinjaClient, batch_size: int) -> tuple[int, int]:
    """Drain Q3 (activity) then Q1 (scheduled) up to batch_size total.
    Returns (activity_drained, scheduled_drained)."""
    recover_stale_entries()

    activity_drained = _drain_queue(
        client, "ninja_core.software_activity_queue", batch_size
    )
    remaining = batch_size - activity_drained
    scheduled_drained = 0
    if remaining > 0:
        scheduled_drained = _drain_queue(
            client, "ninja_core.software_scheduled_queue", remaining
        )
    return activity_drained, scheduled_drained


# ── On-demand worker (Q2) ──────────────────────────────────────────


def process_demand_entry(entry_id: int, client: NinjaClient) -> None:
    """Claim and process a Q2 demand entry. Called from a dedicated thread."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ninja_core.software_demand_queue
            SET status = 'processing', started_at = NOW()
            WHERE id = %s AND status = 'pending'
            RETURNING df, attempts, max_attempts
            """,
            (entry_id,),
        )
        row = cur.fetchone()
    if not row:
        log.warning("Demand entry %d already claimed or not found", entry_id)
        return
    df, attempts, max_attempts = row
    _process_entry(
        client,
        _DEMAND_TABLE,
        {"id": entry_id, "df": df, "attempts": attempts, "max_attempts": max_attempts},
    )


# ── Internal helpers ───────────────────────────────────────────────


def _enqueue(table: str, df: str, reason: str) -> bool:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} (df, reason) "
            "VALUES (%s, %s) "
            "ON CONFLICT (df) WHERE status = 'pending' DO NOTHING "
            "RETURNING id",
            (df, reason),
        )
        return cur.fetchone() is not None


def _drain_queue(client: NinjaClient, table: str, limit: int) -> int:
    drained = 0
    for _ in range(limit):
        entry = _claim_one(table)
        if entry is None:
            break
        _process_entry(client, table, entry)
        drained += 1
    return drained


def _claim_one(table: str) -> dict | None:
    """Atomically claim the oldest pending entry. Returns dict or None."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {table}
            SET status = 'processing', started_at = NOW()
            WHERE id = (
                SELECT id FROM {table}
                WHERE status = 'pending'
                ORDER BY queued_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, df, attempts, max_attempts
            """,
        )
        row = cur.fetchone()
    if not row:
        return None
    return dict(zip(["id", "df", "attempts", "max_attempts"], row))


def _process_entry(client: NinjaClient, table: str, entry: dict) -> None:
    entry_id = entry["id"]
    df = entry["df"]
    attempts = entry["attempts"]
    max_attempts = entry["max_attempts"]
    try:
        rows = _sw.run(client, df=df)
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {table} "
                "SET status = 'done', completed_at = NOW(), rows_seen = %s "
                "WHERE id = %s",
                (rows, entry_id),
            )
        log.info("Queue %s entry %d done: df=%r rows=%d", table, entry_id, df, rows or 0)
    except Exception as exc:
        new_attempts = attempts + 1
        err = str(exc)[:_ERROR_MAX]
        if new_attempts < max_attempts:
            with db.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} "
                    "SET status = 'pending', attempts = %s, error = %s, started_at = NULL "
                    "WHERE id = %s",
                    (new_attempts, err, entry_id),
                )
            log.warning(
                "Queue %s entry %d failed (attempt %d/%d), will retry: %s",
                table, entry_id, new_attempts, max_attempts, exc,
            )
        else:
            with db.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} "
                    "SET status = 'failed', attempts = %s, error = %s, completed_at = NOW() "
                    "WHERE id = %s",
                    (new_attempts, err, entry_id),
                )
            log.error(
                "Queue %s entry %d permanently failed after %d attempts: %s",
                table, entry_id, new_attempts, exc,
            )
