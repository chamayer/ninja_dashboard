# PLAN-021 — Generic entity candidate lifecycle reconciliation

## Goal

Keep the generic entity-candidate queue and status aligned with the current
source observation and source-link state, while retaining an audit trail for
withdrawn evidence.

## Measured state

Read-only production measurement on 2026-10-26:

- 576 pending candidates and 12 observed-only candidates matched inactive
  source observations and had no entity source link.
- 19 pending and 3,878 observed-only candidates matched active observations.
- 74 observed-only candidates had a source link but were not marked attached;
  their timing relative to the latest projection has not been established.
- No active source observation lacked both a candidate and a source link.
- Attached candidates without a current observation still had source links and
  represent retained identity history; they are not classified as stale.

## Scope

- Verify projection freshness for candidates that have source links but are
  not `attached`.
- Design and implement idempotent, auditable candidate withdrawal/reconciliation
  when a source observation becomes inactive, including existing stale rows.
- Keep attached identity history and rejected decisions intact.
- Confirm queue counts and detail/read models exclude withdrawn candidates from
  actionable work while retaining their history.

## Out of scope

- Client resolver finding cleanup, which remains a PLAN-004 follow-up.
- Deleting canonical entities or source-link history when a source withdraws an
  observation.
- Production data mutation, deployment, or schema migration until separately
  approved after implementation is reviewed.

## Validation

- Focused projection tests for active, inactive, reactivated, linked, rejected,
  and already attached candidates.
- Verify repeated runs are idempotent and withdrawal events retain a reason.
- Verify candidate queue counts and detail/history behavior.
- Review migration order and tenant/RLS behavior if a schema change is needed.

## Checkpoint

Defined 2026-10-26 as ready. No implementation or production state change is
authorized by this plan entry. Resume only after reviewing the 74 linked but
not-attached candidates and separately approving implementation.
