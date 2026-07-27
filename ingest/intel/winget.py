"""Winget enrichment via the community `winget.run` REST API.

Microsoft's own ``cdn.winget.microsoft.com/cache/api/manifestSearch``
endpoint returns 405 UnsupportedHttpVerb on POST from arbitrary
clients — that CDN is designed for the winget CLI, not third-party
callers. The community-run https://api.winget.run mirror serves the
same manifest data through a simple GET-friendly REST API with no
auth, so we use it as the enrichment source for tags and publisher.

Per-title queries against ``/v2/packages`` (search); one HTTPS GET per
canonical we've observed and don't already have a fresh signal for.
Results merge into ``operations.safety_signal`` as one aggregated row
per canonical (source='winget', signal_type='category').
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

_SEARCH_ENDPOINT = "https://api.winget.run/v2/packages"
_TENANT_ID = 1
_STALE_AFTER = timedelta(days=30)
_MAX_TITLES_PER_RUN = 500
_DELAY_SECONDS = 0.4
_USER_AGENT = "ninja-dashboard/intel-winget (+ops)"


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
                packages = _search(client, canonical)
            except httpx.HTTPError as exc:
                log.warning("Winget search failed for %s: %s", canonical, exc)
                continue
            if packages:
                written += _write_signal(canonical, packages)
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
    r = client.get(
        _SEARCH_ENDPOINT,
        params={"query": canonical[:120], "take": 5},
    )
    if r.status_code == 404:
        return []
    r.raise_for_status()
    body = r.json() or {}
    packages = body.get("Packages") or body.get("packages") or []
    return packages if isinstance(packages, list) else []


def _write_signal(canonical: str, packages: list[dict]) -> int:
    tags: set[str] = set()
    publishers: set[str] = set()
    package_ids: set[str] = set()
    for pkg in packages:
        latest = pkg.get("Latest") or pkg.get("latest") or {}
        pkg_meta = pkg.get("Metadata") or pkg
        for tag in (latest.get("Tags") or pkg_meta.get("Tags") or []):
            if tag:
                tags.add(str(tag))
        publisher = (
            latest.get("Publisher")
            or pkg_meta.get("Publisher")
            or ""
        )
        if publisher:
            publishers.add(str(publisher))
        pkg_id = pkg.get("Id") or pkg_meta.get("Id") or ""
        if pkg_id:
            package_ids.add(str(pkg_id))
    if not (tags or publishers or package_ids):
        return 0
    details = {
        "package_identifiers": sorted(package_ids),
        "publishers": sorted(publishers),
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
