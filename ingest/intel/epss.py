"""FIRST.org EPSS score CSV → intel.cves EPSS columns.

One gzipped CSV per day, ~250k rows, ``cve,epss,percentile`` shape.
We only update rows that already exist in intel.cves (NVD-known),
which keeps the update set bounded.
"""

from __future__ import annotations

import csv
import gzip
import io
import logging

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_ENDPOINT = "https://epss.cyentia.com/epss_scores-current.csv.gz"


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_EPSS_ENABLED):
        log.info("EPSS ingest disabled by flag; skipping")
        return 0
    with record_run("epss") as state:
        rows = _pull_and_upsert()
        state["rows_touched"] = rows
        state["notes"] = f"Updated {rows} CVEs with EPSS scores."
        return rows


def _pull_and_upsert() -> int:
    with httpx.Client(timeout=60.0) as client:
        r = client.get(_ENDPOINT)
        r.raise_for_status()
        payload = r.content
    text = gzip.decompress(payload).decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    # First row is a metadata comment starting with '#'; the header is next.
    header: list[str] = []
    rows: list[tuple] = []
    for row in reader:
        if not row:
            continue
        if row[0].startswith("#"):
            continue
        if not header:
            header = row
            continue
        if len(row) < 3:
            continue
        cve_id, epss, percentile = row[0], row[1], row[2]
        try:
            rows.append((float(epss), float(percentile), cve_id))
        except ValueError:
            continue
    if not rows:
        return 0
    with db.transaction() as cur:
        # Only touch existing CVE rows — EPSS carries hundreds of thousands
        # of scores; without this gate we'd insert every one as a stub.
        cur.executemany(
            """
            UPDATE intel.cves
               SET epss_score = %s, epss_percentile = %s, updated_at = now()
             WHERE cve_id = %s
            """,
            rows,
        )
        cur.execute("SELECT COUNT(*) FROM intel.cves WHERE epss_score IS NOT NULL")
        (updated,) = cur.fetchone()
    return int(updated)
