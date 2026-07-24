"""NIST NVD v2 API delta ingest → intel.cves.

Free tier with API key: 50 requests / 30s rolling window. Without:
5 / 30s. We honour whichever we have. Delta cursor comes from
``MAX(last_modified_at)`` on ``intel.cves``; on first run we pull the
last 120 days to build a working table without exhausting the whole
history.

NVD returns up to 2000 items per page; each response carries
``totalResults`` so we page until the offset exceeds it.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_ENDPOINT = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_PAGE_SIZE = 2000
_FIRST_RUN_LOOKBACK_DAYS = 120
_MAX_PAGES_PER_RUN = 40  # ~80k CVEs; safety valve


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_NVD_ENABLED):
        log.info("NVD ingest disabled by flag; skipping")
        return 0
    with record_run("nvd") as state:
        rows = _pull_and_upsert()
        state["rows_touched"] = rows
        state["notes"] = f"Upserted {rows} CVEs from NVD."
        return rows


def _pull_and_upsert() -> int:
    cursor = _cursor_from_db()
    end = datetime.now(timezone.utc)
    if cursor is None:
        start = end - timedelta(days=_FIRST_RUN_LOOKBACK_DAYS)
    else:
        # Small overlap window so a race with NVD publishing doesn't miss rows.
        start = cursor - timedelta(minutes=15)
    log.info("NVD delta pull: %s .. %s", start.isoformat(), end.isoformat())

    api_key = settings.NVD_API_KEY.get_secret_value().strip()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["apiKey"] = api_key
    delay = 0.65 if api_key else 6.5  # ~ rate-limit / N with a margin

    total_upserted = 0
    offset = 0
    with httpx.Client(timeout=30.0, headers=headers) as client:
        for page_index in range(_MAX_PAGES_PER_RUN):
            params = {
                "lastModStartDate": start.isoformat(timespec="seconds"),
                "lastModEndDate":   end.isoformat(timespec="seconds"),
                "resultsPerPage":   _PAGE_SIZE,
                "startIndex":       offset,
            }
            payload = _fetch(client, params)
            batch = payload.get("vulnerabilities") or []
            total = payload.get("totalResults") or 0
            if not batch:
                break
            total_upserted += _upsert_batch(batch)
            offset += len(batch)
            log.info("NVD page %d: %d rows (offset %d / %d)",
                     page_index, len(batch), offset, total)
            if offset >= total:
                break
            time.sleep(delay)
    return total_upserted


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
            log.warning("NVD fetch attempt %d failed: %s", attempt, exc)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("NVD fetch failed after retries")


def _cursor_from_db() -> datetime | None:
    with db.transaction() as cur:
        cur.execute("SELECT MAX(last_modified_at) FROM intel.cves")
        (v,) = cur.fetchone()
        return v


def _upsert_batch(vulns: list[dict[str, Any]]) -> int:
    rows: list[tuple] = []
    for entry in vulns:
        cve = entry.get("cve") or {}
        cve_id = cve.get("id")
        if not cve_id:
            continue
        metrics = cve.get("metrics") or {}
        cvss_v3, cvss_v3_vec = _first_cvss(metrics, "cvssMetricV31") \
            or _first_cvss(metrics, "cvssMetricV30") \
            or (None, None)
        cvss_v4, cvss_v4_vec = _first_cvss(metrics, "cvssMetricV40") or (None, None)
        severity = _severity(cvss_v3 or cvss_v4)
        descriptions = cve.get("descriptions") or []
        description = next(
            (d.get("value") for d in descriptions if d.get("lang") == "en"),
            "",
        )
        cwes = [
            weak.get("description", [{}])[0].get("value", "")
            for weak in cve.get("weaknesses", []) or []
        ]
        cwes = [c for c in cwes if c.startswith("CWE-")]
        affected_cpes = _extract_cpes(cve.get("configurations") or [])
        rows.append((
            cve_id,
            cvss_v3, cvss_v3_vec,
            cvss_v4, cvss_v4_vec,
            severity,
            _parse_dt(cve.get("published")),
            _parse_dt(cve.get("lastModified")),
            description,
            cwes,
            json.dumps(affected_cpes),
            json.dumps(entry),
        ))
    if not rows:
        return 0
    with db.transaction() as cur:
        cur.executemany(
            """
            INSERT INTO intel.cves (
                cve_id, cvss_v3, cvss_v3_vector, cvss_v4, cvss_v4_vector,
                severity, published_at, last_modified_at, description,
                cwes, affected_cpes, raw_nvd, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now()
            )
            ON CONFLICT (cve_id) DO UPDATE SET
                cvss_v3          = EXCLUDED.cvss_v3,
                cvss_v3_vector   = EXCLUDED.cvss_v3_vector,
                cvss_v4          = EXCLUDED.cvss_v4,
                cvss_v4_vector   = EXCLUDED.cvss_v4_vector,
                severity         = EXCLUDED.severity,
                published_at     = EXCLUDED.published_at,
                last_modified_at = EXCLUDED.last_modified_at,
                description      = EXCLUDED.description,
                cwes             = EXCLUDED.cwes,
                affected_cpes    = EXCLUDED.affected_cpes,
                raw_nvd          = EXCLUDED.raw_nvd,
                updated_at       = now()
            """,
            rows,
        )
    return len(rows)


def _first_cvss(metrics: dict, key: str) -> tuple[float | None, str | None] | None:
    entries = metrics.get(key) or []
    if not entries:
        return None
    m = entries[0].get("cvssData") or {}
    score = m.get("baseScore")
    vector = m.get("vectorString")
    if score is None:
        return None
    return float(score), vector


def _severity(score: float | None) -> str:
    if score is None:
        return "none"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def _extract_cpes(configurations: list[dict]) -> list[str]:
    out: set[str] = set()
    for config in configurations:
        for node in config.get("nodes", []) or []:
            for m in node.get("cpeMatch", []) or []:
                cpe = m.get("criteria")
                if cpe:
                    out.add(cpe)
    return sorted(out)


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    # NVD publishes ISO strings, sometimes without tz. Coerce to UTC.
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
