# Goal

Continue the Operations M0 build from the Claude handoff while keeping the
root repo docs as a resumable checkpoint.

# Why

Operations is a module-sized build inside `ninja-dashboard`; the detailed
architecture already lives in `operations/BLUEPRINT.md`, and the active
implementation plan should not overwrite unrelated root project context.

# Scope

- In: Operations M0 Django app/schema foundation.
- In: root pointer docs required by `DEVELOPMENT.md`.
- Out: agent compliance, patch dashboards, existing ingest domains.
- Detail: `operations/BUILD_BLUEPRINT.md`.

# Files to change

- `operations/BUILD_BLUEPRINT.md` — detailed active implementation plan.
- `operations/SESSIONS.md` — detailed Operations session journal.
- `operations/TODO.md` — Operations-specific backlog.
- `operations/...` — code files named in the module blueprint.

# Steps

1. Keep this file as the root checkpoint.
2. Follow `operations/BUILD_BLUEPRINT.md` for detailed M0 slices.
3. Checkpoint for approval before each new M0 slice.
4. Mirror only repo-level status into root `SESSIONS.md` / `TODO.md`.

# Open questions

- None.

# Status

In progress. Operations M0 foundation, M0.11/M0.12 bootstrap/UI scaffold,
M1.1 device bootstrap, initial M1 queues/pages, and the v0.35.5 redeploy
session fix are committed and pushed through `746770e`. Resume from
`operations/BUILD_BLUEPRINT.md`: live Portainer validation is the active
checkpoint before the next implementation slice.
