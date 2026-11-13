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
