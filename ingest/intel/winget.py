"""Winget enrichment via the community `winget.run` REST API.

Microsoft's own ``cdn.winget.microsoft.com/cache/api/manifestSearch``
endpoint returns 405 UnsupportedHttpVerb on POST from arbitrary
clients — that CDN is designed for the winget CLI, not third-party
callers. The community-run https://api.winget.run mirror serves the
same manifest data through a simple GET-friendly REST API with no
auth, so we use it as the enrichment source for tags and publisher.

Per-title queries against ``/v2/packages`` (search); one HTTPS GET per
canonical we've observed and don't already have a fresh signal for.
Exact-match only, one row per canonical (source='winget',
signal_type='category') — see ``_search`` for why.
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

_SEARCH_ENDPOINT = "https://api.winget.run/v2/packages"
_TENANT_ID = 1
_STALE_AFTER = timedelta(days=30)
_MAX_TITLES_PER_RUN = 500
_DELAY_SECONDS = 0.4
_USER_AGENT = "ninja-dashboard/intel-winget (+ops)"
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(value: str) -> str:
    return _NORMALIZE_RE.sub("", value.lower())


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
    with httpx.Client(
        timeout=20.0,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        for canonical in titles[:_MAX_TITLES_PER_RUN]:
            try:
                tags, publisher, package_id, titles_found = _search(client, canonical)
            except httpx.HTTPError as exc:
                log.warning("Winget search failed for %s: %s", canonical, exc)
                continue
            if tags or publisher or package_id or titles_found:
                written += _write_signal(canonical, tags, publisher, package_id, titles_found)
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


def _search(
    client: httpx.Client, canonical: str
) -> tuple[list[str], str, str, list[str]]:
    """One package's tags/publisher/id, exact-name-matched -- or nothing.

    The old version unioned tags, publishers and package identifiers across
    every one of the top-5 search results into one row, on the theory that
    more data was more helpful. It wasn't: querying "01 transaction pro
    exporter 6.0" returned Chinese chat, video and shopping apps in the same
    top-5 batch (measured 2026-08-18, safety_signal), and their tags —
    "chat", "video", "taobao" — got stored as if they described the exporter.
    This is the same failure Chocolatey had (092: `Packages()` ignored its
    search term entirely; 1,473 rows carried one identical alphabetical
    tag set) wearing a different cause: here the endpoint *is* filtering by
    query, but "top 5 relevance matches" still isn't "the one right package."

    Exact match on the normalized package title (`Latest.Name`), same
    discipline as `chocolatey._search`: a fuzzy or top-N union cannot be
    trusted to describe the queried title rather than its neighbors in the
    search results, and no threshold was found (there, measured on 31 titles)
    that keeps the right matches without keeping the wrong ones too.
    """
    r = client.get(
        _SEARCH_ENDPOINT,
        params={"query": canonical[:120], "take": 5},
    )
    if r.status_code == 404:
        return [], "", "", []
    r.raise_for_status()
    body = r.json() or {}
    packages = body.get("Packages") or body.get("packages") or []
    if not isinstance(packages, list) or not packages:
        return [], "", "", []

    wanted = _normalize(canonical)
    titles_found: list[str] = []
    for pkg in packages:
        latest = pkg.get("Latest") or pkg.get("latest") or {}
        name = str(latest.get("Name") or "")
        if name:
            titles_found.append(name)
        if _normalize(name) == wanted:
            tags = sorted({str(t) for t in (latest.get("Tags") or []) if t})
            publisher = str(latest.get("Publisher") or "")
            package_id = str(pkg.get("Id") or "")
            return tags, publisher, package_id, titles_found
    return [], "", "", titles_found


def _write_signal(
    canonical: str, tags: list[str], publisher: str, package_id: str,
    titles_found: list[str],
) -> int:
    details = {
        "package_identifiers": [package_id] if package_id else [],
        "publishers": [publisher] if publisher else [],
        "tags": tags,
        "titles_found": titles_found,
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
