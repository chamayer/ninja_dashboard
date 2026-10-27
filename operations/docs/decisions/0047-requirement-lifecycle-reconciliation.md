# 0047 — Explicit confirmed use and shared lifecycle evidence

Status: Accepted; implemented locally under PLAN-014. Expanded validation and
deployment remain pending at the user's direction.
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

## Enforcement and status

The proposed enforcement is defined in
[PLAN-014's design](../../../docs/plans/PLAN-014-requirement-reconciliation.md):
one scoped lifecycle result, a single requirement gate with explicit operator
precedence, current-assessment closure and exact-identity auditing in the same
evaluation transaction. Synthetic PostgreSQL, runtime-role, cover, concurrency
and recovery acceptance is specified there. The implementation is present
locally; its expanded validation was deferred by the user. Production
enforcement is not claimed before deployment and acceptance.

PLAN-003 retains shared ledger/relationship redesign. Its proposed changes to
independent missing-installation cover are not silently implemented here.
No production migration or recalculation is authorized by accepting this ADR.

## Amends

Amends ADR-0036's unconditional cleanup exclusion with the explicit-confirmed-use
exception, preserves ADR-0032's operator action, and completes ADR-0035's
single-authority direction for requirement episode resolution under PLAN-014.
