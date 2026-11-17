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

Live owner can read the safe metadata view; security_barrier=true and all eight
columns/types match the replacement. Live migration ledger has 0414–0416 applied
and 0413 absent. Python syntax, focused Ruff, whitespace and plan-registry checks
passed; commit governance passed with the existing stale current-state warning.

Release 4e9f2678 / 0.144.19 committed and pushed origin then mirror. Only the four
reviewed release files shipped; unrelated staged client-view changes preserved.
Next: verify automatic migration, services and populated Sources/Software HTTP.
Full latency acceptance is not claimed from the isolated rendering result.

Contract fit: global ADR-0006 R1/R2 retain the existing protected tenant-scoped
count population, companion rules and exact output grain; R4 resolves stream
classification once per grouped key. R5 retains a direct aggregate whose cost is
verified at the existing production population. R8 is checked on complete HTML.
No maintained result is introduced, so no new R6/R7 lifecycle is required. No
pagination, detail enrichment or export path is changed by this view replacement.

Rollout: ingest reports 0.144.19, all three services healthy, 0413 recorded applied.
The count view retains all eight column names/types, owner metadata access and
security_barrier=true. Authenticated Sources HTTP 200, 81,553 bytes in 3.304
seconds; normal logout confirmed. This is a 52.6% reduction from the same-session
6.971-second baseline, but remains above the intended interactive response budget.
No broader query tuning is included in this correction.

Software regression observation: protected reader stale/expired immediately after
rollout, HTTP 200 without the completed-summary marker. Its last publisher did
complete successfully at 16:38:03 UTC; the summary computed at 16:37:51 had a
window expiry of 16:38:15. All owners are ready and no classification targets are
pending. This is a freshness gap, not evidence of renewed self-invalidation.
Await the existing automatic refresh before concluding the regression check;
do not claim continuous Software availability. No Software changes are in this
Sources release.

Automatic Software refresh acddb5e4 was admitted at 16:40:27 UTC and is queued
waiting for capacity while source assessment, health evaluation and source refresh
are running. Owner readiness and classification are clear. This confirms the
remaining maintenance/capacity gap; it is outside this Sources SQL change. No
competing jobs were canceled during this release. Sustained Software availability
and Sources full latency acceptance remain open.
