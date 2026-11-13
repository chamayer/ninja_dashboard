# PLAN-056 — Sources count reader correction

2026-11-13. User approved moving to Admin Sources: measure its dominant cost,
apply the smallest correction within existing contracts, deploy, and verify.
Standing emergency approval covers necessary commit/push/deployment work.

Authenticated Sources baseline: HTTP 200, 81,340 bytes, 6.971 seconds, logout
confirmed. A separate isolated read-only render took 7.773 seconds: record counts
5.6452, source health 0.6724, three Jobs reads 0.0191/0.0454/0.3249 seconds.

The existing view calls is_companion_stream for every observation. Its result
depends only on tenant, source instance and namespace. Reviewed migration 0413
groups those keys and entity type before classifying each stream. It then combines
current/active/withdrawn counts and maximum last-seen time at the original grain.
The safe metadata view retains access controls. CREATE OR REPLACE preserves owner
and ACL; explicit DML revocation remains. No data rebuild, new store, cache,
configuration change, Python reader change, or public interface change is needed.
Only Sources directly consumes this view; its UI and CSV keep their existing path.

One repeatable-read, read-only comparison under the Operations runtime role:
original count 4.8739 seconds, grouped count 0.2794; complete Sources rendering
6.728 to 1.817 seconds, equal full context and 81,296 bytes in both renders.
Process-local caches cleared independently; no serving file or database object was
modified by the comparison. First comparison setup stopped before SQL because it
checked the cache proxy instead of its underlying backend; corrected diagnostic
verified LocMem before clearing. No tests were created or modified.

Release scope: VERSION/CHANGELOG 0.144.19 and existing migration 0413 only,
depending on 0416. Earlier numbered migrations 0414–0416 are already deployed;
Django follows the dependency chain, so 0413 runs last. Reverse SQL restores the
original view and retains the DML revocations. Unrelated Home/client/test work is
excluded. Dockerfile includes all Operations migrations.

Next: verify live owner privileges/column compatibility, focused syntax and
whitespace checks, then commit/push origin followed by mirror, automatic migration
and populated Sources/Software HTTP verification. Full latency acceptance is not
claimed from the isolated rendering result.
