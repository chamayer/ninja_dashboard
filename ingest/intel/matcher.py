"""Canonical software → CVE matcher.

Precision knobs are data-driven (``operations.intel_matcher_hints``):

  * ``require_third_token`` — for the vendors listed there (Microsoft,
    Adobe, Google, Oracle, IBM, Cisco, VMware, Citrix by default),
    the canonical name must carry a distinctive third token beyond
    ``vendor + product`` before a tier-1 hit fires. Blocks
    "Microsoft Office Shared MUI" from inheriting every Office CVE.
  * ``ignore_sub_component`` — regex patterns for support / language /
    proofing / redistributable sub-components that skip CVE matching
    entirely; their risk is inherited from the parent product's
    publisher-scope decision.

Additional built-ins:

  * Version awareness: matching is per **product+version**, not per
    title. The installed version from ``catalog.software_versions``
    supplies progressive prefixes (``3.13.2`` -> ``3.13`` -> ``3``),
    combined with any year (2010..2035) or semver token parsed from
    the canonical name itself ("Office 2010", whose installed version
    is an unrelated ``14.0.x``). Matches carry the resolved
    ``software_version_id``.

    Version-agnostic CPEs (``version`` of ``*``, ``-`` or absent) are
    emitted once per title with ``software_version_id`` NULL. That is a
    genuine product-level claim, not an unknown version -- a CVE with no
    version constraint really does affect every release.

    Before this, the version filter was parsed only from the title text
    and then *discarded* at INSERT, so every device running any version
    of a matched product was flagged identically, patched ones included
    (ADR-0008 amendment 2026-08-06; ADR-0012 s5 governs).
  * Publisher-alias resolution runs implicitly through the matview /
    scoring layer, not the matcher — the matcher's job is only to
    fill ``operations.cve_match``.

Every run is a full refresh (``DELETE tenant + INSERT``) and ends by
issuing ``REFRESH MATERIALIZED VIEW operations.v_software_safety`` so
the software pages see fresh scores immediately.
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
_VERSION_YEAR_RE = re.compile(r"\b(20[1-3][0-9])\b")
_VERSION_SEMVER_RE = re.compile(r"\b(\d+(?:\.\d+){1,3})\b")

_STOP_TOKENS: frozenset[str] = frozenset({
    "core", "sdk", "app", "apps", "tool", "tools", "server", "client",
    "service", "services", "utility", "utilities", "framework",
    "platform", "system", "windows", "linux", "mac", "runtime", "package",
    "installer", "manager", "console", "desktop", "web", "cloud",
    "shared", "common", "component", "components", "library", "libraries",
    "driver", "drivers", "user", "admin", "beta", "alpha", "preview",
    "engine", "assistant", "portable", "professional", "enterprise",
    "standard", "express", "starter", "basic", "advanced", "free",
    "trial", "demo", "update", "helper", "microsoft", "google", "adobe",
    "oracle", "ibm", "cisco", "vmware", "citrix",
})


def run_once() -> int:
    if not settings.INTEL_ENABLED:
        log.info("Intel matcher disabled by flag; skipping")
        return 0
    with record_run("matcher") as state:
        rows = _match_and_upsert()
        state["rows_touched"] = rows
        state["notes"] = f"Refreshed {rows} cve_match rows."
        # Refresh the materialised view so the software UI reflects the
        # new match set immediately. Non-concurrent refresh — the view
        # is small enough that a full rebuild is cheap and doesn't
        # require the unique index to be present ahead of time.
        try:
            with db.transaction() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW operations.v_software_safety")
            log.info("Refreshed operations.v_software_safety matview")
        except Exception:
            log.exception("Failed to refresh v_software_safety matview")
        return rows


def _load_hints() -> tuple[set[str], list[re.Pattern]]:
    """Return (`require_third_token vendors`, `ignore-sub-component regexes`)."""
    third_token_vendors: set[str] = set()
    ignore_patterns: list[re.Pattern] = []
    try:
        with db.transaction() as cur:
            cur.execute(
                "SELECT kind, pattern FROM operations.intel_matcher_hints"
                " WHERE enabled = TRUE"
            )
            for kind, pattern in cur.fetchall():
                if kind == "require_third_token":
                    third_token_vendors.add(pattern.strip().lower())
                elif kind == "ignore_sub_component":
                    try:
                        ignore_patterns.append(re.compile(pattern))
                    except re.error:
                        log.warning("Bad ignore_sub_component regex: %s", pattern)
    except Exception:
        log.exception("Failed to load matcher hints; using empty set")
    return third_token_vendors, ignore_patterns


def _parse_version_prefixes(canonical: str) -> list[str]:
    """Return a list of version-string prefixes to filter CPE candidates.

    Prefers year (Office 2010, LTSC 2024) over semver (10.1.2).
    Returns an empty list when no version token is parseable; the
    matcher then keeps all CPE candidates for the product.
    """
    prefixes: list[str] = []
    year_hits = _VERSION_YEAR_RE.findall(canonical)
    if year_hits:
        prefixes.extend(year_hits[:2])  # most-specific two
    semver_hits = _VERSION_SEMVER_RE.findall(canonical)
    for v in semver_hits[:2]:
        # Take the major (or major.minor) prefix; sub-versions rarely
        # line up between canonical inventory and CPE tuples.
        parts = v.split(".")
        if parts[0].isdigit():
            prefixes.append(parts[0])
            if len(parts) > 1 and parts[1].isdigit():
                prefixes.append(f"{parts[0]}.{parts[1]}")
    # Dedupe while preserving order.
    seen: set[str] = set()
    return [p for p in prefixes if not (p in seen or seen.add(p))]


_INSERT_MATCH = """
    INSERT INTO operations.cve_match (
        tenant_id, canonical_name, software_version_id, cve_id,
        match_kind, version_range, confidence
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (tenant_id, canonical_name, software_version_id,
                 cve_id, match_kind) DO NOTHING
"""


def _cves_for(
    cur, cpe_candidates: list[str], cache: dict[tuple[str, ...], list[str]]
) -> list[str]:
    """CVE ids affecting any of ``cpe_candidates``, memoised on the candidate
    set. Sibling versions of one title often produce an identical set."""
    key = tuple(cpe_candidates)
    hit = cache.get(key)
    if hit is not None:
        return hit
    cur.execute(
        """
        SELECT cve_id
          FROM intel.cves
         WHERE affected_cpes ?| %s::text[]
        """,
        (cpe_candidates,),
    )
    found = [row[0] for row in cur.fetchall()]
    cache[key] = found
    return found


def _version_prefixes(version: str) -> list[str]:
    """Progressive prefixes of an *installed* version string.

    '3.13.2' -> ['3.13.2', '3.13', '3']. Most specific first, so a CPE for
    3.13.2 is preferred over one for the whole 3.x line when both exist in the
    candidate pool -- though both match, since a CVE against 3.x does affect
    3.13.2.

    This is the half that was missing: ``_parse_version_prefixes`` reads the
    *title text* ("Office 2010"), which is all the matcher had before the
    catalogue gave installations a version identity.
    """
    v = (version or "").strip()
    if not v:
        return []
    parts = [p for p in v.split(".") if p != ""]
    if not parts or not parts[0].isdigit():
        return []
    out: list[str] = []
    for i in range(len(parts), 0, -1):
        out.append(".".join(parts[:i]))
    return out


def _match_and_upsert() -> int:
    third_token_vendors, ignore_patterns = _load_hints()

    with db.transaction() as cur:
        # Unit of work is the installed product+version, not the bare title.
        # ADR-0012 s5 binds CVEs to software+version, and the ADR-0008
        # amendment of 2026-08-06 records what title scope cost: every device
        # running any version of a matched product was flagged identically,
        # including patched ones. `software_version_id` is 100% populated on
        # installations (489,347/489,347 measured 2026-08-10), so the catalogue
        # join loses no installation.
        cur.execute(
            """
            SELECT DISTINCT p.canonical_name, sv.id, sv.version
            FROM operations.software_installations_current sic
            JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
            JOIN catalog.products p           ON p.id  = sv.product_id
            WHERE sic.tenant_id = %s
              AND sic.deleted_at IS NULL
              AND sic.stale_since IS NULL
              AND sic.software_version_id IS NOT NULL
              AND p.canonical_name <> ''
            """,
            (_TENANT_ID,),
        )
        # canonical -> [(software_version_id, version_string), ...]
        installed: dict[str, list[tuple[int, str]]] = {}
        for canonical, version_id, version in cur.fetchall():
            installed.setdefault(canonical, []).append((version_id, version or ""))
        titles = list(installed)

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

    total_rows = 0
    matched_titles = 0
    matched_versions = 0
    ignored_titles = 0
    # CVE lookups are keyed by the exact CPE candidate set, and sibling
    # versions of one title frequently resolve to the same set. Without this
    # the move from title to product+version would roughly double the query
    # count against intel.cves for no new information.
    cve_cache: dict[tuple[str, ...], list[str]] = {}
    with db.transaction() as cur:
        cur.execute(
            "DELETE FROM operations.cve_match WHERE tenant_id = %s",
            (_TENANT_ID,),
        )
        for canonical in titles:
            # Sub-component skip.
            if any(rx.search(canonical) for rx in ignore_patterns):
                ignored_titles += 1
                continue

            tokens = {t for t in _TOKEN_SPLIT_RE.split(canonical.lower()) if t}
            if not tokens:
                continue
            version_prefixes = _parse_version_prefixes(canonical)

            tier1_pairs: set[tuple[str, str]] = set()
            for vendor in tokens & products_by_vendor.keys():
                # Require-third-token gate for noisy vendors.
                if vendor in third_token_vendors:
                    distinctive = {
                        t for t in tokens
                        if t != vendor and t not in _STOP_TOKENS
                        and len(t) >= _MIN_DISTINCTIVE_LEN
                        and any(c.isalpha() for c in t)
                    }
                    if not distinctive:
                        continue
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

            # Fetch the CPE candidate pool once per title, unfiltered. The
            # version filter is applied per installed version below, so
            # filtering here would throw away the rows other versions need.
            cpe_rows: list[tuple[str, str | None]] = []
            if tier1_pairs:
                keys = [f"{v}|{p}" for v, p in tier1_pairs]
                cur.execute(
                    """
                    SELECT cpe23, version FROM intel.cpes
                     WHERE (LOWER(vendor) || '|' || LOWER(product)) = ANY(%s::text[])
                    """,
                    (keys,),
                )
                cpe_rows.extend(cur.fetchall())
            if tier2_products:
                cur.execute(
                    """
                    SELECT cpe23, version FROM intel.cpes
                     WHERE LOWER(product) = ANY(%s::text[])
                     LIMIT 500
                    """,
                    (list(tier2_products),),
                )
                cpe_rows.extend(cur.fetchall())
            if not cpe_rows:
                continue

            confidence = "high" if tier1_pairs else "medium"
            kind = "cpe_exact" if tier1_pairs else "cpe_product_only"
            title_matched = False

            # Version-agnostic CPEs ('*', '-', empty, NULL) genuinely apply to
            # every release, so they stay product-level: software_version_id
            # NULL. That is an assertion about the product, not a missing
            # version -- see the column comment in migration 077. Emitted once
            # per title, deduplicated by the NULLS NOT DISTINCT unique index.
            agnostic = sorted({
                cpe23 for cpe23, ver in cpe_rows
                if cpe23 and (ver is None or ver.strip() in ("", "*", "-"))
            })
            if agnostic:
                cve_ids = _cves_for(cur, agnostic, cve_cache)
                if cve_ids:
                    cur.executemany(_INSERT_MATCH, [
                        (_TENANT_ID, canonical, None, cve_id, kind, "*", confidence)
                        for cve_id in cve_ids
                    ])
                    total_rows += len(cve_ids)
                    title_matched = True

            # Then each installed version against the version-specific CPEs.
            for version_id, version in installed[canonical]:
                prefixes = _version_prefixes(version) + version_prefixes
                if not prefixes:
                    # Nothing to narrow by: the installed version is empty and
                    # the title carries no version token. Anything more than the
                    # product-level rows above would be a guess.
                    continue
                specific = sorted({
                    cpe23 for cpe23, ver in cpe_rows
                    if cpe23 and ver is not None
                    and ver.strip() not in ("", "*", "-")
                    and any(ver.strip().startswith(p) for p in prefixes)
                })
                if not specific:
                    continue
                cve_ids = _cves_for(cur, specific, cve_cache)
                if not cve_ids:
                    continue
                cur.executemany(_INSERT_MATCH, [
                    (_TENANT_ID, canonical, version_id, cve_id, kind,
                     version or "", confidence)
                    for cve_id in cve_ids
                ])
                total_rows += len(cve_ids)
                matched_versions += 1
                title_matched = True

            if title_matched:
                matched_titles += 1

    log.info(
        "Intel matcher: %d titles matched (%d product+version pairs), "
        "%d sub-components ignored, %d cve_match rows.",
        matched_titles, matched_versions, ignored_titles, total_rows,
    )
    return total_rows


def _filter_by_version_prefix(
    rows: list[tuple[str, str | None]], prefixes: list[str]
) -> list[str]:
    """Keep CPEs whose ``version`` starts with any of ``prefixes`` OR
    whose version is version-agnostic (None / '*' / '-'). When no
    prefixes are given, keep everything."""
    if not prefixes:
        return [r[0] for r in rows]
    out: list[str] = []
    for cpe23, version in rows:
        if version is None:
            out.append(cpe23)
            continue
        v = version.strip()
        if v in ("", "*", "-"):
            out.append(cpe23)
            continue
        if any(v.startswith(p) for p in prefixes):
            out.append(cpe23)
    return out
