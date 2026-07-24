"""Winget manifest search enrichment → operations.safety_signal.

Bulk-cloning ``microsoft/winget-pkgs`` costs multiple GB; instead we
query the same REST search endpoint the winget CLI uses, once per
canonical title we've observed in the fleet that we don't already have
a fresh signal for. Tags land as ``signal_type='category'``; publisher
context as ``signal_type='community_flag'``.
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

_ENDPOINT = "https://cdn.winget.microsoft.com/cache/api/manifestSearch"
_TENANT_ID = 1
_STALE_AFTER = timedelta(days=30)
_MAX_TITLES_PER_RUN = 500
_DELAY_SECONDS = 0.4  # ~2.5 req/s, well under any reasonable free-tier ceiling


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_WINGET_ENABLED):
        log.info("Winget enrichment disabled by flag; skipping")
        return 0
    with record_run("winget") as state:
        rows = _enrich()
        state["rows_touched"] = rows
        state["notes"] = f"Winget-enriched {rows} titles."
        return rows


def _enrich() -> int:
    titles = _titles_needing_refresh()
    if not titles:
        return 0
    written = 0
    with httpx.Client(timeout=20.0) as client:
        for canonical in titles[:_MAX_TITLES_PER_RUN]:
            try:
                packages = _search(client, canonical)
            except httpx.HTTPError as exc:
                log.warning("Winget search failed for %s: %s", canonical, exc)
                continue
            if packages:
                written += _write_signals(canonical, packages)
            time.sleep(_DELAY_SECONDS)
    return written


def _titles_needing_refresh() -> list[str]:
    with db.transaction() as cur:
        cur.execute(
            """
            WITH latest_signal AS (
                SELECT LOWER(canonical_name) AS canonical, MAX(observed_at) AS observed_at
                FROM operations.safety_signal
                WHERE tenant_id = %s AND source = 'winget' AND canonical_name <> ''
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


def _search(client: httpx.Client, canonical: str) -> list[dict]:
    body = {
        "Query": {"KeyWord": canonical[:120], "MatchType": "Substring"},
        "MaximumResults": 5,
    }
    r = client.post(_ENDPOINT, json=body)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    data = r.json() or {}
    return data.get("Data") or []


def _write_signals(canonical: str, packages: list[dict]) -> int:
    # One aggregated row per (canonical, source, signal_type) to match
    # the partial unique index. Multiple package matches are folded
    # into a single JSON payload.
    tags: set[str] = set()
    publishers: list[str] = []
    monikers: list[str] = []
    identifiers: list[str] = []
    for pkg in packages:
        for tag in (pkg.get("Tags") or []):
            if tag:
                tags.add(str(tag))
        publisher = pkg.get("Publisher") or pkg.get("PackageName") or ""
        if publisher:
            publishers.append(publisher)
        moniker = pkg.get("Moniker") or ""
        if moniker:
            monikers.append(moniker)
        pkg_id = pkg.get("PackageIdentifier")
        if pkg_id:
            identifiers.append(pkg_id)
    details = {
        "package_identifiers": identifiers,
        "publishers": publishers,
        "monikers": monikers,
        "tags": sorted(tags),
    }
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO operations.safety_signal (
                tenant_id, canonical_name, publisher, source,
                signal_type, severity, details
            ) VALUES (%s, %s, '', 'winget', 'category', 'info', %s::jsonb)
            ON CONFLICT (tenant_id, LOWER(canonical_name), LOWER(publisher), source, signal_type)
            DO UPDATE SET details = EXCLUDED.details, observed_at = now()
            """,
            (_TENANT_ID, canonical, json.dumps(details)),
        )
    return 1
