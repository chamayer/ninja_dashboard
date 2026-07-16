# Active root work plan

This file is intentionally a template until root and Operations state are
reconciled.

## Status

- Planning — no active root-level code change found.

## Goal

- Coordinate the next repository-wide slice only if work crosses the root
  ingest/reporting boundary. Current documented work is Operations-scoped.

## Scope

- In:
  - Root coordination, release state, and cross-service changes when needed.
- Out:
  - Duplicating Operations implementation details.

## Files involved

- `operations/.work/plan.md` — current candidate implementation direction.
- Root VERSION and CHANGELOG — stack release authorities.

## Steps

- [x] Reconcile root BLUEPRINT with the current release.
- [x] Confirm root BLUEPRINT is stale and describes completed M0-era work.
- [ ] Keep this plan as a short router while work remains Operations-only.
- [ ] Expand it only when an approved task changes ingest, root SQL, Metabase,
  Compose, or other cross-service behavior.

## Decisions

- Context: Operations is a module-sized product inside a shared stack.
- Options considered:
  - Mirror all Operations details at root.
  - Keep one Operations plan and a root router only for cross-service work.
- Decision: Use the module plan as the detailed authority for Operations-only
  work.
- Rationale: Avoids duplicated, conflicting plan state.
- Consequences: Root work must explicitly identify cross-service dependencies.
- Root planning should route to the Operations plan when the active task is
  entirely module-scoped.
- Promote durable decisions to `docs/decisions/`.

## Validation

- [x] Root VERSION and recent CHANGELOG reviewed.
- [x] Root Git status reviewed.

## Current checkpoint

- Version 0.50.5 is current.
- The latest Operations-only UI work is complete; see
  `operations/.work/plan.md`.

## Remaining blockers

- Human approval of the next Operations UI slice.

## Next action

- Follow `operations/.work/plan.md` unless a cross-service requirement emerges.

## Completion

- Mark complete only after actual validation and already known commit hashes are
  recorded.
- Do not create an extra commit solely to add that commit's own hash here.
- Keep this completed plan until the next nontrivial root task replaces it.
