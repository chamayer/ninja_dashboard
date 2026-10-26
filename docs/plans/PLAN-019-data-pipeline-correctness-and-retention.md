# PLAN-019 — Data pipeline correctness and source-record retention (PLAN-017 follow-up)

Registered 2026-10-26 as `ready` at the user's approval (PLAN-017 Phase 5,
Q2). **Resume gate:** executing this plan or any step requires separate
explicit user approval. Registering it authorizes no implementation and
changes no other plan's status: PLAN-002 and PLAN-005 stay `verify`, PLAN-006
and PLAN-007 stay `deferred`, PLAN-012 keeps F04.

## Goal

Fix the acquisition, publication and retention defects PLAN-017 confirmed,
in the agreed order, each with its own approval, test and (where needed)
reviewed migration.

## Evidence

[Phase 2 local reproductions](../records/PLAN-017-phase-2-results.md),
[Phase 3 production incidence](../records/PLAN-017-phase-3-results.md),
[Phase 4 prototypes and candidates](../records/PLAN-017-phase-4-verification.md),
[Phase 5 triage](../records/PLAN-017-phase-5-triage.md), decision record
[0045](../../operations/docs/decisions/0045-source-record-first-observed-and-change-trail.md).

## Items in order

| Step | Item | Change | Evidence and test |
| --- | --- | --- | --- |
| 1 | F07 | Correct `ingest/software_catalog.py`'s contract: in-place rerun, not identical clean rebuild; catalog rows are retained anchors (current design assumption) | Phase 2 check 9 |
| 1 | F01 | Record an empty `_FETCHERS` result as not-complete instead of `ok=True, rows=0`; no automatic withdrawal on empty | Phase 2 check 1 (invert) |
| 1 | F02 detection | A cap hit records the activity run as partial in the run log | Phase 2 check 3 |
| 1 | F03 | Enqueue software demand before advancing the activity cursor (enqueue is idempotent per computer) | Phase 2 check 4 (invert) |
| 1 | F09 assessment | Estimate all-source daily-presence row growth, retention and cost; then decide whether the shared writer records presence for every source | Read-only estimate needs approval |
| 2 | U04 | Generation fence on software reclassification targets: column, three producer conflict clauses, fenced acknowledgment; map F06's publication stages alongside, fencing a stage only where its race is confirmed | Phase 4 prototype, Phase 2 checks 5–6 |
| 3 | F08 | Separate sites snapshot scope, completed only when the sites fetch succeeds | Phase 4 prototype (option B) |
| 3 | F02 fix | Bounded per-filter continuation (design in the Phase 5 triage); prototype on the Phase 2 activity harness first. Until it ships the risk of losing events behind the cursor in a backlog over the cap is accepted | Phase 2 check 3 |
| 4 | Retention (ADR 0045) | First-observed anchor with basis and precision, then the significant-change trail after measuring which fields drive interval churn | Phase 2 check 10; new measurement needs approval |

F05 purge measurement stays in the root backlog under R08 and PLAN-006's
gate. F04 stays with PLAN-012 item 4.

## Coordination

The code touched belongs to the collection, Jobs and ingest areas of
PLAN-002/005/007. PLAN-019 coordinates with them and does not take over their
gates. PLAN-017's Phase 2/4 check suites are the starting tests: each
reproduction should fail (be inverted into a regression test) when its fix
lands.
