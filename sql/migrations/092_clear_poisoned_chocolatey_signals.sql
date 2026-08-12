-- 092: discard the Chocolatey category signals, all of which are invalid.
--
-- The enricher queried `/api/v2/Packages()` with a `searchTerm` parameter.
-- `searchTerm` belongs to the `Search()` function; `Packages()` accepts the
-- query string, ignores the term, and returns HTTP 200 with the unfiltered
-- first page of the gallery. It then unioned the tags of every result in that
-- page into one set and stored it against whichever title it was enriching.
--
-- The result, measured 2026-08-12: 1,473 rows, exactly ONE distinct tag set,
-- 22 tags each, beginning "0install, 1c, 1c83, 1c83tonc, 1cfresh, 1password,
-- 1password8" -- the alphabetically first Chocolatey packages. `. .` and
-- `.net android templates (x64)` carried identical tags to everything else.
-- Winget, whose enricher is shaped correctly, has 154 distinct tag sets
-- across 379 rows for comparison.
--
-- Deleted rather than left to expire. `_titles_needing_refresh` only re-queries
-- a title whose newest signal is older than `_STALE_AFTER` (30 days), and these
-- rows were written 2026-08-10, so the corrected enricher would not revisit any
-- of them until September. Deleting makes every affected title eligible on the
-- next run.
--
-- This removes no true information: not one of these rows describes the title
-- it is attached to. Nothing is lost that was ever a fact -- which is the test
-- ADR-0012's "nothing is lost without when and why" asks for, and the when and
-- why are this file.
--
-- Scoped to source = 'chocolatey'. Winget, OTX, ThreatFox and AbuseCH rows are
-- untouched.

DELETE FROM operations.safety_signal
 WHERE source = 'chocolatey';

-- The corrected enricher (Search(), per-entry tag extraction, best-match
-- selection) repopulates these at _MAX_TITLES_PER_RUN = 500 per cycle.
