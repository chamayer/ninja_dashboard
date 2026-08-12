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

_ENDPOINT = "https://community.chocolatey.org/api/v2/Search()"
_TENANT_ID = 1
_STALE_AFTER = timedelta(days=30)
_MAX_TITLES_PER_RUN = 500
_DELAY_SECONDS = 0.5

_ENTRY_ELEMENT = re.compile(r"<entry[\s>].*?</entry>", re.S)
_TAG_ELEMENT = re.compile(r"<d:Tags[^>]*>(.*?)</d:Tags>", re.S)
_TITLE_ELEMENT = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


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
            SELECT sic.canonical_name
            FROM operations.software_installations_current sic
            LEFT JOIN latest_signal ls ON ls.canonical = LOWER(sic.canonical_name)
            WHERE sic.tenant_id = %s
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND sic.canonical_name <> ''
              AND (ls.observed_at IS NULL OR ls.observed_at < %s)
            GROUP BY sic.canonical_name
            -- Most-installed first, not alphabetical. Each run is capped at
            -- _MAX_TITLES_PER_RUN, so the ordering decides what the cap buys.
            -- Alphabetical spent a whole run on '. .', '1.1.3.4' and
            -- '4500_help': measured 2026-08-12, ~225 titles processed for 8
            -- writes, a 3.5% hit rate, while the 544 titles that carry 73% of
            -- the fleet's installs sat untouched behind the digits.
            ORDER BY COUNT(DISTINCT sic.device_id) DESC, sic.canonical_name
            """,
            (_TENANT_ID, _TENANT_ID, datetime.now(timezone.utc) - _STALE_AFTER),
        )
        return [row[0] for row in cur.fetchall()]


def _normalise(value: str) -> str:
    return _NORMALISE_RE.sub("", value.lower())


def _search(client: httpx.Client, canonical: str) -> tuple[list[str], list[str]]:
    # `Search()`, not `Packages()`. `searchTerm` is a parameter of the Search
    # function; `Packages()` accepts the query string, ignores the term, and
    # returns HTTP 200 with the unfiltered first page of the gallery. That is
    # what this connector did for its whole life -- every enriched title got
    # the alphabetically-first packages' tags, which is why all 1,473 stored
    # rows carried one identical 22-tag set beginning "0install, 1c, 1c83".
    # Search() additionally requires targetFramework and includePrerelease;
    # omitting them returns HTTP 400.
    #
    # OData wants ``searchTerm='...'`` quoted and ``$``-prefixed keys raw.
    # httpx URL-encodes params too aggressively for OData, so hand-assemble.
    from urllib.parse import quote
    quoted = quote(canonical[:120].replace("'", ""), safe="")
    url = (
        f"{_ENDPOINT}?searchTerm=%27{quoted}%27"
        "&targetFramework=%27%27"
        "&includePrerelease=false"
        "&$filter=IsLatestVersion"
        "&$top=5"
    )
    r = client.get(url)
    if r.status_code == 404:
        return [], []
    r.raise_for_status()

    # Per entry, never unioned across the response. Tags describe one package;
    # merging five results' tags produces a set that describes none of them.
    entries: list[tuple[str, list[str]]] = []
    for block in _ENTRY_ELEMENT.findall(r.text):
        title_match = _TITLE_ELEMENT.search(block)
        title = title_match.group(1).strip() if title_match else ""
        tag_match = _TAG_ELEMENT.search(block)
        tags = [t for t in re.split(r"\s+", tag_match.group(1).strip())] if tag_match else []
        entries.append((title, [t for t in tags if t]))
    if not entries:
        return [], []

    # Exact normalised match only. No relevance fallback, no similarity
    # threshold: both were measured against 31 real titles on 2026-08-12 and
    # neither separates right from wrong here.
    #
    #   1.1.3.4                -> dotnetcore-3.1-sdk-4xx   ratio 0.18  WRONG
    #   3utools                -> yuanliao-utools          ratio 0.57  WRONG
    #   microsoft edge update  -> microsoft-edge-insider   ratio 0.71  WRONG
    #   25415inkscape.inkscape -> InkScape                 ratio 0.55  right
    #
    # The one correct fuzzy match scores *below* the worst wrong one, so any
    # threshold that rejects the errors also rejects it. At 0.75+ the fuzzy
    # path accepts exactly what exact matching accepts and nothing more.
    # Writing nothing is the honest outcome: an unmatched title is a title
    # Chocolatey does not carry, which is a fact worth preserving rather than
    # papering over with the gallery's nearest guess.
    wanted = _normalise(canonical)
    match = next((e for e in entries if _normalise(e[0]) == wanted), None)
    if match is None:
        return [], [t for t, _ in entries if t]
    return sorted(set(match[1])), [t for t, _ in entries if t]


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
