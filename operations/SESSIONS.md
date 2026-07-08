# Operations Sessions

Detailed Operations module development journal. Root `../SESSIONS.md` keeps
only project-level pointers.

---

## 2026-07-08 — Platform foundation Batch A3 (Phase 4)

**Why:** Create all new platform tables needed by the evaluator, identity
resolver, queue governance, and notification engine.

**Work completed:**

- Migration 0014: CreateModel for 7 new tables — CoverageRequirement,
  AdminFinding, QueueRegistry, IdentityCandidate, NotificationRule,
  NotificationState, NotificationEvent. Unique/index constraints added.
  RunPython enables RLS + grants on 6 tenant-scoped tables (not queue_registry).
  RunPython seeds 4 queues into queue_registry.
- models.py: 7 new model classes added (CoverageRequirement, AdminFinding,
  QueueRegistry, IdentityCandidate, NotificationRule, NotificationState,
  NotificationEvent).

**Deployed:** v0.38.0

---

## 2026-07-08 — Platform foundation Batch A2 (Phase 3)

**Why:** Extend FindingType and Finding models with platform evaluator fields —
finding_class/source_module/auto_resolvable on types; condition_key/confidence/
last_detected_at/client FK on findings. Seed 6 new finding types.

**Work completed:**

- Migration 0013: AddField finding_class, source_module, auto_resolvable on
  FindingType. AddField condition_key (with unique partial constraint on active
  findings), confidence, last_detected_at, client FK on Finding.
  RunPython back-fills all 10 existing types with entity class + source_module.
  Inserts 6 new finding types (4 entity, 2 admin).

**Deployed:** v0.37.0

---

## 2026-07-08 — Platform foundation Batch A1 (Phases 1–2)

**Why:** Three-state staleness model for software_installations_current (fixes
active data-loss risk — refresh function was hard-deleting missing rows).
Universal lifecycle columns on devices, device_links, and clients per DESIGN.md §3.4.

**Work completed:**

- Migration 0011: rewrote `operations.refresh_software_installations_current()`
  to use stale/unmark pattern instead of DELETE. Added stale_since, stale_reason,
  deleted_at, deleted_reason columns to software_installations_current.
- Migration 0012: added missing_since to device_links; added created_at,
  created_reason, updated_at, updated_reason, stale_since, stale_reason,
  deleted_reason to both devices and clients.
- Updated models.py to reflect all new fields.

**Deployed:** v0.36.0

---

## 2026-07-07 — Fleet overview dashboard

**Why:** The all-clients view was a plain flat table. With Operations
reframed as a data browser, the front door should show fleet state at a
glance.

**Work completed:**

- Added 4 summary tiles to the all-clients view: Clients, Devices (with
  type breakdown), Sources (distinct sources with per-source client count),
  Findings (global open count).
- Added Sources column to the client table showing which systems each
  client is linked to.
- Moved shared tile CSS out of the per-client branch so both views share it.
- Removed slug column from client table (slug belongs on the detail page,
  not the fleet list).

**Validation:** Django check, ruff, template load smoke test all passed.

**Deployed:** `8b452f7`, pushed to both remotes. Browser check pending.

---

## 2026-07-07 — Product direction reframed to operational data app

**Why:** We were drifting toward describing Operations as mainly an issue
resolution console. The intended product is broader: it should become the
primary app for viewing and working with the operational data model.

**Decision:**

- Operations is the operational data browser and control plane.
- Operators should use it to view current canonical clients, devices, users,
  software, sources, observations, evidence, status, history, findings, and
  decisions.
- Metabase remains useful for exploratory BI, broad historical analytics, and
  arbitrary charting.
- Operations pages should be model-aware and workflow-aware. If a page helps
  someone understand or operate the managed environment, it belongs here. If it
  is only a generic chart over arbitrary data, it likely belongs in Metabase.

**Pending:** Next approved UI slice should start from this framing, likely a
top-level Operations dashboard/data-browser front door.

---

## 2026-07-07 — Client landing identity coverage WIP

**Why:** The client landing page only showed canonical client identity and
`client_links`. That was too thin for Operations' purpose as the
operator-facing identity-resolution surface.

**Work completed locally:**

- Added identity coverage aggregates to `org_index` for:
  - device source links by source;
  - source binding enabled/disabled counts;
  - canonical client users and external user links;
  - active `unlinked_external_identity` findings tied to this client's
    source bindings.
- Added a compact "Identity coverage" section to the per-client landing page.
- Kept the change summary-level; no new detail pages or schema changes.

**Validation:**

- `python operations\manage.py check --settings=config.settings.dev` passed.
- `python operations\manage.py makemigrations --check --dry-run --settings=config.settings.dev`
  passed.
- `python -m ruff check operations\apps\core\views.py` passed.
- Template load smoke for `org_index.html` passed.

**Deployed:** Committed as `a8bf257`, pushed to both remotes, Portainer
auto-update deployed it. Container healthy. Browser validation pending.

---

## 2026-07-07 — Device list pagination/search WIP

**Why:** Live Operations logs showed `/orgs/uta/devices/` returned a large
device-list page and a Gunicorn worker timed out shortly afterward. The view
loaded every device for a client and filtered rows in browser JavaScript.

**Work completed locally:**

- Changed `org_devices` to filter/search/paginate in Django instead of
  materializing all client devices.
- Added server-side search by hostname/serial.
- Added server-side device type filtering.
- Added pagination at 100 devices per page.
- Updated the device-list template to use GET controls and pagination links.
- Added backlog notes for broader client identity coverage and a future
  top-level Operations summary page.

**Validation:**

- `python operations\manage.py check --settings=config.settings.dev` passed.
- `python operations\manage.py makemigrations --check --dry-run --settings=config.settings.dev`
  passed.
- `python -m ruff check operations\apps\core\views.py` passed.
- `python operations\manage.py shell --settings=config.settings.dev -c "from django.template.loader import get_template; get_template('org_devices.html'); print('template_ok')"`
  passed.

**Live validation:** Portainer deployed `cfa1767`; `/orgs/uta/devices/`
returned 47,649 bytes versus the previous 504,547-byte render. Operations
remained healthy. A later Gunicorn timeout showed `no URI read`, so it was
recorded as non-blocking idle connection noise, not a page render failure.

**Pending:** None for this slice.

---

## 2026-07-07 — Live Operations validation

**Why:** Continue the active checkpoint after pushing `55cda73`.

**Validation completed:**

- Pushed docs checkpoint `55cda73` to both `origin/master` and
  `a-m-rose/master`.
- Configured SSH key login from the workstation to `amrose@10.61.50.28` via
  local alias `am-ch-01`.
- Confirmed SSH login lands on host `am-ch-01` as `amrose`, with `docker`
  group membership available.
- Confirmed Operations is reachable from the workstation at
  `http://10.61.50.28:3002/`.
- Confirmed Gunicorn serves the app and unauthenticated `/` and
  `/orgs/all/` requests redirect to `/admin/login/`.
- Confirmed `ninja-operations`, `ninja-ingest`, `ninja-metabase`, and
  `ninja-postgres` containers are running healthy.
- Confirmed host-loopback health:
  `curl -fsS http://127.0.0.1:8091/healthz` returned `{"status": "ok"}`.
- Confirmed all Operations migrations through `0009_rename_device_kind_to_device_type`
  are applied.
- Confirmed startup logs show:
  - migrations ran as `operations_migrate`;
  - initial admin password sync skipped because already current;
  - client bootstrap saw `created=0 updated=0 unchanged=75 total=75`;
  - device bootstrap saw `created=0 updated=2 unchanged=5656 orphaned=0 total=5658`;
  - static files collected and Gunicorn started.
- Confirmed Postgres counts:
  - `operations.clients`: 75
  - `operations.client_links`: 75
  - `operations.devices`: 5658
  - `operations.device_links`: 5658

**Notes:**

- Plain `docker ...` works over SSH because `amrose` is in the `docker`
  group; do not use `sudo docker ...`.
- Django ORM counts from the runtime app role can return zero without tenant
  context because RLS is active. Use `tenant_context(1)` or Postgres-side
  count queries for validation.
- SSH commands currently print a local `known_hosts` update warning even when
  the remote command succeeds:
  `hostfile_replace_entries: mkstemp: Permission denied`.
- Logs contain one Gunicorn worker timeout at `2026-07-07 16:49:44` after a
  large `/orgs/uta/devices/` page response; service recovered and health
  checks continued passing.

**Pending:** User-facing same-password redeploy session preservation still
needs browser confirmation after a future Portainer redeploy.

---

## 2026-07-07 — Checkpoint docs reconciled to committed Operations state

**Why:** The active build blueprint and TODO still described M0.11/M0.12/M0.15
as pending, but the commit history showed M0.11/M0.12, device bootstrap, and
several M1 UI/data pages were already committed and pushed.

**Work completed locally:**

- Updated `operations/BUILD_BLUEPRINT.md` to make live Portainer validation
  the active checkpoint.
- Moved obsolete M0.11/M0.12/current-WIP items out of `operations/TODO.md`.
- Recorded completed Operations slices through `746770e`.

**Current checkpoint:**

- Validate commit `746770e` in the Portainer-managed `ninja-dashboard` stack.
- Confirm migrations/bootstrap, `/healthz`, populated clients/devices, and
  same-password redeploy session preservation.
- Choose the next M1 implementation slice only after that validation is known.

**Validation:** Documentation-only change; no code checks required.

**Pending:** Live Portainer validation.

---

## 2026-07-07 — Admin session preservation across redeploys

**Why:** The Operations container startup command re-applied the initial admin
password on every redeploy. Django salts each password hash, so even the same
password produced a new stored hash and invalidated existing admin sessions.

**Work completed locally:**

- Updated `set_initial_admin_password` to check the current admin password
  before calling `set_password()`.
- Kept flag repair behavior for `is_active`, `is_staff`, and `is_superuser`.
- Added command output that reports whether the password or flags changed.

**Validation:**

- `python operations\manage.py check --settings=config.settings.dev` passed.
- `python operations\manage.py makemigrations --check --dry-run --settings=config.settings.dev`
  passed.
- A targeted two-run command test confirmed the second run skips and the
  stored password hash remains unchanged.
- `python -m ruff check operations` still fails on pre-existing unrelated lint
  in `forms.py`, `views.py`, and `bootstrap_devices_from_ninja.py`.

**Pending:** Browser-confirm same-password redeploy session preservation after
a future Portainer redeploy. Commit `746770e` has been pushed to both remotes.

---

## 2026-07-06 — M0 deployability checkpoint

**Why:** We realized M0 cannot be considered healthy just because schema
migrations validate locally. The blueprint requires a Portainer-deployed
Operations container, and the M0.8 RLS/role migration cannot safely run under
the runtime `operations_app` role.

**Work completed locally:**

- Updated `operations/entrypoint.sh` to run migrations with
  `OPERATIONS_MIGRATE_DB_USER` / `OPERATIONS_MIGRATE_DB_PASSWORD`, then switch
  back to `OPERATIONS_DB_USER` / `OPERATIONS_DB_PASSWORD` before launching
  Gunicorn.
- Updated `operations/config/settings/prod.py` to require both runtime and
  migration DB passwords in production.
- Updated `docker-compose.yml` comments to document the Portainer `.env`
  contract for both role pairs.

**Required `.env` keys for deploy:**

- `OPERATIONS_DB_USER=operations_app`
- `OPERATIONS_DB_PASSWORD=...`
- `OPERATIONS_MIGRATE_DB_USER=operations_migrate`
- `OPERATIONS_MIGRATE_DB_PASSWORD=...`
- Existing required keys still apply: `OPERATIONS_SECRET_KEY` and
  `OPERATIONS_ALLOWED_HOSTS`.

**Validation:** Local Docker is unavailable on this workstation, so container
build/start was not exercised here. Python/Django validation remains required
after this change.

**Pending:** Build/start through Docker or Portainer on a Docker-capable host,
then hit `/healthz` on `127.0.0.1:8091`.

---

## 2026-07-06 — M0.10 seed groups, permissions, and taxonomy

**Why:** Continue the approved Operations M0 build after middleware. M0.10
adds idempotent seed data for local auth groups/permissions and the initial
source/collector/finding taxonomy.

**Work completed locally:**

- Added migration `0007_seed_m0_reference_data`.
- Seeds default tenant `id=1`, `slug=amrose`.
- Creates/updates the 15 custom Operations permissions from §5.4 on the
  `operations.User` content type.
- Creates global Django groups:
  - `admin` with all custom Operations permissions.
  - `operator` with `view_*`, decision, merge, finding, client policy, and
    query permissions.
  - `viewer` with `view_*` and `run_queries`.
- Seeds `sources`: `Ninja`.
- Seeds `collectors`: `internal-ingest`, `ninja-hosted-script`.
- Seeds one tenant-scoped `collector_instances` row for `internal-ingest`.
- Seeds the 10 baseline `finding_types` with runbook paths.
- Seeds an `admin` superuser with an unusable password for break-glass setup
  until a real password is set intentionally.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --noinput` applied migration `0007`
  to the local SQLite skeleton.
- Local seed sanity check confirmed: 1 tenant, groups
  `admin`/`operator`/`viewer`, `Ninja` source, 2 collectors, 1 collector
  instance, 10 finding types, and admin user present.

**Pending:** M0.11 bootstrap clients from `ninja_core.organizations`.
Requires approval before implementation.

---

## 2026-07-06 — M0.9 tenant/client-scope middleware

**Why:** Continue the approved Operations M0 build after RLS roles/policies.
M0.9 adds runtime tenant scoping, client-scope resolution, management-command
tenant context helpers, query helpers, and scope decorators.

**Work completed locally:**

- Added `apps.core.db.tenant` with:
  - `set_local_tenant(tenant_id)`
  - `current_tenant_id()`
  - `tenant_context(tenant_id)`
  - `client_scoped_query(request, sql, params)`
  - `all_clients_query(sql, params)`
  - development query-time tenant GUC assertion wrapper.
- Added `TenantMiddleware`.
  - Resolves tenant from authenticated user when present, otherwise tenant 1.
  - Opens the outer transaction itself on Postgres before issuing
    `SET LOCAL operations.tenant_id = %s`, because Django `ATOMIC_REQUESTS`
    wraps views but not normal middleware.
  - Skips the wrapper on `/healthz`.
- Added `ClientScopeMiddleware`.
  - Resolves `/orgs/all/...` to all-client mode.
  - Resolves `/orgs/{slug}/...` to `request.current_client`.
- Added `require_client_scope` and `require_admin` decorators.
- Wired middleware into `config/settings/base.py` after authentication.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --plan` reports no planned operations.

**Pending:** M0.10 admin seed groups, permissions, taxonomy, and finding
types. Requires approval before implementation.

---

## 2026-07-06 — M0.8 RLS roles, policies, and grants

**Why:** Continue the approved Operations M0 build after M0.7 workflow/audit
tables. M0.8 adds the Postgres role, RLS, and privilege layer required by
§6.3 and the M0 DB grants section.

**Work completed locally:**

- Added migration `0006_rls_roles_policies_grants`.
- Postgres-only migration path ensures roles exist:
  `operations_app`, `operations_migrate`, `operations_readonly`,
  `operations_health`, `metabase_ro`, and `ninja_ingest`.
- Enables and forces RLS on tenant-scoped tables with a fail-closed
  `tenant_isolation` policy using
  `current_setting('operations.tenant_id', TRUE)::bigint`.
- Enables and forces RLS on `software_catalog` with a layered
  `tenant_or_global` policy.
- Applies broad app/read-only grants and restricted `ninja_ingest` grants for
  `entity_observations`, `dead_letter_observations`, `run_log`, and
  `refresh_software_installations_current(bigint)`.
- SQLite/local migration path no-ops the Postgres SQL.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --noinput` applied migration `0006`
  to the local SQLite skeleton.

**Pending:** M0.9 tenant/client-scope middleware and tenant context helpers.
Requires approval before implementation.

---

## 2026-07-06 — M0.7 workflow and audit tables

**Why:** Continue the approved Operations M0 build after M0.6 observation
tables. M0.7 adds the operator workflow, catalog, findings, notification,
secret, audit, and run tracking tables.

**Work completed locally:**

- Added `SoftwareCatalog` as the layered global/tenant taxonomy table with
  partial uniqueness for global and tenant rows.
- Added `SoftwareDecision`.
- Added `MergeCandidate` with `member_snapshots` and historical
  `member_observation_ids`.
- Added `Finding` with subject polymorphism fields and finding details JSON.
- Added `SuppressionRule`, `NotificationRoute`, `Secret`, `AuditLog`, and
  `RunLog`.
- Added admin registrations for all M0.7 tables.
- Added migration
  `0005_notificationroute_auditlog_finding_mergecandidate_and_more`.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --noinput` applied migration `0005`
  to the local SQLite skeleton.

**Pending:** M0.8 RLS roles, policies, and grants. Requires approval before
implementation.

---

## 2026-07-06 — M0.6 observations and current-state table

**Why:** Continue the approved Operations M0 build slice after the module-doc
checkpoint. M0.6 adds the ingest observation landing tables and the
software-install current-state table/function required by §4.5 and §4.7.

**Work completed locally:**

- Added `EntityObservation` with promoted nullable `client_id` and
  `device_id`, collector/source binding references, raw/canonical JSON, batch
  idempotency fields, and the unique key
  `(tenant_id, collector_instance_id, batch_id, observation_hash)`.
- Added `DeadLetterObservation` for unresolved/rejected ingest envelopes.
- Added admin inspection surfaces for both tables.
- Added migration `0004_deadletterobservation_entityobservation`.
- Added Postgres-only migration SQL for
  `operations.software_installations_current` with composite primary key
  `(tenant_id, client_id, device_id, canonical_name)`.
- Added Postgres-only
  `operations.refresh_software_installations_current(bigint)` as a
  `SECURITY DEFINER` function. SQLite/local migration planning no-ops this
  SQL path.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --plan` passed.

**Pending:** M0.7 workflow/audit tables. Requires approval before
implementation.

---

## 2026-07-06 — M0.3-M0.5 local build WIP

**Why:** Resume Claude handoff `a2a3de93-e7af-4d46-a2dd-b2c156f12c9a` for
the Operations M0 build.

**Work completed locally:**

- M0.3 custom auth/tenant foundation:
  - `Tenant`
  - custom `operations.User`
  - tenant-scoped `UserGroup` / `UserPermission`
  - `AUTH_USER_MODEL`
  - admin wiring
  - migration `0001_initial`
- M0.4 canonical entity/link foundation:
  - `Source`
  - `Client`, `ClientLink`, `ClientPolicy`
  - `Device`, `DeviceLink`
  - `ClientUser`, `ClientUserLink`
  - admin wiring
  - migration `0002_source_client_clientpolicy_clientuser_device_and_more`
- M0.5 source/collector taxonomy and binding foundation:
  - `Collector`
  - `FindingType`
  - `SourceInstance`
  - `CollectorInstance`
  - `SourceBinding`
  - admin wiring
  - migration `0003_collector_findingtype_collectorinstance_and_more`
- Independent M0 stubs:
  - `/healthz`
  - 10 runbook placeholder files.

**Validation:**

- `python operations\manage.py check` passed.
- `python operations\manage.py makemigrations --check --dry-run` passed.
- `python -m ruff check operations` passed.
- `python operations\manage.py migrate --plan` passed.

**Process correction:** This build WIP was created before the module-doc
delegation rule was added to `DEVELOPMENT.md`. Future Operations slices must
checkpoint here and in `operations/BUILD_BLUEPRINT.md` before edits.

**Pending:** M0.6 observations/dead-letter/current-state schema and refresh
function. Requires approval before implementation.
