"""General category recognition projector -> catalog.category_assertion_machine.

Sole writer of machine-derived category evidence. Operator assertions
(`catalog.category_assertion_operator`) are never touched here: only a human
may assert that something is *not* a category, and that negative must survive
every projector run. Same shape as `capability_match.py`, on a different axis
-- see migration 104 for why the two are separate tables rather than one.

Evidence source: `operations.safety_signal` tag rows written by the Winget and
Chocolatey enrichers, matched through `catalog.category_tag_rule` (data,
ADR-0012 section 6 -- never a hardcoded tag list) to reach a `product_uuid` via
the installation link (safety_signal carries no product identity of its own,
only a canonical_name).

What it does NOT do, deliberately, mirroring capability_match.py:

  * It does not decide whether its output may alert. It cannot -- there is no
    unauthorized_<category> finding and no may_alert column on
    catalog.category_source at all. Every source here is a community tag, so
    nothing this projector writes can ever be more than a candidate; only an
    operator confirmation reaches 'confirmed'.
  * It does not write negatives. Machine evidence is positive-only.
  * It does not fuzzy-match tags. A tag is looked up in category_tag_rule
    exactly (after lowercasing) or it is not mapped -- same discipline as the
    enrichers' own exact-title matching, for the same reason: an unmapped tag
    staying unmapped is a fact worth preserving, not a gap to paper over with
    a guess.

Withdrawal safety is the same distinction capability_match.py documents: a
source that **loaded its tag rules and matched nothing** must withdraw its
stale assertions, while a rule set that **failed to load** must withdraw
nothing at all.
"""

from __future__ import annotations

import logging

from ingest import db
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

MATCHER_VERSION = "category_match/1"

# This projector owns both tag sources entirely. Operator rows are written
# elsewhere, and a withdrawal that reached them would delete evidence this
# projector cannot rebuild.
_OWNED_SOURCES = ("winget_tag", "chocolatey_tag")

# safety_signal.source uses the enricher's own name ('winget', 'chocolatey');
# catalog.category_source.source_key carries the '_tag' suffix to distinguish
# it from any future non-tag source for the same enricher. The CASE below is
# the one place that mapping lives.
_COMPUTE_SQL = """
CREATE TEMP TABLE category_desired ON COMMIT DROP AS
WITH matched AS (
    SELECT DISTINCT
           p.product_uuid,
           r.category,
           CASE ss.source
               WHEN 'winget'     THEN 'winget_tag'
               WHEN 'chocolatey' THEN 'chocolatey_tag'
           END AS source_key,
           LOWER(tag_val) AS tag
      FROM operations.safety_signal ss
      JOIN operations.software_installations_current sic
        ON LOWER(sic.canonical_name) = LOWER(ss.canonical_name)
       AND sic.tenant_id = ss.tenant_id
       AND sic.deleted_at IS NULL
       AND sic.stale_since IS NULL
      JOIN catalog.software_versions sv ON sv.id = sic.software_version_id
      JOIN catalog.products p ON p.id = sv.product_id
      CROSS JOIN LATERAL jsonb_array_elements_text(ss.details->'tags') AS tag_val
      JOIN catalog.category_tag_rule r ON r.tag = LOWER(tag_val) AND r.enabled
     WHERE ss.signal_type = 'category'
       AND ss.source IN ('winget', 'chocolatey')
)
-- One row per (product, category, source): several tags on one title routinely
-- map to the same category ("video" and "media-player" both -> media), and
-- without this collapse the upsert below would try to update the same unique
-- row twice in a single statement, same failure mode capability_match.py's
-- own comment documents.
SELECT product_uuid, category, source_key,
       0.700::numeric(4,3) AS confidence,
       'tag_match' AS evidence_kind,
       string_agg(DISTINCT tag, ',' ORDER BY tag) AS evidence_ref
  FROM matched
 GROUP BY product_uuid, category, source_key
"""

_WRITE_SQL = """
INSERT INTO catalog.category_assertion_machine
    (product_uuid, category, source_key, confidence,
     evidence_kind, evidence_ref, matcher_version)
SELECT d.product_uuid, d.category, d.source_key, d.confidence,
       d.evidence_kind, d.evidence_ref, %s
  FROM category_desired d
ON CONFLICT (product_uuid, category, source_key)
    WHERE withdrawn_at IS NULL
DO UPDATE SET
    last_observed_at = now(),
    confidence       = EXCLUDED.confidence,
    evidence_kind    = EXCLUDED.evidence_kind,
    evidence_ref     = EXCLUDED.evidence_ref,
    matcher_version  = EXCLUDED.matcher_version
"""

_WITHDRAW_SQL = """
UPDATE catalog.category_assertion_machine m
   SET withdrawn_at     = now(),
       withdrawn_reason = 'no longer matched by ' || m.source_key
                          || ' tag rules (' || %s || ')'
 WHERE m.withdrawn_at IS NULL
   AND m.source_key = ANY(%s::text[])
   AND NOT EXISTS (
       SELECT 1 FROM category_desired d
        WHERE d.product_uuid = m.product_uuid
          AND d.category     = m.category
          AND d.source_key   = m.source_key
   )
"""


def run_once() -> int:
    # Imported here, not at module scope, so project_with_cursor can be
    # exercised against a disposable Postgres without pulling in
    # pydantic-backed settings -- same reason capability_match.py does this.
    from ingest.config import settings

    if not (settings.INTEL_ENABLED and settings.INTEL_CATEGORY_ENABLED):
        log.info("Category projection disabled by flag; skipping")
        return 0
    with record_run("category_match") as state:
        written, withdrawn, rules, evaluated = _project()
        state["rows_touched"] = written + withdrawn
        state["notes"] = (
            f"{rules} tag rule(s) over {len(evaluated)} source(s); "
            f"{written} assertion(s) written, {withdrawn} withdrawn."
        )
        return written + withdrawn


def _project() -> tuple[int, int, int, list[str]]:
    with db.pool.connection() as conn, conn.cursor() as cur:
        return project_with_cursor(cur)


def project_with_cursor(cur) -> tuple[int, int, int, list[str]]:
    """The whole projection, including its guards, against one cursor.

    Must run inside a transaction: `_COMPUTE_SQL` builds a TEMP TABLE ...
    ON COMMIT DROP, so an autocommit connection would drop it before the write.
    """
    cur.execute("SELECT count(*) FROM catalog.category_tag_rule WHERE enabled")
    rules = int(cur.fetchone()[0])

    # A tag-rule table that loaded as empty is indistinguishable from one that
    # matched nothing, and treating the two the same would withdraw every
    # assertion this projector has ever made. Refuse instead.
    if rules == 0:
        log.warning(
            "category_match: no enabled category_tag_rule rows -- skipping "
            "the run rather than withdrawing existing evidence"
        )
        return 0, 0, 0, []

    # Sources whose rules could in principle have matched this run -- both are
    # owned outright by this table, so both are always "evaluated" once any
    # rule exists, unlike capability_match.py where source_key varies per rule.
    evaluated = list(_OWNED_SOURCES)

    cur.execute(_COMPUTE_SQL)

    cur.execute(_WRITE_SQL, (MATCHER_VERSION,))
    written = cur.rowcount or 0

    cur.execute(_WITHDRAW_SQL, (MATCHER_VERSION, evaluated))
    withdrawn = cur.rowcount or 0

    log.info(
        "Category projection: %d tag rule(s), %d written, %d withdrawn, sources=%s",
        rules, written, withdrawn, ",".join(evaluated),
    )
    return written, withdrawn, rules, evaluated
