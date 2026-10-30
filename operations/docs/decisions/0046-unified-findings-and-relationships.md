# 0046 — One findings ledger and typed finding relationships

Status: Proposed technical design; architectural direction approved in PLAN-003.
Date: 2026-10-27

## Context

Entity/admin findings share one operator queue but have separate authoritative
tables, subject/timestamp/handling contracts and query pipelines. The existing
union view loses admin subject/client context and state triggers ignore admin
assessments. UI-only grouping cannot resolve those differences. The user
approved consolidation and unified coverage/prerequisite handling during the
PLAN-003 review, while retaining domain-specific work and history.

## Options considered

- Keep both stores permanently and add more per-kind UI/reader adapters.
- Add a third findings authority and migrate both old ledgers into it.
- Extend existing findings, retain explicit legacy identity/reference mapping,
  and make relationships/state and queue selection common (proposed).

## Proposed decision

1. operations.findings is the only active finding ledger. Preserve UUIDs,
   versions, evidence, operator decisions, history and references. Structured
   subjects represent source/Job/configuration work without fake canonical
   entities; validate kinds/tenant ownership through the DB boundary and registry.
2. Preserve immutable legacy condition namespace and identity. They are
   compatibility/correlation metadata, not a storage split or operator filter.
   Namespace-aware assessment/participant joins and legacy references preserve
   history, notifications and action safety during conversion.
3. One narrow finding relationship contract supports covers and requires.
   Same-tenant composite FKs, self-link checks, serialized cycle validation and
   restricted DML enforce scope/graph integrity. The SQL projector is sole
   relationship/state writer. A tenant lock function runs before graph-
   affecting row locks; triggers assert that the transaction already holds the
   lock. Unchanged assessments use the touch path without graph serialization.
   Traversal is bounded.
4. Covers hides proven same-root fallout and gates child notifications;
   Requires retains independent work and gates only the rule's named action.
   Request, worker, and delivery boundaries recheck live link/rule versions;
   changes invalidate queued authority. Review, evidence refresh, investigation,
   resolution, and prerequisite repair remain available. Metadata/assessment
   uncertainty alone proves neither a condition nor recovery.
5. One queue selection supplies matching item counts, grouped pages, exports,
   home links and resolution scopes. Candidate records participate through a
   typed read adapter without being manufactured as findings. Keep the five
   categories and permission-gated domain actions.
6. Separate mechanical storage conversion from approved type/episode changes.
   No history erasure, guessed identity, notification replay or automatic
   source mutation. Keep pre-slice-2 readers disjoint by immutable namespace
   and assert identity-set/count conservation through cutover. Package M2–M4
   in one drained release; read-only processes declare supported version ranges,
   while writers and guarded actions require the exact contract generation and
   the database rejects stale callers.
   M5 semantic changes and M6 compatibility retirement each require separate
   approval and artifacts. Migration numbers are assigned after rebase.

## Consequences and enforcement

The [technical package](../plans/PLAN-003-technical-design.md) specifies fields,
mapping, controlled mutation/trigger enforcement, release boundaries and validation.
The [ledger](../plans/PLAN-003-consumer-ledger.md) enumerates repository/current
database consumers and the named alertability exception. Old admin storage
becomes protected rollback evidence; any compatibility relation is read-only
over the unified ledger, never a second write authority.

Readiness removal is approved and affects presentation only; retain technical
condition guards. The M5 `device_unenrolled` inventory/lifecycle-review meaning
is approved as non-alertable; M1–M4 preserve the current flag and M5 changes it
under the reviewed semantic manifest.
Recognized OS applicability, Computer identity algorithms and candidate lifecycle
stay with their owning plans; accepted scope is not license for unrelated repairs.
Runtime role/RLS, concurrency, exact-population/history and action-target tests
are mandatory before deployment. Application startup applies all packaged
migrations, so M2–M4 remain together and later M5/M6 files stay out of earlier
release artifacts.
The revised compatibility population, action guards, lock protocol, and version
gates address technical review findings R1–R4 at design level only. These two
user-approved product decisions do not authorize implementation, migration, or
deployment.

This record is not final approval of migration SQL, implementation or execution.
Keep Proposed until package review resolves the explicit gates and records
actual validation. No new dependency is required by this direction.

## Supersedes or superseded by

Extends ADR-0031's transactional state authority across all finding subjects.
Supersedes the permanent separate-admin-ledger constraint of the old queue
design. Does not replace ADR-0012's evidence/ownership rules, ADR-0040 client
mapping, ADR-0043 identity work, or recognized-OS applicability. Prospective
dependency handling supersedes the split Admin/Jobs child-closure mechanism;
historical closures and reasons remain intact.
