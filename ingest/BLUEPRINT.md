# PLAN-014 — Requirement and lifecycle reconciliation

## Status, goal and scope

Release 0.129.3 prepared; commit authorized, push pending explicit reviewed
migration/deployment approval. The user requested finishing the
build with light checks and deferring broader validation. PLAN-014 stays active
until separately authorized production acceptance shows zero unexplained drift.
Preserve unrelated worktree edits; no release bump or production writes.

One lifecycle result supplies reason/evidence/currentness to lifecycle updates,
offline/cleanup findings and requirement guards. Requirements and recovery use
one coverage verdict calculation, retaining historical episodes and safety
guards. Explicit confirmed use restores checks in cleanup without asserting
liveness or bypassing OS policy, retirement, source or clearing safeguards.

## Authorities and coordination

- [Design](../docs/plans/PLAN-014-requirement-reconciliation.md).
- [Current build and retained baseline](../docs/records/PLAN-014-build-2026-10-27.md).
- [Earlier validation](../docs/records/PLAN-014-validation-2026-10-27.md) describes
  earlier code and does not validate this expanded build.
- ADR-0035/0036 and accepted ADR-0047 own verdicts and explicit confirmed use.
  OS/cleanup exclusion retains covered history; there is no clearing bypass.
- PLAN-014 precedes PLAN-003 in overlapping evaluator paths. PLAN-003 retains
  ledger/relationship redesign; PLAN-012 keeps inventory readers while its
  narrow resolution-reader follow-up is handled here. Identity work stays
  with PLAN-004/015/021.

## Confirmed build and affected files

`ingest/evaluator.py`, `ingest/requirement_state.py`, focused ingest tests,
Operations coverage labels/tests, new migration `0356_requirement_episode_identity`,
ADR-0047/0036 amendment, design and registry.

The evaluator serializes per tenant before a repeatable-read snapshot, shares
qualified lifecycle results and reconciles obsolete episodes with fresh
assessments. Full/single-Computer runs share offline recovery. Documentation
and stopped-VM cleanup do not become fabricated offline conditions; uncertainty
cannot grant clearing. Confirmation alone does not restore silent retirement.

Migration 0356 corrects exact entity/platform/episode matching and SQL NULL
handling without deleting history or changing the function signature/grants.
The read-only summary preserves raw counts and distinguishes guarded retention
from review. UI uses `N/A — Cleanup`; historical filter URLs remain accepted.
Existing Dockerfile directory copies include the changes; no dependencies,
ports or entrypoints changed. VERSION/CHANGELOG prepare release 0.129.3.

## Validation and next action

Syntax parsing and `git diff --check` pass. Running scoped tests were stopped
at the user's request. Integrated tests are prepared; no final PostgreSQL,
Django, migration, rendering, concurrency or performance acceptance is claimed.
Earlier passing batches do not establish acceptance of this expanded build.

Next action: present the local build, then run the design's integrated matrix
when requested, using disposable synthetic PostgreSQL data and real roles/cover
triggers. Include rollback, full/single scope, snapshot serialization,
confirmation on/off, uncertainty and recovery. Review migration 0356 and the
unrelated oversized root blueprint before release. Separate commit and push
approvals must cover pending migrations/automatic deployment; production
recalculation has its own approval. No production change or completion claimed.
