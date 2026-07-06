# Goal

Build Operations M0 through the Django app/schema foundation.

# Why

Resume the Claude handoff for `operations` and continue the approved M0
implementation plan from `operations/BLUEPRINT.md`.

# Scope

- In: Django Operations app, models, migrations, admin wiring, health route,
  runbook stubs, seed/reference schema foundations.
- Out: public UI pages, ingest endpoint implementation, production deploy,
  commit/push.
- Current checkpoint: M0.3-M0.5 code is uncommitted WIP and validated locally.

# Files to change

- `operations/apps/core/` — Django app models, admin, migrations, views.
- `operations/config/settings/*.py` — app registration and lint cleanup.
- `operations/config/urls.py` — health endpoint route.
- `operations/docs/runbooks/*.md` — baseline finding type placeholders.
- `operations/BUILD_BLUEPRINT.md` — active implementation status.
- `operations/SESSIONS.md` — detailed session log.
- `operations/TODO.md` — Operations backlog.

# Steps

1. M0.3 auth/tenant foundation.
   - Status: done locally.
   - Includes `Tenant`, custom `User`, tenant-scoped auth through models,
     `AUTH_USER_MODEL`, admin wiring, migration `0001`.
2. M0.4 canonical entities.
   - Status: done locally.
   - Includes clients, policies, devices, client users, link tables, `Source`,
     admin wiring, migration `0002`.
3. M0.5 source/collector taxonomy and bindings.
   - Status: done locally.
   - Includes `Collector`, `FindingType`, source/collector instances,
     source bindings, admin wiring, migration `0003`.
4. Independent M0 stubs.
   - Status: done locally.
   - Includes `/healthz` and 10 runbook placeholder files.
5. M0.6 observations/current-state.
   - Status: done locally.
   - Add `entity_observations`, `dead_letter_observations`,
     `software_installations_current`, and refresh function strategy.
6. M0.7+ workflow, RLS, seeds, bootstrap clients, middleware, CI.
   - Status: M0.7 done locally; M0.8+ pending.
   - M0.7 includes workflow/audit tables and admin wiring.
7. M0.8 RLS roles, policies, and grants.
   - Status: done locally.
8. M0.9 tenant/client-scope middleware and tenant context helpers.
   - Status: done locally.
9. M0.10 admin seed groups, permissions, taxonomy, and finding types.
   - Status: done locally.
10. M0.11 bootstrap clients from `ninja_core.organizations`.
   - Status: pending approval.
11. M0 deployability checkpoint.
   - Status: done locally.
   - Ensures the container runs migrations with `operations_migrate`, then
     starts Gunicorn with `operations_app`.

# Open questions

- Whether RLS roles/grants are one SQL migration or separated from model
  migrations for easier local SQLite checks.

# Status

In progress. Do not start M0.11 bootstrap clients without an explicit approval
checkpoint. Before commit/deploy, validate the container on a Docker-capable
host because this workstation lacks Docker.
