# 0047 — Explicit confirmed use and shared lifecycle evidence

Status: Accepted. Baseline deployed as `0af8aac`; the reported-state fallback
amendment is implemented locally under PLAN-014 and awaits release approval
and production acceptance.
Date: 2026-10-27

## Context

PLAN-014 found disagreement between requirement verdicts, episode resolution
and offline findings. The offline calculation treated a recent collection
timestamp as device contact when contact was absent. A lifecycle label alone
also cannot distinguish contact aging from documentation/stopped-VM cleanup.

ADR-0032 promises that explicit confirmation of use returns a Computer to
coverage while retaining review status. ADR-0036 subsequently excluded all
`pending_cleanup` Computers. The user explicitly chose to restore checking
for confirmed use while preserving OS applicability and safety guards.

## Decision

1. A valid tenant-owned `in_use_confirmed=true` decision bypasses the cleanup
   requirement exclusion and returns that non-retired Computer to the coverage
   universe. It does not assert liveness, restore retirement, override OS support
   or exemptions, or authorize clearing, notification or execution through guards.
2. Lifecycle evaluation owns a shared result containing reason, qualified
   evidence and currentness. Offline/cleanup producers and requirement guards
   consume that result. `pending_cleanup` alone never establishes offline.
3. Collection time alone is not positive contact. Explicit reported state is
   qualified only under its registered evidence mode; unknown/conflicting
   evidence retains uncertainty rather than granting authority from an old label.
4. Requirement verdicts and desired episodes are computed together. Resolution
   consumes those decisions and reassesses disappeared conditions instead of
   applying another profile calculation or a fixed 48-hour recovery window.
5. On 2026-10-27 the user approved preparing explicit reported-state fallback
   when contact time is absent. The registered mode
   `direct_contact_state_fallback` opts in `agent.remote_access` and
   `agent.monitoring`. It uses recognized state only when the Computer has no
   qualified direct contact from any source. This keeps aged contact from being
   displaced by a contactless poll. Existing reported-state and hybrid/VM modes
   keep their selection rules. A fallback negative report establishes current
   offline state, without measuring offline duration or granting retirement,
   cleanup, a new extended-offline episode, or recovery of an existing offline
   episode. Its requirement guard says `offline:reported_without_duration`.
   Positive fallback can support normal recovery; source completeness,
   identity, tenant, retirement and operator guards still apply.

## Enforcement and status

The enforcement is defined in
[PLAN-014's design](../../../docs/plans/PLAN-014-requirement-reconciliation.md):
one scoped lifecycle result, a single requirement gate with explicit operator
precedence, current-assessment closure and exact-identity auditing in the same
evaluation transaction. Synthetic PostgreSQL, runtime-role, cover, concurrency
and recovery acceptance is specified there. The baseline is deployed; the
fallback candidate adds migration 0357's constrained registry/choice update,
shared evidence-selection support and matching data-quality checks. The
read-only summary recognizes qualified cleanup cover and preserves raw drift.
Current evidence, tests and the 102-Computer aggregate impact preview are in
the [acceptance record](../../../docs/records/PLAN-014-acceptance-2026-10-27.md).
No fallback production enforcement is claimed before approved deployment.

PLAN-003 retains shared ledger/relationship redesign. Its proposed changes to
independent missing-installation cover are not silently implemented here.
No production migration or recalculation is authorized by accepting this ADR.

## Amends

Amends ADR-0036's unconditional cleanup exclusion with the explicit-confirmed-use
exception, preserves ADR-0032's operator action, and completes ADR-0035's
single-authority direction for requirement episode resolution under PLAN-014.
Extends ADR-0010/0011's evidence modes with the explicitly opted-in fallback;
their existing four modes retain their behavior.
