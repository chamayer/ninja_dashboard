# PLAN-035 — Health enrichment evidence classification

## Status and goal

**Superseded by [PLAN-038](PLAN-038-ninja-device-health-as-record-detail.md) on 2026-11-02**; kept for provenance.

Ready; planning only, defined 2026-10-29. Registry owns lifecycle dates.
Implementation is not approved. Separate health evidence from independently
countable Computer source records without losing health values or provenance.

## Confirmed basis

ADR-0012/0013 distinguish entity attributes from relationships with attributes;
observations are evidence, not additional entities. Health already has its own
namespace (`device-health`), snapshot scope (`Ninja.device-health`), and history.
Its writer nevertheless copies the device's `agent.rmm`, `vm.guest`, or other
type. Inventory's broad type filter counts enrichment again. Presence already
excludes that namespace (migration 0098); other consumers have similar guards.
Health fields already have claim definitions/mappings (migration 0103), and
attribute authority policies depend on observation type. Changing only the
writer can therefore lose effective health values.

Read-only production investigation on 2026-10-29 found 16,243 counted Ninja
observations: 7,944 device/VM records plus 8,299 health observations. These are
snapshot evidence, not fixed acceptance counts. Separate review found 103
non-enrichment VM-host records excluded by the page's current filter.

## Scope and proposed contract

- Register a dedicated type, provisionally `device.health`, in existing data
  registries. Deny identity creation/matching, license consumption, requirement
  satisfaction, and independent lifecycle/presence authority. Verify enforcement
  at consumers, not merely registry flags; avoid spurious entity candidates.
- Preserve namespace, source identity tuple, observation IDs, attachment, raw
  payload, collection cadence, and snapshot withdrawal semantics. Keep the
  current/history observation store; create no new entity or enrichment table.
- Retain existing claims/effective projection. Explicitly register reviewed
  field authority for the new type. Device attributes remain device attributes;
  facts about entity pairs belong to relationships. Do not invent a single
  relationship for this mixed summary or migrate unrelated domains here.
- Use one shared, governed Computer-record eligibility contract across counts,
  search, source-record presentation, identity, and presence readers. Keep health
  accessible as enrichment evidence. Actual record totals retain relevant
  unlinked and withdrawn records; distinct Computer totals remain separate.
- Hudu layout eligibility and broader inventory reconciliation stay PLAN-012.
  This plan must not silently change card layout, labels, or other populations.

## Steps and affected areas

1. Reconcile Git/worktree and PLAN-007/012/004/019 ownership. Inventory writer,
   registry, claims/authority, candidate, lifecycle, shadow-view, evaluator, UI,
   and direct SQL consumers; resolve final type/eligibility design for approval.
2. Add a new reviewed Operations migration and update `ingest/core/device_health.py`.
   Review `ingest/observations.py`, claim/policy projectors, health compatibility
   views, `ingest/computer_listing.py`, and `operations/apps/core/views.py`.
   Change only consumers demonstrated to need adaptation; do not edit applied
   migrations. Preserve packaging of runtime files.
3. Design replay-safe reclassification of current health rows, including
   withdrawn rows. Preserve history/first-observed facts; audit classification
   changes without fabricating source events. Update projection hashes/material
   contracts correctly and bound any required re-projection.
4. Validate locally; then prepare release metadata and explicit production
   approval naming migration/re-projection effects. Document old-writer and
   mixed-version behavior, startup prerequisites, and rollback before rollout.
   Prevent an older writer silently reinstating inventory types.

## Validation and acceptance

- Synthetic PostgreSQL tests cover present/withdrawn and attached/unlinked
  health rows, repeat migration/collection, stale input, history, and RLS.
- Before/after health claims and effective reboot/patch/threat/health outputs
  retain approved values and authority; changed behavior needs explicit review.
- No new Computers, identity decisions, source attachments, candidates, agent
  coverage, or lifecycle transitions arise from the classification change.
- Inventory excludes enrichment once; legitimate endpoint/VM records remain.
  Health inspection still works and relevant totals reconcile independently.
- Run focused health/observation/projection/reader tests, Django checks, relevant
  lint, registry validation, and whitespace checks. Record actual evidence and
  unavailable checks; live verification requires authorization.

## Checkpoint and next action

Plan created from inspected code and aggregate reads; no runtime/schema changes,
reclassification, collection, or re-projection performed. Next: approve design
work and reconcile the consumer/policy ledger before implementation approval.
