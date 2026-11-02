# PLAN-041 — Host CPU and runtime profiling

## Status and goal

Active implementation. Finish the Ninja CPU fix, release it, and measure a
complete matcher run. The user requested continuation through the fix; existing
CPU-task commit/push authorization continues. No migrations, new dependencies,
host tuning, or matching-rule changes are included.

## Scope and affected files

- `ingest/intel/matcher.py`: bounded CPE reuse and CVE operand batches.
- `ingest/tests/test_matcher_candidate_cache.py`: output equivalence, versions,
  cache bounds, failures, and subsequent-run withdrawals.
- `VERSION`, `CHANGELOG.md`, registry/routing, and the retained
  [measurement record](../records/HOST-CPU-2026-11-02.md).
- Earlier phase diagnostics are deployed in 0.142.1 `573851c1`.
- DMARC `03ddf01` is deployed and healthy; its combined probe runs inside
  Manager, with no host units or Zabbix parser monitor.

## Decisions and steps

1. Retain a full matcher rebuild, version filtering, lexical precision, input
   selection, withdrawal behavior, and the existing fallback cap.
2. Cache identical CPE queries within one run only, bounded to 20,000 rows and
   256 pools. Oversized pools are used in full, not truncated or cached.
3. Split CVE any-key arrays into batches of at most 500 and deduplicate the
   union. This preserves matching while avoiding full CVE scans for large
   arrays. No persistent planner setting or index changes.
4. Release 0.142.2, verify the automatic rollout, then measure completed-run
   duration, lookup reuse, output material changes, and host CPU.

## Confirmed evidence and validation

The catalogue estimate found 13,005 lookups and 2,410 pools. A bounded simulation
reused 6,347 lookups. This is not a completed matcher-run benchmark.
Live read-only repeated-pool samples returned identical 500-row results, with
10 queries reduced to one (0.215→0.034 s and 0.159→0.014 s).

CVE EXPLAIN switched from GIN at 500/2,048 candidates to a full scan at 8,192.
The read-only original 8,192-candidate lookup exceeded a three-second limit;
17 batches finished in 0.508 s with the same eight CVEs as the original query
forced through its existing index in that diagnostic session. No global setting
changed. A real matcher membership query was observed running over three minutes.

16 focused matcher/index tests passed. Broader checks: 49 passed and one
existing source-string assertion failed in `test_software_reconcile.py`; the
referenced `operator_job_queue.py` is unchanged. Scoped Ruff, compilation,
registry, and whitespace checks pass. The software aggregation plan is recorded;
no speculative aggregation rewrite is included.

## Checkpoint and next action

Release 0.142.2 is prepared. Prior completed matcher baseline: 1,368 seconds and
648,106 match rows. Whole-job improvement is not yet claimed. Next: finish staged
review, confirm migration parity, commit and push origin then a-m-rose, verify
Portainer's automatic rollout, and follow a full optimized matcher run. Do not
trigger a separate redeploy. Preserve unrelated work and capture actual results
in the measurement record before marking this plan complete.
