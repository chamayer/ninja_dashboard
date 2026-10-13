"""Software device queue: which computers need their software list fetched.

A computer is queued when Ninja reports a software change on it (added,
removed or updated activity) or when an operator asks for a refresh. Pending
entries combine per computer. The device worker claims every pending entry,
fetches the lists in batches with one Ninja request each
(``df=id in (...)``, about 0.5 s for 20 computers, measured 2026-10-13), and
applies each batch in one transaction (``inventory.software.apply``).

The daily fleet check covers everything else, so this queue is only about
freshness. (The table keeps its historical name, ``software_activity_queue``.)

Failure handling: a failed batch returns its entries to pending until their
``max_attempts`` is reached, then leaves them failed with the error; entries a
killed worker left in processing return to pending when the next run starts.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from ingest import db
from ingest.inventory import software as _sw

log = logging.getLogger(__name__)

TABLE = "ninja_core.software_activity_queue"
DOMAIN_KIND = "software.activity"
BATCH_DEVICES = 100
MAX_CLAIM = 5000
_ERROR_MAX = 2000
_DEVICE_DF = re.compile(r"^id=(\d+)$")

SOFTWARE_ACTIVITY_TYPES: frozenset[str] = frozenset(
    (
        "SOFTWARE_ADDED",
        "SOFTWARE_REMOVED",
        "SOFTWARE_UPDATED",
    )
)


@contextmanager
def _tenant_cursor() -> Iterator[object]:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        yield cur


def enqueue_activity(ninja_device_id: int, reason: str = "") -> bool:
    """Queue one computer. Returns True if inserted, False if already pending."""
    with _tenant_cursor() as cur:
        cur.execute(
            f"INSERT INTO {TABLE} (tenant_id, df, reason) "
            "VALUES (1, %s, %s) "
            "ON CONFLICT (df) WHERE status = 'pending' DO NOTHING "
            "RETURNING id",
            (f"id={int(ninja_device_id)}", reason),
        )
        return cur.fetchone() is not None


def recover_stale_entries() -> int:
    """Release entries a dead worker left in processing (not counted as an attempt).

    Called before this run claims anything. The Jobs control plane runs one
    software inventory job at a time (resource ``tenant:<id>:software-inventory``),
    so every entry still in processing belongs to a run that ended without
    finishing, typically a deploy restart. Waiting out a lease would only delay
    the retry. An entry whose computer already has a newer pending request is
    closed as superseded instead, since only one pending entry per computer may
    exist.
    """
    with _tenant_cursor() as cur:
        cur.execute(
            f"""
            UPDATE {TABLE} entry
               SET status = 'done', completed_at = NOW(),
                   error = 'Interrupted; superseded by a newer request for this computer.'
             WHERE status = 'processing'
               AND EXISTS (
                   SELECT 1 FROM {TABLE} pending
                    WHERE pending.df = entry.df AND pending.status = 'pending')
            """,
        )
        superseded = cur.rowcount
        cur.execute(
            f"""
            UPDATE {TABLE}
               SET status = 'pending', started_at = NULL, worker_id = NULL
             WHERE status = 'processing'
            """,
        )
        recovered = cur.rowcount
    if recovered or superseded:
        log.warning(
            "Released %d interrupted software queue entries (%d superseded)",
            recovered,
            superseded,
        )
    return recovered


CLAIM_SQL = f"""
UPDATE {TABLE}
   SET status = 'processing', started_at = NOW(), job_run_id = %(run)s
 WHERE id IN (
       SELECT id FROM {TABLE}
        WHERE status = 'pending'
        ORDER BY queued_at
        FOR UPDATE SKIP LOCKED
        LIMIT %(limit)s)
RETURNING id, df, attempts, max_attempts
"""

# Lease recovery resets an entry to pending without bumping ``attempts``, so the
# recorded history, not the counter, decides the next attempt number; reusing
# one aborts the claim.
ATTEMPTS_SQL = """
INSERT INTO operations.job_domain_attempts (
    tenant_id, domain_kind, domain_record_id, attempt_number, job_run_id)
SELECT 1, %(kind)s, claimed.id::text,
       GREATEST(claimed.attempts + 1, COALESCE(recorded.latest, 0) + 1), %(run)s
  FROM unnest(%(ids)s::bigint[], %(attempts)s::int[]) AS claimed(id, attempts)
  LEFT JOIN (
       SELECT domain_record_id, max(attempt_number) AS latest
         FROM operations.job_domain_attempts
        WHERE tenant_id = 1 AND domain_kind = %(kind)s
          AND domain_record_id = ANY(%(keys)s)
        GROUP BY domain_record_id) recorded
    ON recorded.domain_record_id = claimed.id::text
"""


@dataclass
class Entry:
    id: int
    df: str
    attempts: int
    max_attempts: int

    @property
    def ninja_device_id(self) -> int | None:
        match = _DEVICE_DF.match(self.df or "")
        return int(match.group(1)) if match else None


def claim(job_run_id: object, limit: int = MAX_CLAIM) -> list[Entry]:
    """Lease every pending entry (oldest first) in one statement."""
    with _tenant_cursor() as cur:
        cur.execute(CLAIM_SQL, {"run": job_run_id, "limit": limit})
        entries = [Entry(int(r[0]), r[1], int(r[2]), int(r[3])) for r in cur.fetchall()]
        if entries:
            cur.execute(
                ATTEMPTS_SQL,
                {
                    "kind": DOMAIN_KIND,
                    "run": job_run_id,
                    "ids": [entry.id for entry in entries],
                    "attempts": [entry.attempts for entry in entries],
                    "keys": [str(entry.id) for entry in entries],
                },
            )
    return entries


def _finish(entries: list[Entry], error: str = "") -> int:
    """Mark entries done, or return them to pending / failed after an error."""
    if not entries:
        return 0
    ids = [entry.id for entry in entries]
    with _tenant_cursor() as cur:
        if not error:
            cur.execute(
                f"UPDATE {TABLE} SET status = 'done', completed_at = NOW(), error = NULL "
                "WHERE id = ANY(%s)",
                (ids,),
            )
            return 0
        cur.execute(
            f"""
            UPDATE {TABLE}
               SET attempts = attempts + 1, error = %s,
                   status = CASE WHEN attempts + 1 < max_attempts THEN 'pending' ELSE 'failed' END,
                   started_at = CASE WHEN attempts + 1 < max_attempts THEN NULL ELSE started_at END,
                   completed_at = CASE WHEN attempts + 1 < max_attempts THEN NULL ELSE NOW() END
             WHERE id = ANY(%s)
            """,
            (error[:_ERROR_MAX], ids),
        )
    return len(entries)


@dataclass
class DrainResult:
    entries: int = 0
    failed: int = 0
    result: _sw.ApplyResult | None = None

    @property
    def material_changed(self) -> bool:
        return bool(self.result and self.result.material_changed)


def _add(total: _sw.ApplyResult, part: _sw.ApplyResult) -> None:
    for name in (
        "seen",
        "unresolved",
        "devices",
        "new",
        "changed",
        "unchanged",
        "removed",
        "relinked",
        "held_devices",
    ):
        setattr(total, name, getattr(total, name) + getattr(part, name))
    total.complete = total.complete and part.complete


def drain(
    client: object,
    job_run_id: object,
    count: Callable[[int, int | None, str], None] | None = None,
) -> DrainResult:
    """Fetch and apply every queued computer, ``BATCH_DEVICES`` per request.

    ``count`` receives (requests handled, requests claimed, unit) per batch.
    """
    recover_stale_entries()
    entries = claim(job_run_id)
    outcome = DrainResult(entries=len(entries), result=_sw.ApplyResult())
    if not entries:
        return outcome
    unusable = [entry for entry in entries if entry.ninja_device_id is None]
    outcome.failed += _finish(
        unusable, "Not a single-computer request (expected id=<number>)."
    )
    usable = [entry for entry in entries if entry.ninja_device_id is not None]
    device_map = _sw.load_device_map()
    handled = len(unusable)
    if count is not None:
        count(handled, len(entries), "computers")
    for start in range(0, len(usable), BATCH_DEVICES):
        batch = usable[start : start + BATCH_DEVICES]
        try:
            part = _sw.device_refresh(
                client, [entry.ninja_device_id for entry in batch], device_map
            )
        except Exception as exc:
            log.warning("Software device batch of %d failed: %s", len(batch), exc)
            outcome.failed += _finish(batch, str(exc) or exc.__class__.__name__)
        else:
            _add(outcome.result, part)
            _finish(batch)
        finally:
            handled += len(batch)
            if count is not None:
                count(handled, len(entries), "computers")
    log.info(
        "Software device worker: entries=%d failed=%d %s",
        outcome.entries,
        outcome.failed,
        outcome.result.summary(),
    )
    return outcome
