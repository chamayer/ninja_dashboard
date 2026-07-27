"""abuse.ch MalwareBazaar + ThreatFox dump-file ingest → safety_signal.

Following the abuse.ch 2026-07 fair-use notice, we pull the recent
dump files (single HTTPS GET each) instead of hammering the API. Both
give per-hash records with signer subjects, filenames, and family tags.
We match on publisher (signer_subject) and canonical filename tokens
against our fleet.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_MB_RECENT = "https://bazaar.abuse.ch/export/json/recent/"
_TF_RECENT = "https://threatfox.abuse.ch/export/json/recent/"


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_ABUSECH_ENABLED):
        log.info("abuse.ch ingest disabled by flag; skipping")
        return 0
    with record_run("abusech") as state:
        mb = _pull_bazaar()
        tf = _pull_threatfox()
        total = mb + tf
        state["rows_touched"] = total
        state["notes"] = f"MalwareBazaar: {mb}, ThreatFox: {tf}"
        return total


def _pull_bazaar() -> int:
    entries = _fetch_json(_MB_RECENT)
    if not entries:
        return 0
    canonicals, publishers = _tracked_names()
    matched: list[tuple] = []
    for entry_list in entries.values():
        for entry in _iter(entry_list):
            signer = _lc(entry.get("signature") or entry.get("code_sign", ""))
            filename = _lc(entry.get("file_name", ""))
            tags = [str(t) for t in (entry.get("tags") or [])]
            if signer and signer in publishers:
                matched.append((
                    1, "", signer, "malwarebazaar",
                    json.dumps({
                        "signature": entry.get("signature"),
                        "family": entry.get("signature"),
                        "tags": tags,
                        "sha256": entry.get("sha256_hash"),
                    }),
                ))
            for c in canonicals:
                if c and filename and c in filename:
                    matched.append((
                        1, c, "", "malwarebazaar",
                        json.dumps({
                            "file_name": entry.get("file_name"),
                            "tags": tags,
                            "sha256": entry.get("sha256_hash"),
                        }),
                    ))
                    break
    return _upsert_rows(matched)


def _pull_threatfox() -> int:
    entries = _fetch_json(_TF_RECENT)
    if not entries:
        return 0
    canonicals, publishers = _tracked_names()
    matched: list[tuple] = []
    for entry_list in entries.values():
        for entry in _iter(entry_list):
            ioc = _lc(entry.get("ioc_value", ""))
            tags = entry.get("tags") or []
            malware = _lc(entry.get("malware_printable", ""))
            for c in canonicals:
                if c and ioc and c in ioc:
                    matched.append((
                        1, c, "", "threatfox",
                        json.dumps({
                            "ioc": entry.get("ioc_value"),
                            "malware": entry.get("malware_printable"),
                            "tags": tags,
                        }),
                    ))
                    break
            for p in publishers:
                if p and malware and p in malware:
                    matched.append((
                        1, "", p, "threatfox",
                        json.dumps({
                            "malware": entry.get("malware_printable"),
                            "tags": tags,
                        }),
                    ))
                    break
    return _upsert_rows(matched)


def _fetch_json(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=60.0) as client:
        r = client.get(url)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        try:
            return r.json()
        except json.JSONDecodeError:
            return {}


def _iter(value: Any):
    if isinstance(value, list):
        yield from value
    elif isinstance(value, dict):
        yield value


def _lc(v: Any) -> str:
    return str(v or "").lower()


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


def _upsert_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    with db.transaction() as cur:
        cur.executemany(
            """
            INSERT INTO operations.safety_signal (
                tenant_id, canonical_name, publisher, source,
                signal_type, severity, details
            ) VALUES (%s, %s, %s, %s, 'threat_hit', 'medium', %s::jsonb)
            ON CONFLICT (tenant_id, LOWER(canonical_name), LOWER(publisher), source, signal_type)
            DO UPDATE SET
                details = EXCLUDED.details,
                observed_at = now()
            """,
            rows,
        )
    return len(rows)
