"""Platform-health findings: ingest failures and stalled queues.

Two conditions were registered as `finding_class='admin'` finding types but
nothing ever emitted them. Meanwhile `activities` failed 20 times in 7 days,
`agent_compliance` 11 times, and `software.activity` sat at 4x its configured
`max_depth` — all silent. This module closes that gap.

  - `source_failure`         — an ingest domain whose most recent run failed.
  - `software_queue_stalled` — a registered queue over its own `max_depth`
                               or `max_pending_age_m` threshold.

Both surface on the Operations admin health page (`findings_admin_health`),
which lists `FindingType.objects.filter(finding_class="admin")` — no UI work
is required for them to appear.

Subject convention follows the existing admin-finding precedent in
`ingest/identity/resolver.py`: `subject_type='source_binding'` with a
deterministic UUID and the real context in `finding_details`. Neither an
ingest domain nor a queue is literally a source binding, but there is no
subject type for either and inventing one is a schema change.

Default is dry-run: nothing is written unless `dry_run=False` is passed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from ingest import db
from ingest.cmdb_findings import (
    TENANT_ID,
    _finding_type_id,
    _resolve_absent,
    _upsert,
)

log = logging.getLogger(__name__)

# Deterministic subject IDs — same domain/queue always yields the same UUID,
# so a finding reopens rather than duplicating.
_NS = uuid.UUID("6f6d1f9c-0d2c-4a1e-9a6b-2f0f5f2a1c77")

# Queue tables share one schema (id, df, reason, queued_at, status, ...).
# A registry row whose table lacks it is skipped and logged rather than
# silently ignored.
_QUEUE_COLUMNS = ("status", "queued_at")


def _subject(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{kind}:{key}")


def evaluate(*, dry_run: bool = True) -> dict[str, int]:
    """Emit platform-health findings. Returns per-condition counts."""
    now = datetime.now(UTC)
    counts = {"source_failure": 0, "software_queue_stalled": 0, "queues_skipped": 0}

    with db.transaction() as cur:
        ft_failure = _finding_type_id(cur, "source_failure")
        ft_queue = _finding_type_id(cur, "software_queue_stalled")

        failure_keys = _eval_source_failures(cur, ft_failure, now, counts, dry_run)
        queue_keys = _eval_stalled_queues(cur, ft_queue, now, counts, dry_run)

        if not dry_run:
            _resolve_absent(cur, ft_failure, failure_keys, now)
            _resolve_absent(cur, ft_queue, queue_keys, now)

    log.info("platform findings: %s (dry_run=%s)", counts, dry_run)
    return counts


def _eval_source_failures(
    cur: Any, finding_type_id: int, now: datetime, counts: dict[str, int], dry_run: bool
) -> list[str]:
    """One finding per domain whose LATEST run failed.

    Keyed on the latest run rather than any recent failure, so a transient
    blip that has since recovered does not hold a finding open.
    """
    cur.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (domain)
                   domain, status, error_text, started_at, finished_at
              FROM ninja_core.run_log
             WHERE status <> 'running'
             ORDER BY domain, started_at DESC
        ),
        recent AS (
            SELECT domain,
                   count(*) FILTER (WHERE status = 'failed') AS failures_24h,
                   max(started_at) FILTER (WHERE status = 'ok') AS last_ok
              FROM ninja_core.run_log
             WHERE started_at > now() - interval '24 hours'
             GROUP BY domain
        )
        SELECT l.domain, l.error_text, l.started_at,
               COALESCE(r.failures_24h, 0), r.last_ok
          FROM latest l
          LEFT JOIN recent r ON r.domain = l.domain
         WHERE l.status = 'failed'
         ORDER BY l.domain
        """
    )
    keys: list[str] = []
    for domain, error_text, started_at, failures_24h, last_ok in cur.fetchall():
        key = f"source_failure:{domain}"
        keys.append(key)
        counts["source_failure"] += 1
        if dry_run:
            continue
        _upsert(
            cur,
            tenant_id=TENANT_ID,
            finding_type_id=finding_type_id,
            client_id=None,
            subject_type="source_binding",
            subject_id=_subject("domain", domain),
            condition_key=key,
            # A domain with no success in 24h is broken, not flaky.
            severity="high" if last_ok is None else "medium",
            now=now,
            details={
                "domain": domain,
                "last_failure_at": started_at.isoformat() if started_at else None,
                "failures_24h": failures_24h,
                "last_success_at": last_ok.isoformat() if last_ok else None,
                "error": (error_text or "")[:500],
            },
        )
    return keys


def _eval_stalled_queues(
    cur: Any, finding_type_id: int, now: datetime, counts: dict[str, int], dry_run: bool
) -> list[str]:
    """One finding per enabled queue breaching its registered thresholds."""
    cur.execute(
        """
        SELECT queue_key, table_name, max_pending_age_m, max_depth
          FROM operations.queue_registry
         WHERE enabled
         ORDER BY queue_key
        """
    )
    registry = cur.fetchall()

    keys: list[str] = []
    for queue_key, table_name, max_age_m, max_depth in registry:
        if not _queue_is_measurable(cur, table_name):
            counts["queues_skipped"] += 1
            log.warning(
                "platform findings: queue %s (%s) not measurable — skipped",
                queue_key, table_name,
            )
            continue

        schema, _, table = table_name.partition(".")
        cur.execute(
            sql.SQL(
                """
                SELECT count(*) FILTER (WHERE status = 'pending'),
                       EXTRACT(EPOCH FROM (
                           now() - min(queued_at) FILTER (WHERE status = 'pending')
                       )) / 60
                  FROM {}
                """
            ).format(sql.Identifier(schema, table))
        )
        depth, oldest_age_m = cur.fetchone()
        depth = depth or 0
        oldest_age_m = float(oldest_age_m or 0)

        # A threshold of 0 means "unset", not "zero tolerance" — treat as off.
        over_depth = bool(max_depth) and depth > max_depth
        over_age = bool(max_age_m) and oldest_age_m > max_age_m
        if not (over_depth or over_age):
            continue

        key = f"software_queue_stalled:{queue_key}"
        keys.append(key)
        counts["software_queue_stalled"] += 1
        if dry_run:
            continue
        _upsert(
            cur,
            tenant_id=TENANT_ID,
            finding_type_id=finding_type_id,
            client_id=None,
            subject_type="source_binding",
            subject_id=_subject("queue", queue_key),
            condition_key=key,
            severity="high" if (over_depth and over_age) else "medium",
            now=now,
            details={
                "queue_key": queue_key,
                "table_name": table_name,
                "pending_depth": depth,
                "max_depth": max_depth,
                "oldest_pending_minutes": round(oldest_age_m, 1),
                "max_pending_age_m": max_age_m,
                "breached": [
                    b for b, hit in (("depth", over_depth), ("age", over_age)) if hit
                ],
            },
        )
    return keys


def _queue_is_measurable(cur: Any, table_name: str | None) -> bool:
    """True when the registry's table exists and carries the expected columns."""
    if not table_name or "." not in table_name:
        return False
    schema, _, table = table_name.partition(".")
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table_name,))
    if not cur.fetchone()[0]:
        return False
    cur.execute(
        """
        SELECT count(*) FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s AND column_name = ANY(%s)
        """,
        (schema, table, list(_QUEUE_COLUMNS)),
    )
    return cur.fetchone()[0] == len(_QUEUE_COLUMNS)
