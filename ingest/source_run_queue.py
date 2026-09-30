"""Source run demand queue.

Operator-triggered runs for Ninja, SentinelOne, ScreenConnect, LogMeIn.
One pending entry per source (df) enforced by partial unique index.

df values:
  'Ninja'        — full patching/device ingest run
  'SentinelOne'  — S1 observations → entity_observations
  'ScreenConnect' — SC observations → entity_observations
  'LogMeIn'      — LMI observations → entity_observations

Demand entries are retained until the governed Jobs worker claims them.
Stale processing entries are marked failed; an operator must resubmit them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ingest import db
from ingest.derived import refresh_after_collection

log = logging.getLogger(__name__)

_TABLE = "operations.source_run_queue"
_LEASE_MINUTES = 30

# Bootstrap fallback only — the real list comes from registered sources via
# available_sources(). Kept so the trigger page still renders if the lookup
# fails rather than offering nothing.
_SOURCES_FALLBACK = ("Ninja", "SentinelOne", "ScreenConnect", "LogMeIn")


def available_sources() -> tuple[str, ...]:
    """Platforms that can be run on demand, from configuration.

    'Ninja' is always included: it is collected by its own pipeline rather
    than through a registered source binding, but is still triggerable here.
    """
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT DISTINCT COALESCE(NULLIF(si.config->>'platform', ''), s.name)
                  FROM operations.sources s
                  JOIN operations.source_instances si ON si.source_id = s.id
                 WHERE si.tenant_id = 1 AND si.enabled
                """
            )
            names = {r[0] for r in cur.fetchall() if r[0]}
    except Exception:
        log.exception("source list query failed — using fallback")
        return _SOURCES_FALLBACK
    names.add("Ninja")
    return tuple(sorted(names)) or _SOURCES_FALLBACK


# ── Enqueue ─────────────────────────────────────────────────────────


def enqueue(source: str, reason: str = "") -> int:
    """Insert a pending entry for source. Returns entry id.

    Deduped: if a pending entry already exists for this source, returns
    the existing id without inserting.
    """
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"INSERT INTO {_TABLE} (tenant_id, df, reason) VALUES (1, %s, %s) "
            "ON CONFLICT (df) WHERE status = 'pending' DO NOTHING RETURNING id",
            (source, reason),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute(
            f"SELECT id FROM {_TABLE} WHERE tenant_id = 1 AND df = %s AND status = 'pending'",
            (source,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


# ── Status queries ───────────────────────────────────────────────────


def get_status(entry_id: int) -> dict | None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            SELECT id, df, reason, status, attempts, max_attempts,
                   queued_at, started_at, completed_at, rows_seen, error
            FROM {_TABLE} WHERE tenant_id = 1 AND id = %s
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
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(f"SELECT status, COUNT(*) FROM {_TABLE} WHERE tenant_id = 1 GROUP BY status")
        counts = {row[0]: int(row[1]) for row in cur.fetchall()}

        cur.execute(
            f"""
            SELECT {', '.join(_cols)} FROM {_TABLE}
            WHERE tenant_id = 1 AND status = 'processing' ORDER BY started_at LIMIT 20
            """
        )
        active = [dict(zip(_cols, row)) for row in cur.fetchall()]

        cur.execute(
            f"""
            SELECT {', '.join(_cols)} FROM {_TABLE}
            WHERE tenant_id = 1 AND status IN ('done', 'failed')
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
            WHERE tenant_id = 1 AND status = 'processing'
              AND started_at < NOW() - INTERVAL '{_LEASE_MINUTES} minutes'
            """
        )
        n = cur.rowcount
    if n:
        log.warning("source_run_queue: expired %d stale entries", n)
    return n


# ── Demand worker ────────────────────────────────────────────────────


def process_entry(entry_id: int, job_run_id: object) -> int:
    """Claim and execute one demand entry under its durable Job run."""
    # Late imports to avoid circular deps at module load time.
    from ingest.source_observations import SourceObservationFailure, run_source_observations
    from ingest.sources import load_sources

    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            UPDATE {_TABLE}
            SET status = 'processing', started_at = NOW(), attempts = attempts + 1,
                job_run_id = %s
            WHERE tenant_id = 1 AND id = %s AND status = 'pending'
              AND job_run_id IS NULL
            RETURNING df, attempts, max_attempts
            """,
            (job_run_id, entry_id),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                INSERT INTO operations.job_domain_attempts (
                    tenant_id, domain_kind, domain_record_id,
                    attempt_number, job_run_id
                ) VALUES (1, 'source.demand', %s, %s, %s)
                """,
                (str(entry_id), int(row[1]), job_run_id),
            )

    if not row:
        log.warning("source_run_queue: entry %d not claimable (already running?)", entry_id)
        return 0

    df, attempts, max_attempts = row
    log.info("source_run_queue: processing entry=%d source=%s attempt=%d", entry_id, df, attempts)

    rows_seen = 0
    error: str | None = None
    try:
        if df == "Ninja":
            from ingest.main import run_ninja_observations_once
            run_ninja_observations_once()
        elif df in available_sources():
            sources = [s for s in load_sources() if s.platform == df]
            observed_at = datetime.now(timezone.utc)
            collection_failure = None
            try:
                counts = run_source_observations(sources, observed_at)
            except SourceObservationFailure as exc:
                counts = exc.counts
                collection_failure = exc
            rows_seen = sum(counts.values())
            refresh_after_collection(f"on-demand {df} collection")
            if collection_failure:
                raise collection_failure
        else:
            raise ValueError(f"Unknown source: {df!r}")
    except Exception as exc:
        error = str(exc)[:2000]
        log.exception("source_run_queue: entry %d failed: %s", entry_id, df)

    status = "failed" if error else "done"
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            UPDATE {_TABLE}
            SET status = %s, completed_at = NOW(), rows_seen = %s, error = %s
            WHERE tenant_id = 1 AND id = %s
            """,
            (status, rows_seen or None, error, entry_id),
        )
    log.info(
        "source_run_queue: entry=%d source=%s status=%s rows=%s",
        entry_id, df, status, rows_seen,
    )
    if error:
        raise RuntimeError(error)
    return 1


def process_next(job_run_id: object) -> int:
    """Process one retained demand entry under the governed Jobs worker."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"SELECT id FROM {_TABLE} WHERE tenant_id = 1 AND status = 'pending' "
            "AND job_run_id IS NULL ORDER BY queued_at, id LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        return 0
    return process_entry(int(row[0]), job_run_id)


def enqueue_and_run(source: str, reason: str = "") -> int:
    """Compatibility name: enqueue only; the Jobs worker executes demand."""
    return enqueue(source, reason)
