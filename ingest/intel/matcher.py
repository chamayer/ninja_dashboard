"""Canonical software → CVE matcher.

Token-intersection heuristic per ADR 0008 (upgraded from the day-one
exact-only match):

  1. Split each canonical software name into lowercased alphanum tokens.
  2. For every (vendor, product) pair in ``intel.cpes``, mark it a
     high-confidence tier-1 hit when BOTH the vendor and the product
     token appear in the canonical's token set — e.g. "Google Chrome"
     tokens {"google","chrome"} intersects (vendor=google, product=chrome).
  3. As a fallback, tier-2 mediumconfidence hit when just a distinctive
     product token matches (>=4 chars, alphabetic, not in the generic
     stop list).
  4. Look up every CPE string for the matched (vendor, product) pairs,
     then use ``affected_cpes ?| %s::text[]`` on ``intel.cves`` — that
     operator is a single query per canonical and hits the jsonb GIN
     index cleanly.

Every run is a full refresh — stale rows are purged first so the table
always reflects the current fleet × current CPE dictionary.
"""

from __future__ import annotations

import logging
import re

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_TENANT_ID = 1
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_MIN_DISTINCTIVE_LEN = 4

_STOP_TOKENS: frozenset[str] = frozenset({
    "core", "sdk", "app", "apps", "tool", "tools", "server", "client",
    "service", "services", "utility", "utilities", "framework",
    "platform", "system", "windows", "linux", "mac", "runtime", "package",
    "installer", "manager", "console", "desktop", "web", "cloud",
    "shared", "common", "component", "components", "library", "libraries",
    "driver", "drivers", "user", "admin", "beta", "alpha", "preview",
    "engine", "assistant", "portable", "professional", "enterprise",
    "standard", "express", "starter", "basic", "advanced", "free",
    "trial", "demo", "update", "helper",
})


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
            "SELECT DISTINCT LOWER(vendor), LOWER(product) FROM intel.cpes"
        )
        vendor_product = [(v, p) for v, p in cur.fetchall() if v and p]

    if not titles or not vendor_product:
        with db.transaction() as cur:
            cur.execute(
                "DELETE FROM operations.cve_match WHERE tenant_id = %s",
                (_TENANT_ID,),
            )
        return 0

    products_by_vendor: dict[str, set[str]] = {}
    all_products: set[str] = set()
    for vendor, product in vendor_product:
        products_by_vendor.setdefault(vendor, set()).add(product)
        all_products.add(product)

    # Per canonical, compute the tier-1 (vendor,product) pairs and
    # tier-2 product-only hits, then look up matching CVEs in a single
    # jsonb query using the ?| operator (GIN-indexed on affected_cpes).
    total_rows = 0
    with db.transaction() as cur:
        cur.execute(
            "DELETE FROM operations.cve_match WHERE tenant_id = %s",
            (_TENANT_ID,),
        )
        for canonical in titles:
            tokens = {t for t in _TOKEN_SPLIT_RE.split(canonical.lower()) if t}
            if not tokens:
                continue

            tier1_pairs: set[tuple[str, str]] = set()
            for vendor in tokens & products_by_vendor.keys():
                hits = products_by_vendor[vendor] & tokens
                for product in hits:
                    tier1_pairs.add((vendor, product))

            tier2_products: set[str] = set()
            if not tier1_pairs:
                for token in tokens:
                    if (
                        token not in _STOP_TOKENS
                        and len(token) >= _MIN_DISTINCTIVE_LEN
                        and any(c.isalpha() for c in token)
                        and token in all_products
                    ):
                        tier2_products.add(token)
                        if len(tier2_products) >= 3:
                            break

            if not tier1_pairs and not tier2_products:
                continue

            # Gather the actual CPE strings for the tier-1 and tier-2 hits.
            cpe_candidates: list[str] = []
            if tier1_pairs:
                # Concat vendor + '|' + product for cheap ANY(...) match
                # against the CPE index. Character '|' is not permitted
                # in CPE vendor/product identifiers, so no ambiguity.
                keys = [f"{v}|{p}" for v, p in tier1_pairs]
                cur.execute(
                    """
                    SELECT cpe23 FROM intel.cpes
                     WHERE (LOWER(vendor) || '|' || LOWER(product)) = ANY(%s::text[])
                    """,
                    (keys,),
                )
                cpe_candidates.extend(row[0] for row in cur.fetchall())
            if tier2_products:
                cur.execute(
                    """
                    SELECT cpe23 FROM intel.cpes
                     WHERE LOWER(product) = ANY(%s::text[])
                     LIMIT 500
                    """,
                    (list(tier2_products),),
                )
                cpe_candidates.extend(row[0] for row in cur.fetchall())
            cpe_candidates = list({c for c in cpe_candidates if c})
            if not cpe_candidates:
                continue

            cur.execute(
                """
                SELECT cve_id
                  FROM intel.cves
                 WHERE affected_cpes ?| %s::text[]
                """,
                (cpe_candidates,),
            )
            cve_ids = [row[0] for row in cur.fetchall()]
            if not cve_ids:
                continue

            confidence = "high" if tier1_pairs else "medium"
            kind = "cpe_exact" if tier1_pairs else "cpe_product_only"
            rows = [
                (_TENANT_ID, canonical, cve_id, kind, confidence)
                for cve_id in cve_ids
            ]
            cur.executemany(
                """
                INSERT INTO operations.cve_match (
                    tenant_id, canonical_name, cve_id, match_kind, confidence
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, canonical_name, cve_id, match_kind)
                DO NOTHING
                """,
                rows,
            )
            total_rows += len(rows)
    return total_rows
