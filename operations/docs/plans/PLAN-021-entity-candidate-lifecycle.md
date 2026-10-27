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

Follow-up read-only verification on 2026-10-27 found 77 non-attached
`observed_only` candidates with matching source links. All 77 had active
observations and matching material hashes; 76 observations had a newer
`last_seen_at` than the candidate. Every source link's entity class differed
from the candidate's proposed class. See the aggregate-only
[review record](../../../docs/records/PLAN-021-candidate-review-2026-10-27/review.md)
and [query](../../../docs/records/PLAN-021-candidate-review-2026-10-27/queries.sql).
The mismatch makes the current projector's linked-candidate update invalid
under the resolved-entity composite class constraint.

## Scope

- Verify projection freshness for candidates that have source links but are
  not `attached`.
- Design and implement idempotent, auditable candidate withdrawal/reconciliation
  when a source observation becomes inactive, including existing stale rows.
- Withdraw a non-attached pending/observed-only proposal when its stable source
  identity is already linked to an entity of a different class; attach only
  when the linked and proposed classes match.
- Keep attached identity history and rejected decisions intact.
- Confirm queue counts and detail/read models exclude withdrawn candidates from
  actionable work while retaining their history.

## Out of scope

- Client resolver finding cleanup, which remains a PLAN-004 follow-up.
- Deleting canonical entities or source-link history when a source withdraws an
  observation.
- Production data mutation or deployment. Local migration code may be prepared
  for review; applying it remains separately approved.

## Validation

- Focused projection tests for active, inactive, reactivated, linked, rejected,
  and already attached candidates.
- Verify repeated runs are idempotent and withdrawal events retain a reason.
- Verify candidate queue counts and detail/history behavior.
- Review migration order and tenant/RLS behavior if a schema change is needed.

## Checkpoint

Defined 2026-10-26; implementation started 2026-10-27 after user direction to
complete PLAN-021. Migration 0355 adds `withdrawn` and versioned projector
`sync_entity_candidates_v2`; ingest defers until the new function exists,
and the legacy three-column function remains a compatibility wrapper,
preserving startup and rollback compatibility. The projector emits append-only
withdrawal events, preserves rejected/attached
states, attaches only class-matching links, and reopens explicitly reactivated
unlinked evidence. Python compilation, registry validation, and whitespace
checks pass. The focused candidate/admin run produced 24 passes when the
unrelated existing admin failure was excluded; the passing tests include five
PostgreSQL lifecycle/security cases against an isolated Testcontainers
database. The excluded test imports missing `ConditionPolicyActivationForm`
from `apps.core.admin`. Django system checks and migration autodetection pass.
Production database migration and data application were not run. Next: commit
the scoped implementation; any `origin` push must be separately approved and
explicitly include automatic deployment and migration 0355, then the same
commit goes to the secondary mirror. No production migration or data operation
has run.
