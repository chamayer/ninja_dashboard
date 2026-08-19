"""Capability recognition projector → catalog.capability_assertion_machine.

Sole writer of machine-derived capability evidence. Operator assertions
(`catalog.capability_assertion_operator`) are never touched here: only a human
may assert that something is *not* a capability, and that negative must survive
every projector run.

What it does NOT do, deliberately:

  * It does not decide whether its output may raise an alert. That is
    `catalog.capability_source.may_alert`, a migration-seeded registry row, so a
    connector cannot promote itself to authoritative.
  * It does not write negatives. Machine evidence is positive-only; absence of
    evidence is not evidence of absence.
  * It does not fuzzy-match. Measured 2026-08-12 over 31 real titles, the best
    correct fuzzy match scored *below* the worst wrong one, so no similarity
    threshold separates them.

Phase 1 is shadow mode: assertions are recorded and nothing enforces them.
`unauthorized_*` emission is unchanged until Phase 4, which needs its own
approval after shadow-mode results.

Two independent evidence paths, run as two independent passes in
`project_with_cursor`: anchored title/publisher patterns from
`catalog.capability_rule` (`vetted_rule`, `publisher_rule`), and community
package tags from `catalog.capability_tag_rule` (migration 106; `winget_tag`,
`chocolatey_tag`). They are kept apart rather than unioned into one query so a
change to one cannot regress the other -- `capability_rule`'s own
`ck_capability_rule_source` CHECK forbids it from carrying the tag source keys
at all, which is *why* there are two tables instead of one.

Withdrawal safety is the sharpest edge here, and it turns on one distinction:
a source that **loaded its rules and matched nothing** must withdraw its stale
assertions, while a rule set that **failed to load** must withdraw nothing at
all. Conflating them either strands evidence that no rule supports, or wipes
the whole corpus on a bad read. Each pass carries its own guard, so an empty
(or not-yet-migrated) tag_rule table cannot block the pattern-rule pass and
vice versa.

So "evaluated" means *rules loaded*, computed independently of whether any
product matched, and withdrawal is scoped to those sources. The empty-rule
guard in each pass of `project_with_cursor` is the other half: zero enabled
rules for that pass is treated as a failed or empty load and that pass returns
without touching anything.
"""

from __future__ import annotations

import logging

from ingest import db
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

MATCHER_VERSION = "capability_match/1"

# Rule-driven sources this projector owns. It must never widen a withdrawal
# beyond these: `lolrmm` (Phase 3) and `operator` rows are written elsewhere,
# and a clear that reached them would delete evidence this projector cannot
# rebuild.
_OWNED_SOURCES = ("vetted_rule", "publisher_rule")

# Build the desired assertion set from the rule table. Anchored ILIKE patterns
# only -- the constraint on catalog.capability_rule rejects a leading wildcard,
# because that is how a title inherits the wrong capability.
_COMPUTE_SQL = """
CREATE TEMP TABLE capability_desired ON COMMIT DROP AS
WITH matched AS (
    SELECT p.product_uuid,
           r.capability,
           r.source_key,
           r.priority,
           r.rule_key,
           CASE WHEN r.title_pattern <> '' AND r.publisher_pattern <> '' THEN 2
                WHEN r.title_pattern <> ''                              THEN 1
                ELSE 0
           END AS specificity
      FROM catalog.capability_rule r
      JOIN catalog.products p
        ON (r.title_pattern = ''
            OR lower(p.canonical_name) LIKE lower(r.title_pattern))
      LEFT JOIN catalog.publishers pub ON pub.id = p.publisher_id
     WHERE r.enabled
       AND r.source_key = ANY(%s::text[])
       AND (r.publisher_pattern = ''
            OR lower(COALESCE(pub.canonical_name, '')) LIKE lower(r.publisher_pattern))
)
-- One row per (product, capability, source). Several rules routinely match one
-- product, and without this collapse the upsert below would try to update the
-- same unique row twice in a single statement -- PostgreSQL raises
-- "ON CONFLICT DO UPDATE command cannot affect row a second time", so the whole
-- projection fails rather than one rule losing.
--
-- Precedence is explicit and total: most specific match, then lowest priority
-- number (the convention `capability_rule.priority` and `eol_product_map` both
-- use), then rule_key as a deterministic tie-break so two runs over unchanged
-- data cannot disagree.
SELECT DISTINCT ON (product_uuid, capability, source_key)
       product_uuid,
       capability,
       source_key,
       CASE specificity WHEN 2 THEN 0.950
                        WHEN 1 THEN 0.900
                        ELSE 0.600      -- publisher alone is weak evidence
       END::numeric(4,3) AS confidence,
       CASE specificity WHEN 2 THEN 'rule.title+publisher'
                        WHEN 1 THEN 'rule.title'
                        ELSE 'rule.publisher'
       END AS evidence_kind,
       rule_key AS evidence_ref
  FROM matched
 ORDER BY product_uuid, capability, source_key, specificity DESC, priority, rule_key
"""

# Insert genuinely new evidence, refresh last_observed_at on evidence that is
# still supported. first_observed_at is never moved: it is when we first saw
# this, and a re-observation is not a new observation.
_WRITE_SQL = """
INSERT INTO catalog.capability_assertion_machine
    (product_uuid, capability, source_key, confidence,
     evidence_kind, evidence_ref, matcher_version)
SELECT d.product_uuid, d.capability, d.source_key, d.confidence,
       d.evidence_kind, d.evidence_ref, %s
  FROM capability_desired d
ON CONFLICT (product_uuid, capability, source_key)
    WHERE withdrawn_at IS NULL
DO UPDATE SET
    last_observed_at = now(),
    confidence       = EXCLUDED.confidence,
    evidence_kind    = EXCLUDED.evidence_kind,
    evidence_ref     = EXCLUDED.evidence_ref,
    matcher_version  = EXCLUDED.matcher_version
"""

# Withdraw evidence this projector owns that the current rules no longer
# support. Scoped to `evaluated` -- the sources whose rules LOADED this run,
# not the sources that produced matches. A loaded source that matched nothing
# is a real answer and must withdraw its stale assertions; only a failed or
# empty rule load skips withdrawal, and that is handled by the guard in
# `project_with_cursor` before this statement is reached.
# ADR-0012: nothing is lost without when and why, so the reason is NOT NULL and
# says which matcher withdrew it.
_WITHDRAW_SQL = """
UPDATE catalog.capability_assertion_machine m
   SET withdrawn_at     = now(),
       withdrawn_reason = 'no longer matched by ' || m.source_key
                          || ' rules (' || %s || ')'
 WHERE m.withdrawn_at IS NULL
   AND m.source_key = ANY(%s::text[])
   AND NOT EXISTS (
       SELECT 1 FROM capability_desired d
        WHERE d.product_uuid = m.product_uuid
          AND d.capability   = m.capability
          AND d.source_key   = m.source_key
   )
"""


# Second, independent evidence path: community package tags matched through
# catalog.capability_tag_rule (migration 106; data, ADR-0012 section 6 -- never
# a Python dict). Kept fully separate from the compute/write/withdraw above
# rather than unioned into one query, so a change here cannot regress the
# vetted_rule/publisher_rule path already running in production -- the same
# reason category_match.py's tag matching lives in its own module rather than
# folded into this one.
#
# winget_tag/chocolatey_tag are seeded in capability_source (093) with
# may_alert=FALSE. The effective view already resolves that correctly via its
# join to capability_source, so nothing below needs to know about alerting at
# all -- same non-authority discipline as the rule-based path above.
_TAG_OWNED_SOURCES = ("winget_tag", "chocolatey_tag")

_TAG_COMPUTE_SQL = """
CREATE TEMP TABLE capability_tag_desired ON COMMIT DROP AS
WITH matched AS (
    SELECT DISTINCT
           p.product_uuid,
           r.capability,
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
      JOIN catalog.capability_tag_rule r ON r.tag = LOWER(tag_val) AND r.enabled
     WHERE ss.signal_type = 'category'
       AND ss.source IN ('winget', 'chocolatey')
)
-- Same collapse reasoning as the rule-based compute above: several tags on
-- one title routinely map to the same capability, and without this the
-- upsert would try to update the same unique row twice in one statement.
SELECT product_uuid, capability, source_key,
       0.700::numeric(4,3) AS confidence,
       'tag_match' AS evidence_kind,
       string_agg(DISTINCT tag, ',' ORDER BY tag) AS evidence_ref
  FROM matched
 GROUP BY product_uuid, capability, source_key
"""

_TAG_WRITE_SQL = """
INSERT INTO catalog.capability_assertion_machine
    (product_uuid, capability, source_key, confidence,
     evidence_kind, evidence_ref, matcher_version)
SELECT d.product_uuid, d.capability, d.source_key, d.confidence,
       d.evidence_kind, d.evidence_ref, %s
  FROM capability_tag_desired d
ON CONFLICT (product_uuid, capability, source_key)
    WHERE withdrawn_at IS NULL
DO UPDATE SET
    last_observed_at = now(),
    confidence       = EXCLUDED.confidence,
    evidence_kind    = EXCLUDED.evidence_kind,
    evidence_ref     = EXCLUDED.evidence_ref,
    matcher_version  = EXCLUDED.matcher_version
"""

_TAG_WITHDRAW_SQL = """
UPDATE catalog.capability_assertion_machine m
   SET withdrawn_at     = now(),
       withdrawn_reason = 'no longer matched by ' || m.source_key
                          || ' tag rules (' || %s || ')'
 WHERE m.withdrawn_at IS NULL
   AND m.source_key = ANY(%s::text[])
   AND NOT EXISTS (
       SELECT 1 FROM capability_tag_desired d
        WHERE d.product_uuid = m.product_uuid
          AND d.capability   = m.capability
          AND d.source_key   = m.source_key
   )
"""


def run_once() -> int:
    # Imported here rather than at module scope so the projector's SQL and
    # control flow can be exercised against a disposable Postgres without
    # pulling in pydantic-backed settings. `project_with_cursor` is the unit
    # those tests drive.
    from ingest.config import settings

    if not (settings.INTEL_ENABLED and settings.INTEL_CAPABILITY_ENABLED):
        log.info("Capability projection disabled by flag; skipping")
        return 0
    with record_run("capability_match") as state:
        written, withdrawn, rules, evaluated = _project()
        state["rows_touched"] = written + withdrawn
        state["notes"] = (
            f"{rules} rule(s) over {len(evaluated)} source(s); "
            f"{written} assertion(s) written, {withdrawn} withdrawn."
        )
        return written + withdrawn


def _project() -> tuple[int, int, int, list[str]]:
    with db.pool.connection() as conn, conn.cursor() as cur:
        return project_with_cursor(cur)


def project_with_cursor(cur) -> tuple[int, int, int, list[str]]:
    """The whole projection, including its guards, against one cursor.

    Two independent passes -- pattern rules, then tag rules -- each with its
    own empty-rule guard, so an empty (or not-yet-migrated) tag_rule table
    cannot block the pattern-rule path and vice versa. Combined totals are
    returned; each pass's withdrawal is scoped only to the sources it owns,
    same as before this was split in two.

    Separated from `_project` so the control flow -- not just the SQL -- is
    executable in tests. The empty-rule guard in particular is the difference
    between "matched nothing" and "failed to load", and asserting its condition
    is not the same as proving it takes the branch.

    Must run inside a transaction: `_COMPUTE_SQL` builds a TEMP TABLE ...
    ON COMMIT DROP, so an autocommit connection would drop it before the write.
    """
    written = 0
    withdrawn = 0
    rules = 0
    evaluated: list[str] = []

    cur.execute(
        "SELECT count(*) FROM catalog.capability_rule "
        "WHERE enabled AND source_key = ANY(%s::text[])",
        (list(_OWNED_SOURCES),),
    )
    rule_count = int(cur.fetchone()[0])

    # A rule table that loaded as empty is indistinguishable from one that
    # matched nothing, and treating the two the same would withdraw every
    # assertion this projector has ever made. Refuse instead.
    if rule_count == 0:
        log.warning(
            "capability_match: no enabled rules for %s -- skipping the "
            "pattern-rule pass rather than withdrawing existing evidence",
            ", ".join(_OWNED_SOURCES),
        )
    else:
        # Sources whose rules LOADED, not sources that produced matches.
        #
        # Deriving this from the output would mean a source whose rules all
        # stopped matching never withdrew anything: its former assertions
        # would stay current forever, asserting a capability no rule
        # supports. A successful zero-match evaluation and a failed
        # evaluation must be distinguishable, and this is the line between
        # them -- the query below is what "the rules loaded" means, and the
        # `rule_count == 0` guard above is what "the load failed or the
        # table is empty" means.
        cur.execute(
            "SELECT DISTINCT source_key FROM catalog.capability_rule "
            "WHERE enabled AND source_key = ANY(%s::text[]) ORDER BY source_key",
            (list(_OWNED_SOURCES),),
        )
        rule_evaluated = [row[0] for row in cur.fetchall()]

        cur.execute(_COMPUTE_SQL, (list(_OWNED_SOURCES),))
        cur.execute(_WRITE_SQL, (MATCHER_VERSION,))
        written += cur.rowcount or 0
        cur.execute(_WITHDRAW_SQL, (MATCHER_VERSION, rule_evaluated))
        withdrawn += cur.rowcount or 0

        rules += rule_count
        evaluated += rule_evaluated

    cur.execute("SELECT count(*) FROM catalog.capability_tag_rule WHERE enabled")
    tag_count = int(cur.fetchone()[0])

    if tag_count == 0:
        log.warning(
            "capability_match: no enabled capability_tag_rule rows -- "
            "skipping the tag-rule pass rather than withdrawing existing "
            "evidence"
        )
    else:
        tag_evaluated = list(_TAG_OWNED_SOURCES)

        cur.execute(_TAG_COMPUTE_SQL)
        cur.execute(_TAG_WRITE_SQL, (MATCHER_VERSION,))
        written += cur.rowcount or 0
        cur.execute(_TAG_WITHDRAW_SQL, (MATCHER_VERSION, tag_evaluated))
        withdrawn += cur.rowcount or 0

        rules += tag_count
        evaluated += tag_evaluated

    log.info(
        "Capability projection: %d rule(s), %d written, %d withdrawn, sources=%s",
        rules, written, withdrawn, ",".join(evaluated),
    )
    return written, withdrawn, rules, evaluated