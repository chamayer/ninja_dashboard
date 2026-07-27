"""Chocolatey community feed enrichment → operations.safety_signal.

Per-title queries against the community OData search endpoint. Same
shape as the Winget enricher; runs on the same cadence.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_ENDPOINT = "https://community.chocolatey.org/api/v2/Packages()"
_TENANT_ID = 1
_STALE_AFTER = timedelta(days=30)
_MAX_TITLES_PER_RUN = 500
_DELAY_SECONDS = 0.5

_TAG_ELEMENT = re.compile(r"<d:Tags[^>]*>(.*?)</d:Tags>", re.S)
_TITLE_ELEMENT = re.compile(r"<title[^>]*>(.*?)</title>", re.S)


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_CHOCOLATEY_ENABLED):
        log.info("Chocolatey enrichment disabled by flag; skipping")
        return 0
    with record_run("chocolatey") as state:
        rows = _enrich()
        state["rows_touched"] = rows
        state["notes"] = f"Chocolatey-enriched {rows} titles."
        return rows


def _enrich() -> int:
    titles = _titles_needing_refresh()
    if not titles:
        return 0
    written = 0
    with httpx.Client(
        timeout=20.0,
        headers={
            "User-Agent": "ninja-dashboard/intel-chocolatey (+ops)",
            "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.5",
        },
        follow_redirects=True,
    ) as client:
        for canonical in titles[:_MAX_TITLES_PER_RUN]:
            try:
                tags, titles_found = _search(client, canonical)
            except httpx.HTTPError as exc:
                log.warning("Chocolatey search failed for %s: %s", canonical, exc)
                continue
            if tags or titles_found:
                written += _write_signal(canonical, tags, titles_found)
            time.sleep(_DELAY_SECONDS)
    return written


def _titles_needing_refresh() -> list[str]:
    with db.transaction() as cur:
        cur.execute(
            """
            WITH latest_signal AS (
                SELECT LOWER(canonical_name) AS canonical, MAX(observed_at) AS observed_at
                FROM operations.safety_signal
                WHERE tenant_id = %s AND source = 'chocolatey' AND canonical_name <> ''
                GROUP BY LOWER(canonical_name)
            )
            SELECT DISTINCT sic.canonical_name
            FROM operations.software_installations_current sic
            LEFT JOIN latest_signal ls ON ls.canonical = LOWER(sic.canonical_name)
            WHERE sic.tenant_id = %s
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND sic.canonical_name <> ''
              AND (ls.observed_at IS NULL OR ls.observed_at < %s)
            ORDER BY sic.canonical_name
            """,
            (_TENANT_ID, _TENANT_ID, datetime.now(timezone.utc) - _STALE_AFTER),
        )
        return [row[0] for row in cur.fetchall()]


def _search(client: httpx.Client, canonical: str) -> tuple[list[str], list[str]]:
    # OData wants ``searchTerm='...'`` quoted, ``$filter`` unmodified,
    # and both keys as raw ``$``-prefixed names. httpx URL-encodes
    # params too aggressively for OData, so hand-assemble the query.
    from urllib.parse import quote
    quoted = quote(canonical[:120].replace("'", ""), safe="")
    url = (
        f"{_ENDPOINT}?searchTerm=%27{quoted}%27"
        "&$filter=IsLatestVersion"
        "&$top=5"
    )
    r = client.get(url)
    if r.status_code == 404:
        return [], []
    r.raise_for_status()
    body = r.text
    tags_raw = _TAG_ELEMENT.findall(body)
    titles = _TITLE_ELEMENT.findall(body)
    tags: set[str] = set()
    for chunk in tags_raw:
        for tag in re.split(r"\s+", chunk.strip()):
            if tag:
                tags.add(tag)
    return sorted(tags), [t.strip() for t in titles if t.strip()]


def _write_signal(canonical: str, tags: list[str], titles_found: list[str]) -> int:
    details = {"tags": tags, "titles_found": titles_found}
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO operations.safety_signal (
                tenant_id, canonical_name, publisher, source,
                signal_type, severity, details
            ) VALUES (%s, %s, '', 'chocolatey', 'category', 'info', %s::jsonb)
            ON CONFLICT (tenant_id, LOWER(canonical_name), LOWER(publisher), source, signal_type)
            DO UPDATE SET details = EXCLUDED.details, observed_at = now()
            """,
            (_TENANT_ID, canonical, json.dumps(details)),
        )
    return 1
