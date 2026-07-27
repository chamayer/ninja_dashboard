"""NIST CPE 2.3 dictionary ingest → intel.cpes.

Rather than pulling the whole ~1M-row XML feed, we page the same NVD v2
CPE endpoint incrementally. First run picks up a bounded slice; steady
state pulls delta by ``lastModStartDate``. Vendor/product columns are
lowered and stored raw for matcher use.
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


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_NVD_ENABLED):
        log.info("CPE dict ingest disabled by flag; skipping")
        return 0
    with record_run("cpe_dict") as state:
        rows = _pull_and_upsert()
        state["rows_touched"] = rows
        state["notes"] = f"Upserted {rows} CPE entries."
        return rows


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
    with db.transaction() as cur:
        cur.execute("SELECT MAX(updated_at) FROM intel.cpes")
        (v,) = cur.fetchone()
        return v


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
