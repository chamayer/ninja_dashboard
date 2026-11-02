# Repository cleanup summary — 2026-10-20

## Purpose

- Reduce root and Operations working-folder clutter without deleting data.

## Preserved archives

- `docs/archive/workspace-cleanup-2026-10-20/` contains the six completed
  Agent Compliance design documents, the previous root `BLUEPRINT.md`, and
  the former root `.work/plan.md` and `.work/backlog.md`.
- `operations/docs/archive/workspace-cleanup-2026-10-20/` contains the
  previous Operations `BLUEPRINT.md`, former Operations plan/backlog, and the
  September Jobs research/SQL bundle.
- No archive contents were rewritten or deleted; Git history also retains the
  original paths.

## Current conventions

- `BLUEPRINT.md` is the active handoff.
- `TODO.md` is deferred work and `SESSIONS.md` is history.
- `docs/archive/` is preserved historical material.
- `.work/` is temporary probes only, never a handoff or backlog source.

## Remaining intentional workspace material

- Root `.work/` contains two preserved classes of material, classified on
  2026-10-20:
  - Ten tracked October design notes record the software/finding and central
    work-queue workstreams. They remain in place because active repository
    references (including ADR-0030 and finding-state migration/model
    documentation) still point to them. Move them only as a coordinated
    archival change that updates those references.
  - Twenty-one untracked July-August SQL/Python diagnostics (`probe_*` and
    `bootstrap_intel.py`) have no live repository references. They remain
    local, temporary research artifacts and must not be treated as handoff or
    backlog material.
- No root `.work/` artifact was deleted or rewritten during classification.

## Validation

- Archive inventory and reference checks were run after the move.
