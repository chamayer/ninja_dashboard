# PLAN-027 — Isolated local development stack

## Goal

Run the complete Dashboard locally against isolated Postgres; make collection
manual and validate migrations before production deployment.

## Scope

- Add isolated Compose services, volume, credentials, and loopback ports.
- Provide a local environment template and setup/refresh/reset instructions.
- Keep all scheduled collection and scheduled Jobs disabled locally while
  preserving manual Jobs and source refreshes.
- Preserve current run/audit behavior; add no source snapshot policy.
- Document the production GitOps migration boundary. No production access,
  data copy, commit, or deployment.
- Reopened 2026-10-28: grant the local Operations runtime role read access to
  `ninja_core` after ingest creates the schema, including future tables, on
  every fresh Compose initialization. Keep this repair entirely within dev.

## Affected files

- `docker-compose.dev.yml`
- `docker-compose.dev.workstation-ca.yml`
- `docker/dev-postgres-init/10_operations_roles.sh`
- `docker/dev-postgres-init/grant_operations_ninja_core.sql`
- `.env.dev.example`, `.gitignore`
- `README.md`
- `ingest/config.py`, `ingest/operator_job_queue.py`
- `ingest/migrations.py`
- `ingest/register_job_definitions.py`
- `operations/apps/core/db/tenant.py`
- `operations/apps/core/migrations/0252_jobs_interrupted_local_recovery.py`
- `operations/config/settings/base.py`
- `operations/config/settings/dev.py`
- `sql/migrations/041_agent_compliance_demote_cross_client_conflicts.sql`
- `sql/migrations/042_agent_compliance_restore_online_in_wording.sql`
- `sql/migrations/044_agent_compliance_os_family.sql`
- `sql/migrations/047_agent_compliance_device_state_model.sql`
- `sql/migrations/081_eol_mapping_seed_and_candidates.sql`
- `sql/migrations/088_managed_eol_product_rules.sql`
- `docs/records/PLAN_REGISTRY.md`, `BLUEPRINT.md`

## Steps and decisions

1. Isolate local Compose names, ports, volume, and credentials.
2. Disable schedules locally but keep manual Jobs and refreshes available.
3. Bootstrap local roles and schema before Django migrations.
4. Keep shared session middleware inside tenant scope and stage cross-service
   migrations before starting app services.
5. Preserve fresh-install view contracts and document setup, refresh, and reset.
6. Validate Compose, registry, changed Python, whitespace, and local boot;
   do not configure or collect sources.
7. Apply local Ninja reference schema grants after `ingest-schema-bootstrap`,
   and require success before Operations starts.

## Validation

Compose config, registry validation, Python compilation,
and `git diff --check` pass. Clean local first boot completed staged SQL
and Django migrations. A second `docker compose up -d` completed without
reversing migrations. With DEBUG enabled, login POST redirected to the
dashboard successfully; Operations health and Django system checks pass. No
tests, live source collection, source API calls, production actions, commits,
or pushes were run.

## Checkpoint

The isolated local stack, role bootstrap, default-on scheduler gate, and
developer setup instructions were implemented and verified.
Tenant middleware now wraps session response handling; its debug assertion
permits only the exact parameterized tenant-initialization query. Fresh-install
compatibility fixes preserve historical view column order and
allow registered local Jobs snapshots through the replay-safe recovery policy
migration. The staged Compose bootstrap follows the discovered SQL/Django
migration dependencies and is repeatable. Repository contains unrelated dirty
files; preserve them. No source was configured or collected; no production
action occurred.

Reopened 2026-10-28 after `/orgs/all/` failed because local `operations_app`
lacked `USAGE` on `ninja_core`. The dev Compose path applies schema usage,
current-table SELECT, and default SELECT privileges after ingest creates the
schema. Production Compose, shared migrations, and production bootstrap files
are untouched. Compose rendering, plan-registry validation (30 entries), and
`git diff --check` pass. The dev stack is running; the grant service exited 0,
the exact directory query passed under `operations_app`, and Operations logged
an authenticated `GET /orgs/all/` with HTTP 200.

## Next action

No further work for this fix. The local stack is available at port 3003;
scheduled collection remains disabled.
