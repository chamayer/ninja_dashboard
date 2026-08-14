-- 101: index intel.cves.affected_cpes, the matcher's hot lookup.
--
-- The intel matcher was measured at 2,477 seconds per run (41 minutes), four
-- runs a day, about 2.75 database-hours daily. The backlog framed the question
-- as full rebuild versus incremental. Measurement on 2026-08-14 says it is
-- neither: the cost is one missing index.
--
-- `_cves_for()` issues
--
--     SELECT cve_id FROM intel.cves WHERE affected_cpes ?| $candidates
--
-- once per title and per distinct version-candidate set. `affected_cpes` is a
-- jsonb array and carried no GIN index, so every call sequentially scanned all
-- 97,520 CVE rows:
--
--     before   Seq Scan, 684.4 ms, 18,271 buffers (~143 MB) per call
--     after    Bitmap Index Scan, 0.063 ms, 7 buffers
--
-- At 684 ms a call, the measured 2,477-second run is roughly 3,600 such scans,
-- which is the expected order for 22,013 titles with the existing candidate-set
-- memoisation. The unit-of-work growth recorded in matcher.py -- 21k titles to
-- 526,466 product+version pairs -- was never the dominant cost; the missing
-- index was.
--
-- This keeps every run a full rebuild. matcher.py's own note warns not to make
-- the matcher incremental casually, because the DELETE-then-INSERT refresh is
-- what guarantees no stale match survives a CVE withdrawal. Fixing the lookup
-- preserves that guarantee instead of trading it away for speed.
--
-- Sizing, measured: 34 MB index against a 137 MB table, 11.4 CPEs per CVE on
-- average. jsonb_ops is required -- jsonb_path_ops does not support `?|`.
--
-- Build cost: 3.4 seconds, taking ACCESS EXCLUSIVE on intel.cves. The runner
-- wraps each migration in one transaction, so CONCURRENTLY is not available
-- here; the lock is held during startup before the service reports ready, and
-- the matcher does not run concurrently with it.
CREATE INDEX IF NOT EXISTS cves_affected_cpes_gin
    ON intel.cves USING gin (affected_cpes jsonb_ops);

COMMENT ON INDEX intel.cves_affected_cpes_gin IS
    'Supports the intel matcher''s affected_cpes ?| candidate lookup. Without it each call sequentially scans every CVE row (684 ms measured 2026-08-14).';
