# PLAN-056 — Software publication capacity and request fence

2026-11-13. User explicitly requests immediate repair of the remaining Software
freshness/capacity failure under standing emergency commit/push/deploy approval.

Confirmed after Sources release: overview waited for processing capacity while
source assessment and platform evaluation occupied that pool. Later builds failed
with changed preparation/publication inputs even after owner readiness cleared.
The Software input token includes automatic refresh request rows, so delivery of
a follow-up can invalidate a build without a new material input revision.

Scope: move only Software overview publication to the existing control-work pool,
priority 90. Keep its existing software-state resource, tenant writer guard,
global child limit, claim fences and all publication/read security/expiry checks.
No new pool, worker or service. A queued run keeps its immutable definition;
recovery must use governed cancellation/re-admission if an old revision remains.

Migration 0417 changes only the overview-request portion of software_overview_inputs:
explicit actor requests still participate; automatic request delivery does not.
Owner checkpoints, dirty ownership, pending classification and active-input checks
remain intact. It depends on deployed 0413; reversal restores the prior function.
No table rebuild, privilege change or direct summary write.

Next: focused syntax/registry/migration checks, release, ensure new definition is
used, wait for normal atomic publication, verify protected state and full HTML.
No broad suite or test-file edits. Sustained freshness is not certified yet.

Preparation: Python syntax, registry module validation and focused Ruff passed.
The existing snapshot check passed. The existing workflow-edge check failed on
its expected source-refresh-to-resolver edge: current source routes through
Computer ownership first. This change modifies no workflow edges (diff contains
only overview priority and pool), so the failure is unrelated; no tests edited.
The older pool test also contains a blanket priority=50 expectation despite
already-existing priorities 90 and 10; it was reviewed, not run or edited.
Dockerfiles include changed shared registry and Operations migration files.
An additional existing catalog-count check expects 33 definitions but the baseline
has 38; registry changes add no definitions. Snapshot determinism passes. These
outdated assertions are recorded as validation limitations, not changed here.

Release 3e1ac0a0 / 0.144.20 committed and pushed to origin then a-m-rose with
reviewed migration 0417. Commit governance passed with the existing stale
current-state warning. Automatic deployment started; no manual redeploy invoked.
Original unrelated client-view staging is preserved. Source code and output
claims remain pending live migration/new-definition verification.

Live verification: 0.144.20, migration 0417 applied; function has actor-only request
fence and no old automatic-delivery predicate. New run 890366d3 used current
definition, control pool, priority 90 and started within one second of admission.
Thus it no longer waited for the two occupied processing slots. No obsolete queued
run remained to cancel. However it failed the real prerequisite guard: platform
evaluation was interrupted during deployment and the replacement is running.

Replacement platform evaluation began at 17:09:21 UTC. Source assessment finished
before the recovery helper found anything to cancel; no cancellation was issued.
The bounded reviewed helper holds the existing scheduler lease for at most 170
seconds to avoid new competition, with finally/connection-termination release.
At 17:11 only platform evaluation was running; no database blockers. Software
protected state is input_failed pending that actual input's completion. No
publication success or complete restoration is claimed at this checkpoint.

Final recovery evidence: scheduler lease released normally. Replacement platform
evaluation finished, and current-definition overview 9c5614df completed at
17:20:24 UTC (started 17:19:00), priority 90, capacity:control. Generation 223fe334
published at 17:20:24, window deadline 17:30:41; protected reader current/completed.
Authenticated Software HTML at 17:20:56 returned 200 with completed-summary marker,
47,467 bytes, 2.187 seconds; logout confirmed. All three application services
healthy. The page is populated again and new capacity routing has executed
successfully. No serving runtime file replacements or manual schema applications.

Limits: 2.187 seconds misses ordinary <=1.5 s and hard <2 s targets. The successful
producer took about 84.5 seconds, exceeding the accepted 60-second freshness bound
even without queue delay. Existing control work, writer guards and the global
child limit can still delay publication. This release removes the observed
processing-pool wait and automatic-delivery self-invalidation; it does not certify
sustained freshness under every load or interruption. No broader tuning or more
tests were performed after the user's direction to reduce checking.
