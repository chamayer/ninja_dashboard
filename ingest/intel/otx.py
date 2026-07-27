"""AlienVault OTX pulse ingest → operations.safety_signal.

Pulls recently modified subscribed pulses via the free OTX API,
extracts indicators + tags, and stores rows keyed by any indicator
matching a canonical software name or publisher we already track.

The signal is deliberately weak (`severity='info'` by default) because
OTX pulses are community-curated and noisy — the scorer decides how
much weight to give them.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_ENDPOINT = "https://otx.alienvault.com/api/v1/pulses/subscribed"
_LOOKBACK_DAYS = 7
_MAX_PAGES = 20
_PAGE_LIMIT = 50


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_OTX_ENABLED):
        log.info("OTX ingest disabled by flag; skipping")
        return 0
    key = settings.OTX_API_KEY.get_secret_value().strip()
    if not key:
        log.warning("OTX_API_KEY not configured; skipping OTX ingest")
        return 0
    with record_run("otx") as state:
        rows = _pull_and_upsert(key)
        state["rows_touched"] = rows
        state["notes"] = f"OTX signals: {rows} rows."
        return rows


def _pull_and_upsert(api_key: str) -> int:
    canonicals, publishers = _tracked_names()
    if not canonicals and not publishers:
        return 0
    modified_since = (datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    headers = {"X-OTX-API-KEY": api_key}
    matched: list[tuple] = []
    with httpx.Client(timeout=30.0, headers=headers) as client:
        for page in range(1, _MAX_PAGES + 1):
            r = client.get(
                _ENDPOINT,
                params={
                    "limit": _PAGE_LIMIT,
                    "page": page,
                    "modified_since": modified_since,
                },
            )
            if r.status_code == 401:
                log.warning("OTX auth rejected; check OTX_API_KEY")
                break
            if r.status_code == 429:
                log.warning("OTX rate-limited; stopping run")
                break
            r.raise_for_status()
            payload = r.json() or {}
            results = payload.get("results") or []
            if not results:
                break
            matched.extend(_match_pulses(results, canonicals, publishers))
            if not payload.get("next"):
                break
    if not matched:
        return 0
    with db.transaction() as cur:
        cur.executemany(
            """
            INSERT INTO operations.safety_signal (
                tenant_id, canonical_name, publisher, source,
                signal_type, severity, details
            ) VALUES (%s, %s, %s, 'otx', 'threat_hit', 'low', %s::jsonb)
            ON CONFLICT (tenant_id, LOWER(canonical_name), LOWER(publisher), source, signal_type)
            DO UPDATE SET
                details = EXCLUDED.details,
                observed_at = now()
            """,
            matched,
        )
    return len(matched)


def _tracked_names() -> tuple[set[str], set[str]]:
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT DISTINCT LOWER(canonical_name), LOWER(COALESCE(publisher, ''))
            FROM operations.software_installations_current
            WHERE tenant_id = 1
              AND deleted_at IS NULL AND stale_since IS NULL
              AND canonical_name <> ''
            """
        )
        canonicals: set[str] = set()
        publishers: set[str] = set()
        for c, p in cur.fetchall():
            if c:
                canonicals.add(c)
            if p:
                publishers.add(p)
        return canonicals, publishers


def _match_pulses(
    results: list[dict], canonicals: set[str], publishers: set[str]
) -> list[tuple]:
    matched: list[tuple] = []
    for pulse in results:
        pulse_name = (pulse.get("name") or "").lower()
        tags = [t.lower() for t in (pulse.get("tags") or [])]
        indicator_text = " ".join(
            (i.get("indicator") or "").lower()
            for i in (pulse.get("indicators") or [])
        )
        haystack = f"{pulse_name} {' '.join(tags)} {indicator_text}"
        for canonical in canonicals:
            if canonical and canonical in haystack:
                matched.append((
                    1, canonical, "",
                    json.dumps({
                        "pulse_name": pulse.get("name"),
                        "pulse_id": pulse.get("id"),
                        "tags": tags,
                    }),
                ))
                break
        for publisher in publishers:
            if publisher and publisher in haystack:
                matched.append((
                    1, "", publisher,
                    json.dumps({
                        "pulse_name": pulse.get("name"),
                        "pulse_id": pulse.get("id"),
                        "tags": tags,
                    }),
                ))
                break
    return matched
