"""CISA Known Exploited Vulnerabilities → intel.cves KEV flags.

One HTTPS GET pulls the full catalog (~1,200 rows). We set kev_flag,
kev_added_at, and kev_notes on the matching intel.cves row. If NVD
hasn't ingested the CVE yet we insert a stub row that later NVD runs
will enrich.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_ENDPOINT = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_CISA_KEV_ENABLED):
        log.info("CISA KEV ingest disabled by flag; skipping")
        return 0
    with record_run("cisa_kev") as state:
        rows = _pull_and_upsert()
        state["rows_touched"] = rows
        state["notes"] = f"Flagged {rows} CVEs as KEV."
        return rows


def _pull_and_upsert() -> int:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(_ENDPOINT)
        r.raise_for_status()
        payload = r.json()
    entries = payload.get("vulnerabilities") or []
    kev_rows: list[tuple] = []
    for e in entries:
        cve_id = e.get("cveID")
        if not cve_id:
            continue
        kev_rows.append((
            cve_id,
            _parse_date(e.get("dateAdded")),
            (e.get("shortDescription") or "")[:2000],
        ))
    if not kev_rows:
        return 0
    with db.transaction() as cur:
        # Insert stubs for any CVEs NVD hasn't caught up to yet.
        cur.executemany(
            """
            INSERT INTO intel.cves (cve_id, kev_flag, kev_added_at, kev_notes)
            VALUES (%s, TRUE, %s, %s)
            ON CONFLICT (cve_id) DO UPDATE SET
                kev_flag     = TRUE,
                kev_added_at = EXCLUDED.kev_added_at,
                kev_notes    = EXCLUDED.kev_notes,
                updated_at   = now()
            """,
            kev_rows,
        )
        # Clear kev_flag on any CVE that CISA removed from the list.
        cve_ids = [row[0] for row in kev_rows]
        cur.execute(
            """
            UPDATE intel.cves
            SET kev_flag = FALSE, kev_added_at = NULL, kev_notes = ''
            WHERE kev_flag = TRUE AND NOT (cve_id = ANY(%s::text[]))
            """,
            (cve_ids,),
        )
    return len(kev_rows)


def _parse_date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v).date()
    except ValueError:
        return None
