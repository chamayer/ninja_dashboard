-- 090: record how long each intel connector run takes.
--
-- `operations.intel_ingest_status` records when a connector last ran, whether
-- it succeeded, and what it touched -- but never how long it took. That gap
-- became load-bearing on 2026-08-12: asked for an estimate of a running
-- matcher, there was no way to answer from data, because outcome was recorded
-- and cost was not.
--
-- The cost is not static, and the code says otherwise. `ingest/intel/matcher.py`
-- documents "Every run is a full refresh (DELETE tenant + INSERT)" and
-- justifies it as "small enough that a full rebuild is cheap". That was
-- measured when `intel.cpes` held 164,860 rows (ADR-0015, 2026-08-06).
-- Measured 2026-08-12 it holds 1,799,966 -- a 10.9x increase from the d0b8aea
-- backfill -- and migration 077 independently moved the matcher's unit of work
-- from ~21k titles to ~40k product+versions. A documented "cheap" that nothing
-- re-measures is exactly the shape ADR-0012 exists to prevent.
--
-- Recorded on the shared status table rather than in the matcher, so all
-- eleven connectors are covered by one change and a future slow feed is
-- visible without anyone thinking to instrument it.
--
-- Nullable: rows written before this migration have no duration, and
-- backfilling a fabricated one would be worse than an honest NULL.

ALTER TABLE operations.intel_ingest_status
    ADD COLUMN IF NOT EXISTS last_duration_seconds double precision;

COMMENT ON COLUMN operations.intel_ingest_status.last_duration_seconds IS
    'Wall-clock seconds for the most recent run, successful or failed. NULL '
    'for runs recorded before migration 090.';

-- No grant changes: a new column inherits the table privileges and no new
-- relation is created, so the read-model revoke rule in operations/AGENTS.md
-- does not apply.
