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

Every run recomputes the full desired set and persists only its differences,
preserving existing IDs and timestamps when match content is unchanged. It ends by
issuing ``REFRESH MATERIALIZED VIEW operations.v_software_safety`` so
the software pages see fresh scores immediately.

Cost, and why it is no longer assumed: the full refresh does one
``affected_cpes ?|`` lookup per unit of work, and both sides of that grew
sharply in August 2026 without anything recording the effect. Migration 077
moved the unit of work from ~21k titles to ~40k product+versions, and the
``d0b8aea`` backfill took ``intel.cpes`` from 164,860 rows (ADR-0015,
2026-08-06) to 1,799,966 (measured 2026-08-12) -- a 10.9x increase. Migration
090 adds ``intel_ingest_status.last_duration_seconds`` so this run's cost is
observable instead of inferred. Matching still examines the full installed
scope: difference persistence does not skip recomputation or allow a stale match
to survive a CVE withdrawal.
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict

from ingest import db
from ingest.config import settings
from ingest.intel.material import MaterialCount
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_TENANT_ID = 1
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_MIN_DISTINCTIVE_LEN = 4
_VERSION_YEAR_RE = re.compile(r"\b(20[1-3][0-9])\b")
_VERSION_SEMVER_RE = re.compile(r"\b(\d+(?:\.\d+){1,3})\b")
_CPE_CACHE_MAX_ROWS = 20_000
_CPE_CACHE_MAX_ENTRIES = 256
_CVE_LOOKUP_BATCH_SIZE = 500

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
    INSERT INTO pg_temp.cve_match_desired (
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
    # Large arrays make the planner abandon the GIN index for a full CVE
    # scan. The union of bounded any-key lookups has exactly the same matches.
    # Deduplicate across batches: one CVE may affect CPEs in several batches.
    started = time.monotonic()
    found: list[str] = []
    seen: set[str] = set()
    for offset in range(0, len(cpe_candidates), _CVE_LOOKUP_BATCH_SIZE):
        cur.execute(
            """
            SELECT cve_id
              FROM intel.cves
             WHERE affected_cpes ?| %s::text[]
            """,
            (cpe_candidates[offset:offset + _CVE_LOOKUP_BATCH_SIZE],),
        )
        for (cve_id,) in cur.fetchall():
            if cve_id not in seen:
                seen.add(cve_id)
                found.append(cve_id)
    elapsed = time.monotonic() - started
    if elapsed >= 1:
        log.info(
            "Intel matcher CVE lookup: candidates=%d queries=%d rows=%d elapsed_seconds=%.3f",
            len(cpe_candidates),
            (len(cpe_candidates) + _CVE_LOOKUP_BATCH_SIZE - 1) // _CVE_LOOKUP_BATCH_SIZE,
            len(found), elapsed,
        )
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
    catalog gave installations a version identity.
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


class _CpeCandidateCache:
    """Reuse identical CPE queries within one full matcher refresh.

    Bound both rows and entries: a large candidate pool is still used in full,
    but is not retained when it would exceed the cache's row budget. Empty
    results are cached too. No result survives into the next matcher run.
    """

    def __init__(
        self,
        max_rows: int = _CPE_CACHE_MAX_ROWS,
        max_entries: int = _CPE_CACHE_MAX_ENTRIES,
    ) -> None:
        self.max_rows = max_rows
        self.max_entries = max_entries
        self.rows = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._entries: OrderedDict[tuple, tuple[tuple[str, str | None], ...]] = OrderedDict()

    def lookup(
        self,
        cur,
        tier1_pairs: set[tuple[str, str]],
        tier2_products: set[str],
    ) -> tuple[tuple[str, str | None], ...]:
        if tier1_pairs:
            key = ("tier1", tuple(sorted(tier1_pairs)))
        else:
            key = ("tier2", tuple(sorted(tier2_products)))
        cached = self._entries.get(key)
        if cached is not None:
            self.hits += 1
            self._entries.move_to_end(key)
            return cached

        self.misses += 1
        if tier1_pairs:
            # Preserve positional pairs and both leading index columns.
            pairs = sorted(tier1_pairs)
            cur.execute(
                """
                SELECT c.cpe23, c.version
                  FROM intel.cpes c
                  JOIN unnest(%s::text[], %s::text[]) AS k(vendor, product)
                    ON LOWER(c.vendor) = k.vendor
                   AND LOWER(c.product) = k.product
                """,
                ([v for v, _ in pairs], [p for _, p in pairs]),
            )
        else:
            cur.execute(
                """
                SELECT cpe23, version FROM intel.cpes
                 WHERE LOWER(product) = ANY(%s::text[])
                 LIMIT 500
                """,
                (list(tier2_products),),
            )
        rows = tuple(cur.fetchall())
        if len(rows) > self.max_rows or self.max_entries <= 0:
            return rows
        while self._entries and (
            self.rows + len(rows) > self.max_rows
            or len(self._entries) >= self.max_entries
        ):
            _, removed = self._entries.popitem(last=False)
            self.rows -= len(removed)
            self.evictions += 1
        self._entries[key] = rows
        self.rows += len(rows)
        return rows


def _persist_match_differences(cur) -> None:
    """Publish the complete staged set without rewriting equal matches."""
    cur.execute(
        """
        DELETE FROM operations.cve_match existing
        WHERE existing.tenant_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM pg_temp.cve_match_desired desired
              WHERE desired.tenant_id = existing.tenant_id
                AND desired.canonical_name = existing.canonical_name
                AND desired.software_version_id IS NOT DISTINCT FROM existing.software_version_id
                AND desired.cve_id = existing.cve_id
                AND desired.match_kind = existing.match_kind
          )
        """,
        (_TENANT_ID,),
    )
    cur.execute(
        """
        INSERT INTO operations.cve_match AS existing (
            tenant_id, canonical_name, software_version_id, cve_id,
            match_kind, version_range, confidence
        )
        SELECT desired.tenant_id, desired.canonical_name, desired.software_version_id,
               desired.cve_id, desired.match_kind, desired.version_range, desired.confidence
        FROM pg_temp.cve_match_desired desired
        WHERE desired.tenant_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM operations.cve_match current
              WHERE current.tenant_id = desired.tenant_id
                AND current.canonical_name = desired.canonical_name
                AND current.software_version_id IS NOT DISTINCT FROM desired.software_version_id
                AND current.cve_id = desired.cve_id
                AND current.match_kind = desired.match_kind
                AND ROW(current.version_range, current.confidence)
                    IS NOT DISTINCT FROM ROW(desired.version_range, desired.confidence)
          )
        ON CONFLICT (tenant_id, canonical_name, software_version_id, cve_id, match_kind)
        DO UPDATE SET version_range = EXCLUDED.version_range,
                      confidence = EXCLUDED.confidence,
                      matched_at = now()
        WHERE ROW(existing.version_range, existing.confidence)
              IS DISTINCT FROM ROW(EXCLUDED.version_range, EXCLUDED.confidence)
        """,
        (_TENANT_ID,),
    )


def _match_and_upsert() -> int:
    third_token_vendors, ignore_patterns = _load_hints()

    with db.transaction() as cur:
        # Unit of work is the installed product+version, not the bare title.
        # ADR-0012 s5 binds CVEs to software+version, and the ADR-0008
        # amendment of 2026-08-06 records what title scope cost: every device
        # running any version of a matched product was flagged identically,
        # including patched ones. `software_version_id` is 100% populated on
        # installations (489,347/489,347 measured 2026-08-10), so the catalog
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
    candidate_cache = _CpeCandidateCache()
    with db.transaction() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE cve_match_before ON COMMIT DROP AS
            SELECT canonical_name, software_version_id, cve_id,
                   match_kind, version_range, confidence
              FROM operations.cve_match
             WHERE tenant_id = %s
            """,
            (_TENANT_ID,),
        )
        cur.execute(
            """
            CREATE TEMP TABLE cve_match_desired ON COMMIT DROP AS
            SELECT tenant_id, canonical_name, software_version_id, cve_id,
                   match_kind, version_range, confidence
            FROM operations.cve_match WITH NO DATA
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX cve_match_desired_scope_idx
            ON pg_temp.cve_match_desired (
                tenant_id, canonical_name, software_version_id, cve_id, match_kind
            ) NULLS NOT DISTINCT
            """
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

            # Reuse unfiltered pools across titles with identical lookups.
            # Version filtering stays per installed version below; filtering
            # the shared pool would discard evidence other versions need.
            cpe_rows = candidate_cache.lookup(cur, tier1_pairs, tier2_products)
            lookups = candidate_cache.hits + candidate_cache.misses
            if lookups % 1000 == 0:
                log.info(
                    "Intel matcher CPE progress: lookups=%d queries=%d reused=%d cached_rows=%d",
                    lookups, candidate_cache.misses, candidate_cache.hits, candidate_cache.rows,
                )
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

        _persist_match_differences(cur)
        cur.execute(
            """
            SELECT EXISTS (
                (SELECT canonical_name, software_version_id, cve_id,
                        match_kind, version_range, confidence
                   FROM operations.cve_match WHERE tenant_id = %s
                 EXCEPT
                 SELECT canonical_name, software_version_id, cve_id,
                        match_kind, version_range, confidence
                   FROM cve_match_before)
                UNION ALL
                (SELECT canonical_name, software_version_id, cve_id,
                        match_kind, version_range, confidence
                   FROM cve_match_before
                 EXCEPT
                 SELECT canonical_name, software_version_id, cve_id,
                        match_kind, version_range, confidence
                   FROM operations.cve_match WHERE tenant_id = %s)
            )
            """,
            (_TENANT_ID, _TENANT_ID),
        )
        material_changed = bool(cur.fetchone()[0])
        if material_changed:
            # Change history (ADR-0033): record the matches that were added or
            # removed, including payload changes represented as a before/after pair.
            cur.execute(
                "SELECT to_regclass('operations.cve_match_change_history') IS NOT NULL"
            )
            if cur.fetchone()[0]:
                cur.execute(
                    "SELECT operations.record_cve_match_changes(%s)", (_TENANT_ID,)
                )
            # Preserve the exact affected identity before the next matcher
            # refresh replaces this set. Version matches are exact; product
            # level matches safely target installations by canonical name.
            # Operations applies its migration independently from ingest.  Do
            # not make the matcher unavailable during that short startup gap.
            cur.execute("SELECT to_regclass('operations.software_reclassification_targets')")
            if cur.fetchone()[0] is not None:
                cur.execute(
                """
                INSERT INTO operations.software_reclassification_targets AS target
                    (tenant_id, target_key, software_version_id, canonical_name, source)
                SELECT DISTINCT %s,
                       CASE WHEN changed.software_version_id IS NOT NULL
                            THEN 'version:' || changed.software_version_id::text
                            ELSE 'name:' || LOWER(changed.canonical_name) END,
                       changed.software_version_id,
                       CASE WHEN changed.software_version_id IS NULL
                            THEN LOWER(changed.canonical_name) ELSE '' END,
                       'cve_match'
                  FROM (
                      (SELECT canonical_name, software_version_id, cve_id,
                              match_kind, version_range, confidence
                         FROM operations.cve_match WHERE tenant_id = %s
                       EXCEPT
                       SELECT canonical_name, software_version_id, cve_id,
                              match_kind, version_range, confidence
                         FROM cve_match_before)
                      UNION
                      (SELECT canonical_name, software_version_id, cve_id,
                              match_kind, version_range, confidence
                         FROM cve_match_before
                       EXCEPT
                       SELECT canonical_name, software_version_id, cve_id,
                              match_kind, version_range, confidence
                         FROM operations.cve_match WHERE tenant_id = %s)
                  ) changed
                ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL
                DO UPDATE SET queued_at = now(), generation = target.generation + 1
                """,
                    (_TENANT_ID, _TENANT_ID, _TENANT_ID),
                )

    log.info(
        "Intel matcher CPE lookups: queries=%d reused=%d evictions=%d cached_rows=%d",
        candidate_cache.misses, candidate_cache.hits, candidate_cache.evictions,
        candidate_cache.rows,
    )
    log.info(
        "Intel matcher: %d titles matched (%d product+version pairs), "
        "%d sub-components ignored, %d cve_match rows.",
        matched_titles, matched_versions, ignored_titles, total_rows,
    )
    return MaterialCount(total_rows, material_changed=material_changed)


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
