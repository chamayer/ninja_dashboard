"""NIST CPE 2.3 dictionary ingest → intel.cpes.

Two modes, and the distinction matters:

* **Backfill** — pages the full index by ``startIndex`` with no date filter,
  resuming from ``intel.cpe_backfill_state`` and bounded to
  ``_MAX_PAGES_PER_RUN`` per cycle. Runs until the corpus is complete.
* **Delta** — the original behaviour, ``lastModStartDate`` forward from the
  last write.

Delta alone was never going to fill the dictionary, which is why we held
169,951 of NVD's 1,799,756 CPEs (9.4%) while reporting "Upserted 0 CPE
entries": it filters on *modification* date, so a CPE untouched since before
the first run is never returned at all. Measured consequence: the matcher could
only reach 507 of 21,395 catalogue titles.

Sizing, measured 2026-08-11: 867 bytes/row, so the full corpus is ~1.5 GB
against a 46 GB database. ``raw_nvd`` is two thirds of that and nothing reads
it today — the matcher uses vendor/product/version — but it is retained rather
than dropped at ingest.

``NVD_API_KEY`` is configured, so the limit is ~0.65s/request and the full pull
is ~360 pages ≈ 4 minutes -- it should complete in a single cycle. The cursor
exists anyway so an interrupted or rate-limited run resumes rather than
restarting, and so the mode is observable in `intel_ingest_status` rather than
being a thing that silently either happened or did not.

**The backfill is one-time.** Once the cursor's ``completed_at`` is set the
connector returns to delta pulls permanently; nothing re-triggers it. Deltas
then keep the corpus current on the normal catalogue cadence, forever.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_ENDPOINT = "https://services.nvd.nist.gov/rest/json/cpes/2.0"
_PAGE_SIZE = 5000
_FIRST_RUN_LOOKBACK_DAYS = 120
_MAX_PAGES_PER_RUN = 40
# Backfill gets a larger bound than the delta pull because it is finite and
# one-time. With an API key the limit is ~0.65s/request, so the full 1.8M-entry
# corpus is ~360 pages ≈ 4 minutes -- comparable to the other intel connectors,
# and worth finishing in one pass rather than dribbling across nine cycles.
# Still cursor-driven, so an interrupted run resumes exactly where it stopped.
_BACKFILL_MAX_PAGES_PER_RUN = 450


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_NVD_ENABLED):
        log.info("CPE dict ingest disabled by flag; skipping")
        return 0
    with record_run("cpe_dict") as state:
        backfill = _backfill_state()
        if backfill and backfill["completed_at"] is None:
            rows, done, at, total = _backfill_slice(backfill)
            state["rows_touched"] = rows
            pct = (at * 100 // total) if total else 0
            state["notes"] = (
                f"Backfill {'complete' if done else 'in progress'}: "
                f"{at}/{total} ({pct}%), {rows} upserted this run."
            )
            return rows
        rows = _pull_and_upsert()
        state["rows_touched"] = rows
        state["notes"] = f"Upserted {rows} CPE entries."
        return rows


def _backfill_state() -> dict | None:
    """Cursor row, or None if migration 085 has not been applied yet."""
    try:
        with db.transaction() as cur:
            cur.execute(
                "SELECT next_index, total_results, rows_written, started_at, "
                "completed_at FROM intel.cpe_backfill_state WHERE id"
            )
            row = cur.fetchone()
    except Exception:
        log.warning("CPE backfill state unavailable; using delta pull")
        return None
    if not row:
        return None
    return {
        "next_index": row[0], "total_results": row[1], "rows_written": row[2],
        "started_at": row[3], "completed_at": row[4],
    }


def _backfill_slice(state: dict) -> tuple[int, bool, int, int]:
    """Page the full CPE index from the stored cursor, bounded per run.

    The delta pull cannot reach the corpus's history: it filters on
    lastModStartDate, so a CPE untouched since before the first run is never
    returned. That is why we hold 9.4% of the dictionary. This pages by
    startIndex with no date filter instead.

    Returns (rows_written, completed, next_index, total_results).
    """
    api_key = settings.NVD_API_KEY.get_secret_value().strip()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["apiKey"] = api_key
    delay = 0.65 if api_key else 6.5

    at = int(state["next_index"] or 0)
    total = int(state["total_results"] or 0)
    written = 0

    with httpx.Client(timeout=60.0, headers=headers) as client:
        for _ in range(_BACKFILL_MAX_PAGES_PER_RUN):
            payload = _fetch(client, {
                "resultsPerPage": _PAGE_SIZE,
                "startIndex": at,
            })
            batch = payload.get("products") or []
            total = int(payload.get("totalResults") or total)
            if not batch:
                break
            written += _upsert_batch(batch)
            at += len(batch)
            if at >= total:
                break
            time.sleep(delay)

    done = total > 0 and at >= total
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE intel.cpe_backfill_state
               SET next_index    = %s,
                   total_results = %s,
                   rows_written  = rows_written + %s,
                   updated_at    = now(),
                   completed_at  = CASE WHEN %s THEN now() ELSE NULL END
             WHERE id
            """,
            (at, total, written, done),
        )
    log.info(
        "CPE backfill: %d/%d (%d%%), %d upserted this run%s",
        at, total, (at * 100 // total) if total else 0, written,
        " — COMPLETE" if done else "",
    )
    return written, done, at, total


def _pull_and_upsert() -> int:
    cursor = _cursor_from_db()
    end = datetime.now(timezone.utc)
    if cursor is None:
        start = end - timedelta(days=_FIRST_RUN_LOOKBACK_DAYS)
    else:
        start = cursor - timedelta(minutes=15)
    log.info("CPE delta pull: %s .. %s", start.isoformat(), end.isoformat())

    api_key = settings.NVD_API_KEY.get_secret_value().strip()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["apiKey"] = api_key
    delay = 0.65 if api_key else 6.5

    total = 0
    offset = 0
    with httpx.Client(timeout=45.0, headers=headers) as client:
        for _ in range(_MAX_PAGES_PER_RUN):
            payload = _fetch(client, {
                "lastModStartDate": start.isoformat(timespec="seconds"),
                "lastModEndDate":   end.isoformat(timespec="seconds"),
                "resultsPerPage":   _PAGE_SIZE,
                "startIndex":       offset,
            })
            batch = payload.get("products") or []
            grand = payload.get("totalResults") or 0
            if not batch:
                break
            total += _upsert_batch(batch)
            offset += len(batch)
            if offset >= grand:
                break
            time.sleep(delay)
    return total


def _fetch(client: httpx.Client, params: dict) -> dict:
    for attempt in range(4):
        try:
            r = client.get(_ENDPOINT, params=params)
            if r.status_code == 429:
                time.sleep(30)
                continue
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            log.warning("CPE fetch attempt %d failed: %s", attempt, exc)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("CPE fetch failed after retries")


def _cursor_from_db() -> datetime | None:
    """Delta baseline.

    `intel.cpes.updated_at` is when *we* wrote a row, not when NVD modified it.
    That is fine in steady state, but after a backfill every row was written
    during the backfill, so MAX(updated_at) is its completion time and any CPE
    NVD changed while it ran would never be requested again. The backfill's
    `started_at` is the honest baseline in that case; it re-requests a little
    already-held data rather than silently skipping a window.
    """
    with db.transaction() as cur:
        cur.execute("SELECT MAX(updated_at) FROM intel.cpes")
        (latest,) = cur.fetchone()
        try:
            cur.execute(
                "SELECT started_at, completed_at FROM intel.cpe_backfill_state WHERE id"
            )
            row = cur.fetchone()
        except Exception:
            row = None
    if row and row[1] is not None and latest is not None and row[0] < latest:
        return row[0]
    return latest


def _upsert_batch(products: list[dict]) -> int:
    rows: list[tuple] = []
    for entry in products:
        p = entry.get("cpe") or {}
        cpe23 = p.get("cpeName")
        if not cpe23:
            continue
        vendor, product, version = _split(cpe23)
        rows.append((cpe23, vendor, product, version, json.dumps(entry)))
    if not rows:
        return 0
    with db.transaction() as cur:
        cur.executemany(
            """
            INSERT INTO intel.cpes (cpe23, vendor, product, version, raw_nvd, updated_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (cpe23) DO UPDATE SET
                vendor     = EXCLUDED.vendor,
                product    = EXCLUDED.product,
                version    = EXCLUDED.version,
                raw_nvd    = EXCLUDED.raw_nvd,
                updated_at = now()
            """,
            rows,
        )
    return len(rows)


def _split(cpe23: str) -> tuple[str, str, str | None]:
    # cpe:2.3:a:vendor:product:version:...
    parts = cpe23.split(":")
    if len(parts) < 6:
        return ("", "", None)
    vendor = parts[3].replace("\\", "").lower()
    product = parts[4].replace("\\", "").lower()
    version = parts[5].replace("\\", "")
    if version in ("*", "-"):
        version = None
    return vendor, product, version
