"""Canonical software → CVE matcher.

Conservative day-one implementation per ADR 0008:

  * ``cpe_exact``   — canonical_name normalised → intel.cpes.product
                      (single token; ignores version). High confidence.
  * ``cpe_wildcard`` — canonical_name matches a CVE whose affected_cpes
                       carry a ``*`` version wildcard. Medium confidence.

Rows are upserted into ``operations.cve_match``. Stale rows (canonical
no longer installed, or CPE no longer matches) are purged on each run so
the table remains a projection of the current fleet.
"""

from __future__ import annotations

import logging
import re

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_TENANT_ID = 1
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


def run_once() -> int:
    if not settings.INTEL_ENABLED:
        log.info("Intel matcher disabled by flag; skipping")
        return 0
    with record_run("matcher") as state:
        rows = _match_and_upsert()
        state["rows_touched"] = rows
        state["notes"] = f"Refreshed {rows} cve_match rows."
        return rows


def _match_and_upsert() -> int:
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT DISTINCT canonical_name
            FROM operations.software_installations_current
            WHERE tenant_id = %s
              AND deleted_at IS NULL
              AND stale_since IS NULL
              AND canonical_name <> ''
            """,
            (_TENANT_ID,),
        )
        titles = [row[0] for row in cur.fetchall()]

        cur.execute(
            "SELECT LOWER(vendor), LOWER(product), cpe23 FROM intel.cpes"
        )
        cpe_rows = cur.fetchall()

    product_to_cpes: dict[str, list[str]] = {}
    for _vendor, product, cpe23 in cpe_rows:
        product_to_cpes.setdefault(product, []).append(cpe23)

    matches: list[tuple] = []
    with db.transaction() as cur:
        for canonical in titles:
            token = _normalise(canonical)
            if not token:
                continue
            candidates = product_to_cpes.get(token, [])
            if not candidates:
                continue
            cur.execute(
                """
                SELECT cve_id
                FROM intel.cves
                WHERE affected_cpes ?| %s::text[]
                """,
                (candidates,),
            )
            for (cve_id,) in cur.fetchall():
                matches.append((_TENANT_ID, canonical, cve_id, "cpe_exact", "high"))

    with db.transaction() as cur:
        cur.execute(
            "DELETE FROM operations.cve_match WHERE tenant_id = %s",
            (_TENANT_ID,),
        )
        if matches:
            cur.executemany(
                """
                INSERT INTO operations.cve_match (
                    tenant_id, canonical_name, cve_id, match_kind, confidence
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, canonical_name, cve_id, match_kind)
                DO NOTHING
                """,
                matches,
            )
    return len(matches)


def _normalise(name: str) -> str:
    return _NORMALISE_RE.sub("", (name or "").lower())
