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
    -- A mapping row now matches on title AND, optionally, on the installed
    -- version. Rows with an empty version_pattern apply to every version,
    -- which is the pre-082 behaviour.
    SELECT sv.id AS version_id,
           m.eol_product,
           m.eol_cycle,
           m.priority,
           -- A row that names a version range is more specific than one that
           -- does not, and must win regardless of priority ordering.
           (m.version_pattern <> '') AS is_version_pinned
      FROM operations.eol_product_map m
      JOIN catalog.products p
        ON p.canonical_name ILIKE m.raw_pattern
      JOIN catalog.software_versions sv
        ON sv.product_id = p.id AND sv.version <> ''
     WHERE m.tenant_id = %(tenant)s
       AND (m.version_pattern = '' OR sv.version ILIKE m.version_pattern)
),
best_map AS (
    -- One mapping per catalogue version: version-pinned rows first, then
    -- priority, then name so the result is deterministic rather than arbitrary.
    SELECT DISTINCT ON (version_id)
           version_id, eol_product, eol_cycle
      FROM mapped
     ORDER BY version_id, is_version_pinned DESC, priority, eol_product
),
candidate AS (
    SELECT bm.version_id,
           r.eol_from,
           r.product_name,
           r.cycle,
           -- An explicitly pinned cycle outranks any derived match, which is
           -- the only way to reach codename cycles ('22H2', 'Sonoma') that no
           -- numeric version can prefix-match.
           (bm.eol_cycle <> '' AND r.cycle = bm.eol_cycle) AS is_pinned_cycle,
           length(r.cycle) AS cycle_len
      FROM best_map bm
      JOIN catalog.software_versions sv ON sv.id = bm.version_id
      JOIN intel.eol_releases r ON r.product_name = bm.eol_product
     WHERE (
             -- explicit cycle, or...
             (bm.eol_cycle <> '' AND r.cycle = bm.eol_cycle)
             -- ...derive from the installed version, or...
          OR (bm.eol_cycle = ''
              AND (sv.version = r.cycle OR sv.version LIKE r.cycle || '.%%'))
             -- ...from a year token in the *title*, which is how
             -- 'Office 2010' (installed as 14.0.x) reaches cycle '2010'.
             -- The CVE matcher has always done this; the projector did not.
          OR (bm.eol_cycle = ''
              AND r.cycle ~ '^(19|20)[0-9]{2}$'
              AND EXISTS (SELECT 1 FROM catalog.products p2
                           WHERE p2.id = sv.product_id
                             AND p2.canonical_name ~ ('\\m' || r.cycle || '\\M')))
           )
),
best AS (
    SELECT DISTINCT ON (version_id)
           version_id,
           eol_from,
           product_name || '#' || cycle AS src
      FROM candidate
     ORDER BY version_id, is_pinned_cycle DESC, cycle_len DESC, cycle
)
SELECT version_id, eol_from, 'endoflife.date:' || src AS src
  INTO TEMP TABLE eol_best
  FROM best
"""

# Both the write and the clear read the same computed set. They used to carry
# two copies of the matching logic, which with pinned versions and cycles would
# have been three chances for the copies to drift -- and a drifted clear silently
# wipes correctly dated versions.
_WRITE_SQL = """
UPDATE catalog.software_versions sv
   SET eol_date   = b.eol_from,
       eol_source = b.src,
       updated_at = now()
  FROM eol_best b
 WHERE sv.id = b.version_id
   AND (sv.eol_date   IS DISTINCT FROM b.eol_from
     OR sv.eol_source IS DISTINCT FROM b.src)
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
   AND NOT EXISTS (SELECT 1 FROM eol_best b WHERE b.version_id = sv.id)
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

        # Compute the match set once, then write and clear from it.
        cur.execute("DROP TABLE IF EXISTS eol_best")
        cur.execute(_PROJECT_SQL, {"tenant": _TENANT_ID})

        cur.execute(_WRITE_SQL)
        written = cur.rowcount

        cur.execute(_CLEAR_SQL)
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
