-- 105: seed the known-connector list as data, not a hardcoded count.
--
-- operations/apps/core/views.py's admin overview reported intel connector
-- health as "ok / failed / never run", and derived "never run" for connectors
-- with zero rows in operations.intel_ingest_status by hand:
--
--     intel_never += max(0, 9 - (intel_ok + intel_failed + intel_never))
--
-- "9" was a guess at the total connector count, hardcoded in Operations, kept
-- in sync by hand against a connector list that lives entirely in a different
-- service's source (ingest/main.py's scheduler jobs, HTTP routes and
-- catch-up plan). Measured 2026-08-19: the real count was already 11 before
-- this migration's own category_match connector made it 12 -- "9" had been
-- wrong for a while, silently, because nothing connected the two.
--
-- record_run() (ingest/intel/status.py) always UPSERTs a row on every
-- invocation, success or failure, so the only way a connector has zero rows
-- is if it has never been invoked even once. Seeding a placeholder row per
-- known connector -- last_run_at NULL, meaning exactly "known to exist,
-- never run" -- means every connector Operations should ever report on
-- already has a row, and the count of "how many connectors are there" no
-- longer needs to live in either service's Python at all: it is just
-- `SELECT count(*) FROM operations.intel_ingest_status`.
--
-- ON CONFLICT DO NOTHING: this only adds rows for connectors with no history
-- yet. A connector that has already run keeps its real last_run_at,
-- last_status and everything else untouched.
--
-- List verified 2026-08-19 against the table's own real, already-running
-- connector names -- not written from memory of ingest/main.py's separate
-- enumerations. A from-memory first attempt at this same list missed
-- eol_match, which was already running and already had rows: proof, while
-- writing the fix, of exactly the drift this migration exists to stop.
--
-- This becomes the canonical registry going forward: adding connector #15
-- means adding its row here, the same way a new capability or category gets
-- a migration-seeded registry row. That is an explicit, reviewed addition to
-- data, not a hidden assumption -- the thing ADR-0012 section 6 asks for.
INSERT INTO operations.intel_ingest_status (connector) VALUES
    ('cisa_kev'),
    ('nvd'),
    ('cpe_dict'),
    ('epss'),
    ('winget'),
    ('chocolatey'),
    ('otx'),
    ('abusech'),
    ('endoflife'),
    ('eol_match'),
    ('matcher'),
    ('capability_match'),
    ('category_match'),
    ('lolrmm')
ON CONFLICT (connector) DO NOTHING;
