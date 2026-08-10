"""Project end-of-life dates from the corpus onto catalogue versions.

Separate from `endoflife.py` for the same reason `matcher.py` is separate from
`cpe_dict.py`: fetching a corpus and deciding what it means for our titles are
different jobs with different failure modes and different cadences. A matching
fix must not re-fetch 462 products, and a corpus refresh must not re-decide
matching.

Deterministic and rebuildable -- a projector in the `docs/glossary.md` sense.
It is the sole writer of `catalog.software_versions.eol_date` / `eol_source`,
and re-running it produces the same result.

Which of our titles corresponds to which corpus product is
**operator-maintained data** in `operations.eol_product_map`, never a constant
here (ADR-0012 section 6). The table starts empty, so this projector writes
nothing until an operator maps something -- which is the honest state, not a
silent no-op: the run log reports how many mappings were in force.
"""

from __future__ import annotations

import logging

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_TENANT_ID = 1

# Longest cycle wins, and the boundary matters: matching '3.13.2' against cycle
# '3.1' must fail, which `version LIKE cycle || '.%'` gives us and a bare
# `LIKE cycle || '%'` would not ('3.13.2' does start with '3.1').
_PROJECT_SQL = """
WITH mapped AS (
    SELECT p.id AS product_id, m.eol_product, m.priority
      FROM operations.eol_product_map m
      JOIN catalog.products p
        ON p.canonical_name ILIKE m.raw_pattern
     WHERE m.tenant_id = %(tenant)s
),
best_product AS (
    -- One corpus product per catalogue product: lowest priority wins, name
    -- breaks ties so the result is deterministic rather than arbitrary.
    SELECT DISTINCT ON (product_id) product_id, eol_product
      FROM mapped
     ORDER BY product_id, priority, eol_product
),
candidate AS (
    SELECT sv.id            AS version_id,
           r.eol_from,
           r.product_name,
           r.cycle,
           length(r.cycle)  AS cycle_len
      FROM catalog.software_versions sv
      JOIN best_product bp ON bp.product_id = sv.product_id
      JOIN intel.eol_releases r ON r.product_name = bp.eol_product
     WHERE sv.version <> ''
       AND (sv.version = r.cycle OR sv.version LIKE r.cycle || '.%%')
),
best AS (
    SELECT DISTINCT ON (version_id)
           version_id,
           eol_from,
           product_name || '#' || cycle AS src
      FROM candidate
     ORDER BY version_id, cycle_len DESC, cycle
)
UPDATE catalog.software_versions sv
   SET eol_date   = best.eol_from,
       eol_source = 'endoflife.date:' || best.src,
       updated_at = now()
  FROM best
 WHERE sv.id = best.version_id
   AND (sv.eol_date   IS DISTINCT FROM best.eol_from
     OR sv.eol_source IS DISTINCT FROM 'endoflife.date:' || best.src)
"""

# A version that no longer matches any mapping must lose its date, or a
# withdrawn mapping would leave a stale EOL claim asserting itself forever.
# eol_source going empty is the record that the claim was cleared and that it
# came from this projector rather than never having existed.
_CLEAR_SQL = """
UPDATE catalog.software_versions sv
   SET eol_date   = NULL,
       eol_source = '',
       updated_at = now()
 WHERE sv.eol_source LIKE 'endoflife.date:%%'
   AND sv.id NOT IN (
        SELECT sv2.id
          FROM catalog.software_versions sv2
          JOIN (
              SELECT DISTINCT ON (p.id) p.id AS product_id, m.eol_product
                FROM operations.eol_product_map m
                JOIN catalog.products p
                  ON p.canonical_name ILIKE m.raw_pattern
               WHERE m.tenant_id = %(tenant)s
               ORDER BY p.id, m.priority, m.eol_product
          ) bp ON bp.product_id = sv2.product_id
          JOIN intel.eol_releases r ON r.product_name = bp.eol_product
         WHERE sv2.version <> ''
           AND (sv2.version = r.cycle OR sv2.version LIKE r.cycle || '.%%')
   )
"""


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_ENDOFLIFE_ENABLED):
        log.info("End-of-life projection disabled by flag; skipping")
        return 0
    with record_run("eol_match") as state:
        written, cleared, mappings = _project()
        state["rows_touched"] = written + cleared
        state["notes"] = (
            f"{mappings} mapping(s) in force; {written} version(s) dated, "
            f"{cleared} cleared."
        )
        return written + cleared


def _project() -> tuple[int, int, int]:
    with db.transaction() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM operations.eol_product_map WHERE tenant_id = %s",
            (_TENANT_ID,),
        )
        mappings = cur.fetchone()[0]

        cur.execute(_PROJECT_SQL, {"tenant": _TENANT_ID})
        written = cur.rowcount

        cur.execute(_CLEAR_SQL, {"tenant": _TENANT_ID})
        cleared = cur.rowcount

    # The suggestion list is derived from the corpus and the mapping table, both
    # of which may have just changed. Refreshed here rather than on read because
    # it costs ~37s to compute. Best-effort: a stale suggestions list is a
    # nuisance, a failed projection run is not, so this never fails the caller.
    try:
        with db.transaction() as cur:
            cur.execute(
                "REFRESH MATERIALIZED VIEW operations.v_eol_mapping_candidates"
            )
        log.info("Refreshed operations.v_eol_mapping_candidates")
    except Exception:
        log.exception("Failed to refresh v_eol_mapping_candidates")

    if mappings == 0:
        # Visible rather than silent: an empty mapping table is a real,
        # actionable state ("nobody has mapped anything yet"), not success.
        log.warning(
            "End-of-life projection: operations.eol_product_map is empty, so no "
            "version can receive an EOL date. eol_runtime remains title-scoped."
        )
    log.info(
        "End-of-life projection: %d mapping(s), %d version(s) dated, %d cleared.",
        mappings, written, cleared,
    )
    return written, cleared, mappings
