# Ninja Dashboard documentation map

This is the transition map for the new documentation layout. Existing source
documents remain available until their unique content has been reviewed.

| Current destination | Source material to compare | Purpose |
|---|---|---|
| `README.md` | Current code/layout and basic commands | Introduction, setup, major services, common commands |
| `docs/requirements.md` | REQUIREMENTS plus still-live agent-compliance requirements | Scope, constraints, acceptance criteria |
| `docs/architecture.md` | CONTEXT and implemented service/data design | Root ingest, Postgres, Metabase, and module boundaries |
| `docs/current-state.md` | Current code, CHANGELOG, and verified deployment state | Supported domains and known incomplete areas |
| `docs/operations.md` | HANDY_COMMANDS and PORTS after sensitive review | Deployment, maintenance, recovery, host prerequisites |
| `docs/decisions/` | Settled choices from REQUIREMENTS and design proposals | Architectural decision records |
| `.work/plan.md` | Reconciled root BLUEPRINT and active work | Root implementation plan, reasoning, checkpoint, and validation |
| `.work/backlog.md` | Open root/cross-service items after TODO triage | Deferred work only |
| `CHANGELOG.md` | Current CHANGELOG | Release-visible history |

## Operations module

| Current destination | Source material to compare | Purpose |
|---|---|---|
| `operations/docs/architecture.md` | Operations DESIGN plus implemented parts of BLUEPRINT | Concise Operations architecture guide; DESIGN remains detailed authority during transition |
| `operations/docs/requirements.md` | Parity and feature requirements from BLUEPRINT | Acceptance criteria without implementation diary |
| `operations/docs/operations.md` | Operations HANDY_COMMANDS after sensitive review | Deployment, RLS verification, maintenance |
| `operations/docs/decisions/` | Settled architectural choices | Decision records |
| `operations/.work/plan.md` | Reconciled BUILD_BLUEPRINT and latest active state | One active Operations implementation plan |
| `operations/.work/backlog.md` | Open Operations TODO items | Deferred work only |

## Material requiring resolution

- Root BLUEPRINT and SESSIONS lag later Operations and release state.
- Operations DESIGN declares itself authoritative while Operations README
  currently points to BLUEPRINT as canonical.
- Operations BLUEPRINT mixes requirements, implementation plan, completed
  status, contradictions audit, and historical material.
- The agent-compliance proposal set overlaps and is partly superseded by the
  Operations replacement. Requirements must be compared before archival.
- DASHBOARD_PLACEMENT_MAP remains marked as a draft; implementation status
  requires comparison.
- TROUBLESHOOTING is a session investigation, not a standing project document.
