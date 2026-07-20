# Active root work plan

Router only. Current work is Operations-scoped; see
`operations/.work/plan.md`.

## Status

- Planning — no active root-level code change. Awaiting selection of the next
  slice.

## Goal

- Coordinate the next repository-wide slice only if work crosses the root
  ingest/reporting boundary.

## Scope

- In:
  - Root coordination, release state, and cross-service changes when needed.
- Out:
  - Operations-only implementation details.

## Files involved

- `operations/.work/plan.md` — module-scoped detail authority.
- Root `VERSION`, `CHANGELOG.md` — stack release authorities.

## Steps

- [ ] Keep this plan as a short router while work remains Operations-only.
- [ ] Expand it only when an approved task changes ingest, root SQL, Metabase,
  Compose, or other cross-service behavior.

## Decisions

- Use the module plan as the detailed authority for Operations-only work.
- Rationale: avoids duplicated, conflicting plan state.
- Promote durable decisions to `docs/decisions/`.

## Current checkpoint

- Stack version **0.63.0** is current.
- Recent releases: 0.60.0 rare_recent reframe + classifier config; 0.61.0
  presence matview rename; 0.61.1 `/software` 500 fix; 0.62.0 Finding
  timestamps + dashboard trend arrows; 0.62.1 hotfix for missing
  `resolved_at`; 0.63.0 `device_offline` evidence enrichment.
- Track UI-2 waves **D / E / F** all landed. **G (business data capture)** and
  **H (dashboard maturity)** are deferred together in the backlog.
- Root-level candidates outstanding: ingest domain separation; legacy
  agent-compliance cutover; Metabase card parity audit (informs Operations
  build-out ahead of Metabase deprecation).

## Remaining blockers

- Human approval of the next slice.

## Next action

- Follow `operations/.work/plan.md` unless a cross-service requirement emerges.
- Untracked reference material at repo root:
  `Ninja+RMM+Public+API+v2.0.5+Device+Filter+Syntax.pdf` — likely input for a
  future ingest filter change; not currently scoped.

## Completion

- Keep this plan until the next nontrivial root task replaces it.
