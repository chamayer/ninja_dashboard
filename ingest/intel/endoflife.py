"""End-of-life corpus ingest from endoflife.date -> intel.eol_products /
intel.eol_releases.

This is the producer `eol_runtime` never had. Measured 2026-08-10: 0 of 40,541
`catalog.software_versions` rows carried an `eol_date`, and none of the eight
registered intel connectors carries lifecycle data, so the finding fired on a
title regex ("matches end-of-life runtime pattern") and asserted nothing about
the installed release.

**API v1, not the legacy endpoint.** `/api/{product}.json` overloads a single
`eol` field as either an ISO date string or a bare boolean depending on the
product, which cannot be stored in a date column without losing one case or the
other. `/api/v1/products/{name}` splits it into `isEol` (boolean) and `eolFrom`
(date or null), so both facts survive. Verified against the live API
2026-08-10, schema_version 1.2.1, 462 products.

No auth and no documented rate limit, so requests are paced anyway -- 462
product calls per full refresh is small, but a free community corpus deserves
the same courtesy the winget connector already extends to api.winget.run.

This module only fetches. Deciding which of *our* titles a corpus product
corresponds to is a separate step driven by `operations.eol_product_map`
(ADR-0012 section 6: mappings live in data), so a matching fix never re-fetches
the corpus and a corpus refresh never re-decides matching.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime

import httpx

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_INDEX_ENDPOINT = "https://endoflife.date/api/v1/products"
_PRODUCT_ENDPOINT = "https://endoflife.date/api/v1/products/{name}"
_DELAY_SECONDS = 0.25
_TIMEOUT = 30.0
_USER_AGENT = "ninja-dashboard/intel-endoflife (+ops)"


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_ENDOFLIFE_ENABLED):
        log.info("End-of-life ingest disabled by flag; skipping")
        return 0
    with record_run("endoflife") as state:
        products, releases = _pull_and_upsert()
        state["rows_touched"] = products + releases
        state["notes"] = f"Upserted {products} products, {releases} releases."
        return products + releases


def _pull_and_upsert() -> tuple[int, int]:
    headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    product_rows = 0
    release_rows = 0
    failed: list[str] = []

    with httpx.Client(timeout=_TIMEOUT, headers=headers) as client:
        index = _fetch(client, _INDEX_ENDPOINT)
        entries = (index or {}).get("result") or []
        if not entries:
            # Never treat an empty index as "the corpus is empty" -- that would
            # silently expire every EOL date we hold on the next projection.
            raise RuntimeError(
                "endoflife.date index returned no products; refusing to treat "
                "as an empty corpus"
            )
        log.info("End-of-life index: %d products", len(entries))

        product_rows = _upsert_products(entries)

        for entry in entries:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            time.sleep(_DELAY_SECONDS)
            try:
                payload = _fetch(client, _PRODUCT_ENDPOINT.format(name=name))
            except Exception:
                # One bad product must not lose the other 461. Recorded and
                # counted rather than swallowed.
                log.warning("End-of-life: product %s failed; skipping", name)
                failed.append(name)
                continue
            releases = ((payload or {}).get("result") or {}).get("releases") or []
            release_rows += _upsert_releases(name, releases)

    if failed:
        log.warning(
            "End-of-life: %d product(s) failed this run: %s",
            len(failed), ", ".join(sorted(failed)[:20]),
        )
    log.info(
        "End-of-life ingest: %d products, %d releases, %d failed.",
        product_rows, release_rows, len(failed),
    )
    return product_rows, release_rows


def _fetch(client: httpx.Client, url: str) -> dict:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.json()


def _upsert_products(entries: list[dict]) -> int:
    rows = []
    for e in entries:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        rows.append((
            name,
            (e.get("label") or "").strip(),
            (e.get("category") or "").strip(),
            json.dumps(e.get("aliases") or []),
            json.dumps(e.get("tags") or []),
        ))
    if not rows:
        return 0
    with db.transaction() as cur:
        cur.executemany(
            """
            INSERT INTO intel.eol_products
                (name, label, category, aliases, tags, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, now())
            ON CONFLICT (name) DO UPDATE SET
                label      = EXCLUDED.label,
                category   = EXCLUDED.category,
                aliases    = EXCLUDED.aliases,
                tags       = EXCLUDED.tags,
                updated_at = now()
            """,
            rows,
        )
    return len(rows)


def _upsert_releases(product_name: str, releases: list[dict]) -> int:
    rows = []
    for r in releases:
        cycle = (r.get("name") or "").strip()
        if not cycle:
            continue
        rows.append((
            product_name,
            cycle,
            (r.get("label") or "").strip(),
            _as_date(r.get("releaseDate")),
            _as_date(r.get("eolFrom")),
            bool(r.get("isEol")),
            bool(r.get("isMaintained", True)),
            bool(r.get("isLts")),
            _latest_name(r.get("latest")),
        ))
    if not rows:
        return 0
    with db.transaction() as cur:
        cur.executemany(
            """
            INSERT INTO intel.eol_releases
                (product_name, cycle, label, release_date, eol_from,
                 is_eol, is_maintained, is_lts, latest_version, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (product_name, cycle) DO UPDATE SET
                label          = EXCLUDED.label,
                release_date   = EXCLUDED.release_date,
                eol_from       = EXCLUDED.eol_from,
                is_eol         = EXCLUDED.is_eol,
                is_maintained  = EXCLUDED.is_maintained,
                is_lts         = EXCLUDED.is_lts,
                latest_version = EXCLUDED.latest_version,
                updated_at     = now()
            """,
            rows,
        )
    return len(rows)


def _as_date(value: object) -> date | None:
    """endoflife.date v1 gives ISO dates or null. It does *not* put booleans in
    the date fields -- that was the legacy endpoint's `eol` -- but a boolean is
    rejected explicitly rather than allowed to become a surprise later."""
    if value is None or isinstance(value, bool) or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        log.warning("End-of-life: unparseable date %r", value)
        return None


def _latest_name(value: object) -> str:
    """`latest` is an object ({name, date, link}) in v1 and a bare string in the
    legacy API. Accept both so a schema_version bump does not silently blank the
    column."""
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    if isinstance(value, str):
        return value.strip()
    return ""
