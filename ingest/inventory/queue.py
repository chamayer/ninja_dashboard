"""Software refresh queue — enqueue helpers and background drain worker.

Three queues (all in ninja_core):
  software_scheduled_queue  Q1  one entry per Ninja org, filled by
                                enqueue_all_orgs() on a schedule
  software_demand_queue     Q2  operator-triggered; drained before
                                background demand
  software_activity_queue   Q3  device-level, filled by activity
                                processor on SOFTWARE_* events

The governed worker drains Q2 first, then Q3, then Q1.

Failure handling:
  - Lease expiry: processing entries older than _LEASE_MINUTES are reset
    to pending (Q1/Q3) or failed (Q2 — no worker to pick up re-pending).
  - Retry cap: on failure, attempts is incremented; reset to pending until
    max_attempts is reached, then left as failed permanently.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

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

_DOMAIN_KINDS = {
    "ninja_core.software_scheduled_queue": "software.scheduled",
    "ninja_core.software_demand_queue": "software.demand",
    "ninja_core.software_activity_queue": "software.activity",
}


@contextmanager
def _tenant_cursor() -> Iterator[object]:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        yield cur


# ── Enqueue helpers ─────────────────────────────────────────────────


def enqueue_scheduled(ninja_org_id: int, reason: str = "") -> bool:
    """Insert org into Q1. Returns True if inserted, False if deduped."""
    return _enqueue("ninja_core.software_scheduled_queue", f"org={ninja_org_id}", reason)


def enqueue_activity(ninja_device_id: int, reason: str = "") -> bool:
    """Insert device into Q3. Returns True if inserted, False if deduped."""
    return _enqueue("ninja_core.software_activity_queue", f"id={ninja_device_id}", reason)


def enqueue_demand(df: str, reason: str = "") -> int:
    """Insert into Q2. Returns the entry id (existing if already pending)."""
    with _tenant_cursor() as cur:
        cur.execute(
            "INSERT INTO ninja_core.software_demand_queue (tenant_id, df, reason) "
            "VALUES (1, %s, %s) "
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
    with _tenant_cursor() as cur:
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
    with _tenant_cursor() as cur:
        for name, table in tables.items():
            cur.execute(f"SELECT status, COUNT(*) FROM {table} GROUP BY status")
            counts = {row[0]: int(row[1]) for row in cur.fetchall()}

            cur.execute(
                f"""
                SELECT id, df, status, attempts, max_attempts, started_at, completed_at, rows_seen, error
                FROM {table}
                WHERE status = 'processing'
                ORDER BY started_at
                LIMIT 20
                """
            )
            cols = ["id", "df", "status", "attempts", "max_attempts", "started_at", "completed_at", "rows_seen", "error"]
            active = [dict(zip(cols, row)) for row in cur.fetchall()]

            cur.execute(
                f"""
                SELECT id, df, status, attempts, max_attempts, started_at, completed_at, rows_seen, error
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
    with _tenant_cursor() as cur:
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
        with _tenant_cursor() as cur:
            cur.execute(
                f"""
                UPDATE {table}
                SET status = 'pending', started_at = NULL, worker_id = NULL
                WHERE status = 'processing'
                  AND started_at < NOW() - INTERVAL '{_LEASE_MINUTES} minutes'
                  AND NOT EXISTS (
                      SELECT 1 FROM {table} pending
                      WHERE pending.df = {table}.df
                        AND pending.status = 'pending'
                  )
                """,
            )
            n = cur.rowcount
            if n:
                log.warning("Recovered %d stale entries in %s", n, table)
            total += n

    # Demand entries with no live thread → mark failed so operator sees it.
    with _tenant_cursor() as cur:
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


def drain_background(
    client: NinjaClient, batch_size: int, job_run_id: object
) -> dict[str, int]:
    """Drain Q2, Q3, then Q1 up to the shared batch-size limit."""
    recover_stale_entries()

    demand_drained, demand_failed = _drain_queue(
        client, _DEMAND_TABLE, batch_size, job_run_id
    )
    remaining = batch_size - demand_drained
    activity_drained, activity_failed = _drain_queue(
        client, "ninja_core.software_activity_queue", remaining, job_run_id
    )
    remaining -= activity_drained
    scheduled_drained = 0
    if remaining > 0:
        scheduled_drained, scheduled_failed = _drain_queue(
            client, "ninja_core.software_scheduled_queue", remaining, job_run_id
        )
    else:
        scheduled_failed = 0
    return {
        "demand": demand_drained,
        "activity": activity_drained,
        "scheduled": scheduled_drained,
        "failed": demand_failed + activity_failed + scheduled_failed,
    }


# ── Internal helpers ───────────────────────────────────────────────


def _enqueue(table: str, df: str, reason: str) -> bool:
    with _tenant_cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} (tenant_id, df, reason) "
            "VALUES (1, %s, %s) "
            "ON CONFLICT (df) WHERE status = 'pending' DO NOTHING "
            "RETURNING id",
            (df, reason),
        )
        return cur.fetchone() is not None


def _drain_queue(
    client: NinjaClient, table: str, limit: int, job_run_id: object
) -> tuple[int, int]:
    drained = failed = 0
    for _ in range(limit):
        entry = _claim_one(table, job_run_id)
        if entry is None:
            break
        if not _process_entry(client, table, entry):
            failed += 1
        drained += 1
    return drained, failed


def _claim_one(table: str, job_run_id: object) -> dict | None:
    """Atomically claim the oldest pending entry. Returns dict or None."""
    with _tenant_cursor() as cur:
        cur.execute(
            f"""
            UPDATE {table}
            SET status = 'processing', started_at = NOW(), job_run_id = %s
            WHERE id = (
                SELECT id FROM {table}
                WHERE status = 'pending'
                ORDER BY queued_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, df, attempts, max_attempts
            """,
            (job_run_id,),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                INSERT INTO operations.job_domain_attempts (
                    tenant_id, domain_kind, domain_record_id,
                    attempt_number, job_run_id
                ) VALUES (1, %s, %s, %s, %s)
                """,
                (_DOMAIN_KINDS[table], str(row[0]), int(row[2]) + 1, job_run_id),
            )
    if not row:
        return None
    return dict(zip(["id", "df", "attempts", "max_attempts"], row))


def _process_entry(client: NinjaClient, table: str, entry: dict) -> bool:
    entry_id = entry["id"]
    df = entry["df"]
    attempts = entry["attempts"]
    max_attempts = entry["max_attempts"]
    try:
        rows = _sw.run(client, df=df)
        with _tenant_cursor() as cur:
            cur.execute(
                f"UPDATE {table} "
                "SET status = 'done', completed_at = NOW(), rows_seen = %s "
                "WHERE id = %s",
                (rows, entry_id),
            )
        log.info("Queue %s entry %d done: df=%r rows=%d", table, entry_id, df, rows or 0)
        return True
    except Exception as exc:
        new_attempts = attempts + 1
        err = str(exc)[:_ERROR_MAX]
        if new_attempts < max_attempts:
            with _tenant_cursor() as cur:
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
            with _tenant_cursor() as cur:
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
        return False
