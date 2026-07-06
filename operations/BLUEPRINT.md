# Operations — BLUEPRINT

**Status:** draft v0.9 — all §5 blocks decided; three review passes
resolved (see changelog).
**Owner:** Chaim Tabak
**Repo:** `ninja-dashboard/operations/`
**Version at v1 launch:** `0.1.0`

---

## 1. Purpose

Operations is the write-side companion to Metabase in the ninja-dashboard
stack. Metabase renders read-only analytics; Operations handles everything
that requires a **decision, a policy change, or a workflow**:

- Software inventory classification and Approve / Reject / Investigate
  decisions per client.
- Device merge review across sources (Ninja, SentinelOne, LogMeIn,
  ScreenConnect, and future hypervisor / directory sources).
- Per-client policy editing (authorized RMM, authorized AV, agent SLA).
- Findings triage (assignment, status, suppression, runbooks).
- Ad-hoc query surface for questions Metabase can't answer without a
  dashboard change.

It replaces two failure modes of the current tooling: (a) the
`analyze_inventory.py` + Excel/VBA/CSV pipeline, and (b) the "there is no
write UI, so operators go into psql" gap in the agent compliance domain.

The stack it lives in is unchanged: same Compose file, same Postgres,
same deploy pipeline, same `.env`. Operations is a fourth service
alongside Postgres, Metabase, and ingest.

## 2. Non-goals (v1)

Locked. These are deliberate scope kills so v1 ships:

- **Multi-tenant SaaS.** The seam is preserved (§4.16), but there is no
  sign-up flow, no per-tenant admin, no billing, no plan gating.
- **Public / internet access.** LAN-only in v1. Adding public access
  later is reverse proxy + TLS + rate limiting — not a rewrite.
- **Real-time / websocket updates.** Server-rendered pages with HTMX
  polling only.
- **Mobile-optimized UI.** Desktop-first, responsive but not mobile-first.
- **Internationalization.** English only.
- **CIS Controls beyond 1.1, 1.2, 2.1–2.5.** No DHCP-log ingest, no
  library allowlisting, no script allowlisting in v1.
- **Ad-hoc question authoring in Metabase style.** The Queries page runs
  whitelisted saved queries only; no raw-SQL from browsers.

## 3. Architecture at a glance

```
Ninja API ──► ingest (Python) ──► Postgres ◄── Metabase (3001)  ──► browser
                                        ▲            ▲
                                        │            │ deep-links
                                        │            ▼
                                        └───────► operations (3002 / 8091) ──► browser
                                                      │
                                                      ▲── collector ingest (bearer token)
                                                          from Ninja scripts, native agents,
                                                          direct pulls, file drops
```

- **Framework:** Django + Django REST Framework, HTMX for interactivity,
  Whitenoise for static assets, Gunicorn as the WSGI server.
- **Container:** `operations`. Service and container name deliberately
  brand-neutral to support the appliance rebrand path (§4.16).
- **Ports:**
  - `3002` — UI + API, LAN.
  - `8091` — internal health / ops endpoints, loopback only.
- **Schema:** `operations` in the ninja Postgres cluster. Django owns it;
  reads from `ninja_core`, `ninja_patches`, `ninja_inventory`,
  `ninja_activities`, `ninja_agent_compliance` via `Meta: managed = False`
  models generated with `inspectdb`.
- **Auth:** Session for UI, bearer tokens for programmatic. Local auth
  backend v1; SSO backend slot reserved (§4.2).
- **Config source:** shares `/amr-ch-01_data/ninja-dashboard/.env`. No
  new secrets file.
- **Deploy:** Portainer auto-pull on push, same as the rest of the stack.

## 4. Locked decisions

Everything in this section is settled. Not up for review — recorded for
future contributors.

### 4.1 Framework

**Django** (not Flask, not FastAPI).

- Django admin is a working operator UI for superuser-tier plumbing on
  day one (users, groups, permissions, seed data).
- `django-rest-framework` covers the API-first commitment (§4.15).
- Templates + HTMX cover interactivity without a JS build step.
- Cost: Django owns migrations for `operations` schema only. Existing
  `ninja_*` schemas remain SQL-migration-managed, models generated via
  `inspectdb`, marked `Meta: managed = False`. Rule: **if Operations
  writes it, Django owns it; otherwise, Django reads it and does not
  migrate it.**

### 4.2 Auth

Two backends coexist forever. Never remove local.

- **`ModelBackend`** (username/password) — v1 primary, break-glass
  forever, service accounts, programmatic tokens.
- **SSO backend slot** — reserved. OIDC via Google Workspace is the
  likely first target. One config change to enable, no data migration
  if we dedupe on email.

Login page eventually shows both. Local auth rate-limited + strong
password enforced. MFA is delegated to SSO; local users are break-glass
only.

### 4.3 Org scoping / UX mode

Every page answers a question about a specific client, or explicitly
about "all clients." One URL namespace:

```
/orgs/{slug}/inventory/software      # one client
/orgs/all/inventory/software          # all clients
```

- **Middleware** resolves `request.current_client` from the URL slug
  once per request. `slug='all'` sets it to `None` and flags the
  request as `mode='all'`.
- **View decorators** enforce scope:
  - `@require_client_scope` — pages that must have a specific client
    (policy editor, decision buttons that need whose policy).
  - `@require_admin` — pages that edit MSP-wide data (software catalog).
- **DB access helpers**: `client_scoped_query(request, sql)` and
  `all_clients_query(sql)`. Views declare which they use. No implicit
  filter-skipping.
- **Display term:** "All Clients" everywhere in the UI. No "Fleet" /
  "Global" / "Estate" vocabulary surfaces to operators.
- **Slug `all` is reserved** — client names that would slug to `all`
  are rejected on save.

### 4.4 Module structure

v1 ships a single **Inventory** module with two submodules:

```
/orgs/{slug}/inventory/
    devices/            # merge review, source conflicts, unmanaged assets
    software/           # classification, decisions, policy editor
    reports/            # canonical charts per submodule
    queries/            # whitelisted saved-query page
```

Build order inside v1:

1. Devices submodule first (DB layer is closest to done via migrations
   060–064).
2. Software submodule second (larger — needs new ingest, catalog, policy,
   classification).
3. Reports + Queries land as each submodule needs them.

Future modules attach at `/orgs/{slug}/{module}/...` with the same
scoping + decorators.

### 4.5 Software classification model

Categorized rules + per-client policy + fleet context. **Not** a single
flat label per product.

Three data classes:

| Data | Scope | Edited in |
|---|---|---|
| `software_catalog` (product → category) | MSP-wide | Admin |
| `client_policy` (this client's authorized products per category) | Per-client | Client mode |
| `software_decisions` (Approve / Reject / Investigate per product per client) | Per-client | Client mode (or row-scoped from All Clients) |

Categories in v1: `RMM`, `AV_EDR`, `Remote_Access`, `VPN`, `Backup`,
`Password_Manager`, `File_Sync`, `EOL_Runtime`, `Hack_Crack`,
`Uncategorized`.

Rules that fire against each install (in descending priority):

1. `unauthorized_rmm` — category=RMM ∧ product ∉ policy.approved_rmm.
2. `unauthorized_av` — category=AV_EDR ∧ product ∉ policy.approved_av.
3. `unauthorized_remote_access` — same shape for Remote_Access.
4. `install_path_suspicious` — location matches `%APPDATA%\`, `%TEMP%\`,
   `Downloads\` regardless of publisher.
5. `rare_recent` — ≤2 devices in org ∧ `install_date >= now() - interval '30 days'`.
6. `eol_runtime` — category=EOL_Runtime.
7. `suspicious_name` — matches keygen/crack/miner/etc.
8. `multi_av_conflict` — ≥2 AV_EDR installs on same device (excluding
   Defender).

Signed-publisher status is a modifier, not an override. TeamViewer
signed by TeamViewer GmbH is still `unauthorized_rmm` on a client where
Ninja is the authorized RMM.

**Current-state target: `software_installations_current`.** Rules run
against a **regular tenant-scoped table** with RLS — not a materialized
view, deliberately.

Why not a materialized view: MV rows are stored copies; base-table
RLS does not re-run when selecting from an MV, so `SELECT` against the
MV would leak cross-tenant rows regardless of the RLS on
`entity_observations`. `CREATE POLICY` also cannot be applied to
materialized views in Postgres. Making this a regular table with
RLS is the only shape that stays tenant-safe.

Schema:

```sql
CREATE TABLE operations.software_installations_current (
    tenant_id           bigint NOT NULL,
    client_id           uuid   NOT NULL,
    device_id           uuid   NOT NULL,
    canonical_name      text   NOT NULL,   -- from observations.entity_key
    publisher           text,
    version             text,
    install_location    text,
    install_date        date,
    first_observed_at   timestamptz NOT NULL,
    last_observed_at    timestamptz NOT NULL,
    refreshed_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, client_id, device_id, canonical_name)
);
ALTER TABLE operations.software_installations_current
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.software_installations_current
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON operations.software_installations_current
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
```

Refresh happens through a **`SECURITY DEFINER` function** owned by
`operations_migrate` (the migration/app owner; `BYPASSRLS`):

```sql
CREATE FUNCTION operations.refresh_software_installations_current(
    p_tenant_id bigint DEFAULT NULL   -- NULL = refresh all tenants
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $$
BEGIN
    -- Runs as owner (operations_migrate) with BYPASSRLS so it can read
    -- across tenants when p_tenant_id is NULL, and rebuild all rows.
    WITH latest AS (
        SELECT DISTINCT ON
            (tenant_id, client_id, device_id, entity_key)
            tenant_id, client_id, device_id,
            entity_key AS canonical_name,
            raw_data ->> 'publisher'          AS publisher,
            raw_data ->> 'version'            AS version,
            raw_data ->> 'location'           AS install_location,
            (raw_data ->> 'installDate')::date AS install_date,
            MIN(observed_at) OVER (
                PARTITION BY tenant_id, client_id, device_id, entity_key
            ) AS first_observed_at,
            observed_at AS last_observed_at
        FROM operations.entity_observations
        WHERE entity_type = 'software'
          AND client_id  IS NOT NULL
          AND device_id  IS NOT NULL
          AND (p_tenant_id IS NULL OR tenant_id = p_tenant_id)
        ORDER BY tenant_id, client_id, device_id, entity_key,
                 observed_at DESC
    )
    INSERT INTO operations.software_installations_current AS t
        (tenant_id, client_id, device_id, canonical_name,
         publisher, version, install_location, install_date,
         first_observed_at, last_observed_at, refreshed_at)
    SELECT tenant_id, client_id, device_id, canonical_name,
           publisher, version, install_location, install_date,
           first_observed_at, last_observed_at, now()
      FROM latest
    ON CONFLICT (tenant_id, client_id, device_id, canonical_name)
    DO UPDATE SET
        publisher         = EXCLUDED.publisher,
        version           = EXCLUDED.version,
        install_location  = EXCLUDED.install_location,
        install_date      = EXCLUDED.install_date,
        -- Preserve earliest first_observed_at across backfills and
        -- replays of older observations. Without LEAST() a replay
        -- would advance first_observed_at forward and corrupt any
        -- age-sensitive rule (rare_recent, etc.).
        first_observed_at = LEAST(t.first_observed_at,
                                  EXCLUDED.first_observed_at),
        last_observed_at  = GREATEST(t.last_observed_at,
                                     EXCLUDED.last_observed_at),
        refreshed_at      = now();

    -- Drop rows whose (device, product) no longer appears in the
    -- observation window (uninstalled).
    DELETE FROM operations.software_installations_current t
    WHERE (p_tenant_id IS NULL OR t.tenant_id = p_tenant_id)
      AND NOT EXISTS (
          SELECT 1 FROM operations.entity_observations o
          WHERE o.entity_type = 'software'
            AND o.tenant_id  = t.tenant_id
            AND o.client_id  = t.client_id
            AND o.device_id  = t.device_id
            AND o.entity_key = t.canonical_name
      );
END;
$$;

GRANT EXECUTE ON FUNCTION
    operations.refresh_software_installations_current(bigint)
    TO ninja_ingest, operations_app;
```

Call sites:

- Software ingest module (§8 M2) calls
  `refresh_software_installations_current(NULL)` at the end of every
  run. Runs under `ninja_ingest` role; `SECURITY DEFINER` promotes to
  owner for the duration.
- Retention prune (§4.13) calls it before pruning observations so
  current-state reflects the pre-prune window.
- Ad-hoc admin refresh via `manage.py refresh_current_state`.

Classification rules run as SQL functions against
`software_installations_current`; results land as findings against
`subject_type='device'` (per-device instance) or
`subject_type='client'` (aggregate). Software as an entity remains
observation-only — no canonical `software_row` table; every install
is a row in `software_installations_current` computed from the
observation stream.

### 4.6 Metabase relationship

Coexist, deep-link, migrate domain-by-domain.

- **Metabase → Operations** link contract: URL shape
  `/orgs/{slug}/{module}/{entity}?{filters}`. Metabase columns are
  configured to build these URLs. Documented in `docs/deep_links.md`.
- **Operations → Metabase** links resolved through
  `operations/shared/metabase_links.py` — one config layer, question
  IDs looked up by symbolic name, filters passed as URL params. Signed
  embed URLs supported for inline card rendering (v1 uses external
  links only).
- **Migration:** when Operations' coverage of a domain (list + filter +
  decisions + a few canonical charts + queries) exceeds Metabase's, stop
  routing operators to Metabase for that domain. Software is first.
  Devices, patches, activities, agent compliance follow in later
  releases.
- Metabase stays for domains Operations does not cover, and as an
  ad-hoc exploration tool indefinitely.

### 4.7 Entity observations model

Generalize `platform_observations` beyond devices. Same table shape
handles any entity type sourced from any collector.

```
entity_observations
├── observation_id            uuid primary key
├── tenant_id                 bigint, default 1, RLS-enforced
├── client_id                 uuid nullable  (canonical client;
│                                             null until binding resolved)
├── device_id                 uuid nullable  (canonical device — filled
│                                             for observations that
│                                             reference a device:
│                                             'device', 'software',
│                                             'lease'; null for 'client'
│                                             and 'client_user' scoped
│                                             observations)
├── collector_instance_id     uuid
├── source_binding_id         uuid
├── entity_type               text  ('device' | 'client_user' | 'group' |
│                                    'software' | 'lease' | ...)
├── entity_key                text  (canonical join key for this
│                                    entity_type — for entity_type
│                                    'software' this is the canonical
│                                    product name; for 'device' the
│                                    canonical hostname or serial;
│                                    for 'client_user' the canonical
│                                    email or username)
├── platform                  text  ('Ninja' | 'vCenter' | 'AD' | ...)
├── subplatform               text  ('hypervisor.vcenter', nullable)
├── observed_at               timestamptz
├── raw_data                  jsonb (source-shape payload)
├── canonical_data            jsonb (normalized fields)
├── batch_id                  uuid  (idempotency)
├── observation_hash          bytea (idempotency)
├── collector_version         text
└── schema_version            int
```

`client_id` and `device_id` are **promoted columns**: they start
`NULL` at write time and are filled by the binding resolver — either
at write time when the (source, external_id) resolves cleanly to a
canonical entity, or after operator resolution of an
`unlinked_external_identity` finding (§5.7). Observations without a
resolved `client_id` land in `dead_letter_observations` and do not
participate in current-state materializations until replayed.
Downstream queries and current-state tables read the promoted
columns, not `raw_data` or `canonical_data`, so retention pruning
does not silently corrupt joins.

`client_id` is nullable because tenant-level source_instances (e.g.,
fleet-wide Ninja) can produce observations that reference an external
identity not yet bound to a canonical client. Such observations
dead-letter and fire `unlinked_external_identity` (§5.7); once
resolved, `client_id` is filled at replay time.

Merge review, reconciliation, and finding rules work identically for
every entity type. Devices are one implementation; users, groups,
software installs, DHCP leases follow the same lifecycle.

### 4.8 Source vs Collector

Distinct concerns.

- **Source** — the system being observed (AD, DHCP, vCenter, M365,
  Ninja-as-API, S1, LMI, SC). Data class.
- **Collector** — the transport that got that data to Operations. Runtime
  class. Ninja-hosted script, native agent, direct pull, file drop,
  manual upload.

The same source at the same client can be collected via different
mechanisms without touching schema or reports. `source_bindings`
routes: `(source_instance, collector_instance) → schedule`.

Ninja is one collector kind among several the model supports from day
one; nothing is Ninja-specific in the ingest endpoint.

Platform + subplatform on every observation distinguishes
Ninja-as-hypervisor-transport (`platform='Ninja',
subplatform='hypervisor.vcenter'`) from direct vCenter
(`platform='vCenter'`). Both can coexist; merge on VM BIOS UUID.

### 4.9 Collector contract

Five items. Anything satisfying these is a valid collector:

1. **Authenticate** — bearer token per `collector_instance`, rotatable.
2. **Identify** — send `collector_instance_id`, kind, version,
   capabilities matrix.
3. **POST observations** to `/api/observations` with envelope. All
   instance-level identifiers are UUIDs (generated client-side by the
   collector, no round-trip required). Reference-taxonomy IDs
   (`sources.id`, `collectors.id`, `finding_types.id`) are small ints;
   they never appear in the collector protocol.
   ```json
   {
     "collector_instance_id": "018f7a0b-…",
     "source_binding_id":     "018f7a0c-…",
     "batch_id":              "018f7a0d-…",
     "collector_version":     "1.4.2",
     "schema_version":        3,
     "entity_type":           "software",
     "observed_at":           "2026-07-05T12:00:00Z",
     "observations": [
       { "entity_key": "microsoft office",
         "raw":       {...},
         "canonical": {...},
         "observation_hash": "hex..." }
     ]
   }
   ```
4. **Health** — heartbeat + last-run status per `source_binding`.
5. **Optional: task pull** — `GET /api/work?collector_instance_id=…`
   returns pending runs. Needed for on-demand re-scans and backfills.

Ingest is generic: validate → resolve binding → RLS write. No branching
on collector kind.

**Two entry points, one pipeline.** Observations arrive either over
HTTPS (external collector) or in-process (the existing `ingest/`
container running a domain module like `ingest/inventory/software.py`).
Both go through the same `operations.ingest.observation_pipeline`
function:

```python
observation_pipeline(envelope: ObservationEnvelope) -> IngestResult
```

- HTTP path: DRF view unmarshals the JSON envelope, calls the pipeline.
- In-process path: the ingest module constructs an `ObservationEnvelope`
  in memory (generating `batch_id`, `observation_hash`, tagging
  `collector_instance_id` = the built-in `internal-ingest` collector
  instance) and calls the same function directly.

Both paths share `batch_id` / `observation_hash` uniqueness, schema
versioning, dead-lettering, tenant resolution, and audit trail.
There is one idempotency contract, one validator, one dead-letter
handler.

The `internal-ingest` collector is a real row in `collector_instances`
seeded at M0 (kind = `internal`, tenant-scoped, no external token —
used only from Python code inside the Operations DB network). It
appears in health dashboards next to external collectors.

### 4.10 Finding lifecycle

Findings are first-class. Every rule that fires produces one.

- **Status:** `open | acknowledged | investigating | suppressed | resolved | wontfix`.
- **Owner:** nullable user_id. Auto-assign by policy later.
- **Severity + SLA:** severity from the rule, SLA from client policy.
  Overdue findings show in their own queue.
- **Suppression:** first-class object with reason + expiry. Applied at
  finding-time, not swept later. `suppression_rule` table.
- **Runbook link:** every finding *type* has a runbook (Markdown in
  `docs/runbooks/{type}.md`), rendered inline in the UI.
- **Notification routing:** per-client × per-severity × per-finding-type.
  Channels: email v1; Slack / Teams / webhook post-v1. Immediate vs
  digest configurable per route.
- **`last_reviewed_at`** column supports "stale review" queues.

### 4.11 Audit log

Every write in Operations records:

```
audit_log
├── audit_id       uuid
├── tenant_id
├── actor_id       user_id  (nullable for system actions)
├── actor_kind     'user' | 'collector' | 'system'
├── source         'ui' | 'api' | 'ingest' | 'management_command'
├── action         verb ('approve_software' | 'merge_devices' | ...)
├── entity_ref     (entity_type, entity_id)
├── before_state   jsonb
├── after_state    jsonb
├── ip_address     inet
├── user_agent     text
└── occurred_at    timestamptz
```

- Append-only, immutable.
- Retention: **forever** (no rotation).
- Undo: every write reversible by re-applying `before_state`. Restore
  action recorded as its own audit row.

### 4.12 Idempotency + schema versioning

Ingest envelope carries `batch_id` + per-observation `observation_hash`.

- Unique key on `entity_observations`:
  `(tenant_id, collector_instance_id, batch_id, observation_hash)`.
  `tenant_id` is defense-in-depth against a compromised or
  misconfigured collector token routing to the wrong tenant.
- Re-POST is a no-op, not a duplicate.
- Envelope also carries `collector_version` + `schema_version`.
- Ingest side has small adapter functions per `schema_version` — old
  collectors keep working during rolling upgrades.

### 4.13 Retention + timezone

- **Timezone:** UTC in DB. Display in operator's TZ by default;
  scheduled/emailed reports rendered in client's TZ (§5.10). Client
  timezone is single-valued for v1; multi-site clients pick their
  primary in `clients.timezone`, per-report override deferred.
- **Retention:**
  - `entity_observations` raw: **90 days**. Before pruning, the
    retention job calls the current-state refresh functions
    (`operations.refresh_software_installations_current(NULL)` and
    any future `refresh_*_current` siblings), then denormalizes
    provenance into `merge_candidates.member_snapshots` (§6.1) so no
    downstream row holds dangling observation IDs.
  - Current-state tables (e.g. `software_installations_current`):
    **regular tenant-scoped tables with RLS** (§4.5) — not
    materialized views. Retained indefinitely; rows are refreshed on
    every ingest run and pruned by the refresh function when their
    underlying observations disappear.
  - `run_log`: **30 days**.
  - `dead_letter_observations`: unresolved indefinite; resolved 30
    days past `resolved_at` (§6.4).
  - `findings` open: indefinite. `findings` resolved / wontfix:
    **12 months**.
  - `audit_log`: **forever** (no rotation).
  - Canonical entity rows (`clients`, `devices`, `client_users`,
    `*_links`): soft-delete via `deleted_at`, never hard DELETE.

Retention enforced by a nightly management command (`operations
prune`), which itself writes to `audit_log` (retention action is
auditable) and `run_log`. Prune order matters: refresh current-state
views → denormalize merge candidate provenance → prune observations.
Any step failure aborts the run with `run_log.ok = false` and no
observations are removed on that pass.

### 4.14 Secrets

Two classes, isolated storage:

- **Operations infrastructure secrets** — Django SECRET_KEY, DB DSN,
  session key. Live in `/amr-ch-01_data/ninja-dashboard/.env`. Existing
  pattern.
- **Per-client per-source credentials** — AD service account passwords,
  vCenter certs, direct-pull API tokens. Stored in `secrets` table with
  `pgp_sym_encrypt`; KMS key in `.env` (`OPERATIONS_SECRETS_KEY`).
  Rotation is a re-encrypt management command. Access mediated by a
  `secrets_manager` service; never returned in API responses; never
  logged.

### 4.15 API surface

**API-first.** Every UI view has a JSON representation via DRF. Every
write is available as an API call. UI is one client of the API.

- Session auth for UI; bearer tokens for programmatic (`user_tokens`
  table, per-user, revocable, scoped).
- OpenAPI spec auto-generated by `drf-spectacular`.
- Rate limits per token via `django-ratelimit` or DRF throttling.

### 4.16 Rebrandable appliance + multi-tenant seam

Two future paths preserved cheaply now.

**Appliance / white-label deploy:**

- No hardcoded brand strings. `brand` context processor renders name,
  short name, tagline, footer from config: `OPERATIONS_BRAND_NAME`,
  `OPERATIONS_BRAND_SHORT`, `OPERATIONS_BRAND_TAGLINE`,
  `OPERATIONS_SUPPORT_URL`, `OPERATIONS_PRIVACY_URL`.
- Logo, favicon, colors from a `theme/` directory (default ships with
  AMRose branding, mounted directory overrides at deploy time).
- Email + PDF templates use brand variables everywhere.
- Public URL and all generated links driven by `OPERATIONS_BASE_URL`.

**Multi-tenant seam:**

Three classes of table, treated distinctly:

- **Global tables (no `tenant_id`).** Reference taxonomy shared across
  all tenants. Read-only to non-admins. RLS not applied.
  - `tenants`, `sources`, `collectors`, `finding_types`, Django
    `auth_group`, Django `auth_permission`.
- **Tenant-scoped tables (`tenant_id NOT NULL`, RLS-enforced).** All
  write/workflow/config tables **and current-state derived tables**.
  Cross-tenant queries impossible even with a code bug.
  - `users`, `user_tokens`, `user_groups`, `user_permissions` (custom
    Django M2M through-models with `tenant_id`, see below), `clients`,
    `client_links`, `client_policies`, `devices`, `device_links`,
    `client_users`, `client_user_links`, `source_instances`,
    `collector_instances`, `source_bindings`, `entity_observations`,
    `software_decisions`, `software_installations_current`,
    `merge_candidates`, `findings`, `suppression_rules`,
    `notification_routes`, `dead_letter_observations`, `audit_log`,
    `secrets`, `run_log`.
- **Layered tables (`tenant_id NULL = global default, non-null = tenant
  override`).** RLS policy allows `tenant_id IS NULL OR tenant_id =
  current tenant`. Query pattern uses `DISTINCT ON` to prefer overrides.
  - `software_catalog` (global taxonomy + tenant-specific
    categorization overrides), and any future `*_defaults` tables.

**Django auth model.** Groups and permissions are **global taxonomy**
(`auth_group`, `auth_permission`). The tenant boundary lives on the
custom User model (§5.3), which redeclares the M2M relationships to
`Group` and `Permission` through **custom Through models**
`operations.user_groups` and `operations.user_permissions`, both
carrying `tenant_id NOT NULL` + RLS. This closes the classic Django
hole where `auth_user_groups` references a tenant-scoped `user_id`
but the join table itself carries no tenant marker — without a
custom through, RLS on `users` does not cascade through the FK, and
a cross-tenant permission enumeration would return rows.

A user in tenant 1 with group `operator` gets the same permission set
as a user in tenant 2 with the same group; each only sees their own
tenant's data because every downstream query is RLS-scoped and every
join-table row is tenant-scoped through the custom through. If
per-tenant custom groups ever become a real requirement, we swap to a
custom Group model then.

**RLS bypass rules.** Migrations, `manage.py` commands, and health
checks run as a role with `BYPASSRLS`. Application connections use a
role that does not. See §6.3.

None of this ships product features (sign-up, billing, per-tenant
admin). Those are deferred until a real commercial commitment.

### 4.17 Canonical entity principle (foundational)

Numbered last but architecturally foundational — every other §4
decision assumes this. Read this before the data model.

**Every canonical entity in Operations is multi-sourced by design.**
No entity has a "primary source" or "parent source." Sources
contribute observations; Operations resolves them into a canonical
view. Applies uniformly to:

- **Clients** — business relationships AMRose decides exist. Ninja
  orgs, Entra tenants, ScreenConnect tenants, AD domains, backup
  vault IDs, CRM records are all *external identities* linked to the
  client. Usually 1:1 with a Ninja org today; not required to be.
- **Devices** — physical or logical hosts. Observed by Ninja agent,
  SentinelOne agent, LogMeIn agent, ScreenConnect session,
  vCenter/Hyper-V VM record, AD computer account, DHCP lease. VM BIOS
  UUID, hardware serial, and hostname are the strongest join keys.
- **Client users** — the client's employees / end-users. Distinct from
  `operations.users` (Django login accounts for AMRose staff).
  Observed by AD user, Entra user, M365 mailbox, Ninja LastUser
  string, ticketing-system contact, etc. Modeled as
  `operations.client_users` + `client_user_links` (§6.1).
- **Software products** — via `software_catalog` (already layered).
- **Software installations** — (client, device, product) tuples
  observed by Ninja `/software`, S1 installed apps, package managers.

**Implications carried through the rest of the design:**

- **Nothing is "the Ninja device" or "the AD user."** There is one
  canonical device and one canonical user; Ninja and AD each
  contribute observations.
- **Merge review is the operator flow for binding observations to
  canonical entities.** Whether the entity is a client, device, or
  user, the mechanic is identical (§4.10 finding lifecycle, §6.1
  `merge_candidates`).
- **`unlinked_external_identity`** is the finding type that fires when
  a source's external ID (a Ninja org id, an AD computer objectSid,
  an Entra user id) is not yet bound to a canonical entity. Operator
  resolves by binding to an existing entity or creating a new one.
- **Never auto-create canonical entities from observations.** Ingest
  dead-letters until an operator resolves the binding. Auto-created
  entities grow without owners and pollute reports.
- **Downstream views join through the link tables**, not through
  source-side IDs. Reports may lazy-migrate from
  `... JOIN ninja_core.organizations ON organizationId` to
  `... JOIN client_links ON (source='Ninja', external_id=organizationId)`,
  per-dashboard, per-milestone. New Operations reports use the link
  tables from day one.
- **RMM-agnostic future.** If AMRose ever switches from Ninja to
  another RMM, canonical entities survive. The link rows change; the
  clients, devices, users, and their history do not.

**M0 bootstrap ≠ authority.** The one-shot import that seeds
`operations.clients` from `ninja_core.organizations` at M0 (§8, §5.1)
is a convenience so operators don't hand-enter ~70 clients on day one.
It is the *only* time Ninja is treated as authoritative for canonical
identity. After M0, clients (and every other canonical entity) are
created and edited in Operations first.

---

## 5. Open decisions

Each block is a specific choice with a recommendation. Review, then
Approve / Edit / Veto per block. Nothing here changes the shape of the
system; all are cheap to reverse.

### 5.1 Client canonicalization (client-first)

**Recommendation:** Clients are **first-class canonical entities in
Operations** (§4.17). They are created by AMRose staff — via UI, API,
or future CRM sync — because a business relationship exists. Sources
(Ninja, Entra, ScreenConnect, AD, backup) contribute observations
about a client but never *create* a client silently.

Concretely:

- `operations.clients` holds the canonical row: slug, display_name,
  timezone, deleted_at.
- `operations.client_links` binds `client → (source, external_id,
  external_name)`. A client can have 0, 1, or many links per source.
- New client onboarding starts by creating the Operations client;
  Ninja / Entra / SC / etc. links are added as those tenants are
  provisioned. Clients can exist with **zero** Ninja links (paperwork
  signed, RMM not deployed; consulting-only engagement; migrated
  from a prior RMM).
- A single client with **multiple** Ninja orgs (subsidiary structure,
  M&A situations, region splits) is represented as N `client_links`
  rows against `source='Ninja'`.
- **`source_instances.client_id` is nullable** (§6.1). Tenant-level
  sources — the fleet-wide Ninja OAuth credential that discovers all
  Ninja orgs, for example — carry `client_id = NULL`. Per-client
  sources (AD, DHCP, direct vCenter, per-tenant M365 Graph) carry a
  bound `client_id`. Observations from a tenant-level source that
  reference an unbound external identity dead-letter until an
  operator resolves the binding (§5.7).
- Existing Metabase dashboards continue to read
  `ninja_core.organizations` directly for v1. New Operations views
  and future dashboard migrations join through `client_links`
  (§4.17). No big-bang migration.

**M0 bootstrap import (one-shot only):**

- Migration `operations 0002_bootstrap_clients` seeds
  `operations.clients` from `ninja_core.organizations`: one row per
  Ninja org, slug derived from name, `client_links` row binding
  `client → (source='Ninja', external_id=<ninja org id>)`.
- Tagged `bootstrap=true` on the migration row so it is not re-run
  and its intent is auditable.
- After M0 lands, **Ninja is no longer authoritative for client
  identity.** New Ninja orgs discovered by ingest fire an
  `unlinked_external_identity` finding (§5.7); operators resolve by
  binding to an existing Operations client or by creating a new
  Operations client and binding.

**Approve / Edit / Veto:**  ☐

### 5.2 Schema ownership rule

**Recommendation:**

- Django owns tables in the `operations` schema. Migrations are Django
  migrations (`operations/migrations/`).
- Existing `ninja_*` schemas remain SQL-managed via
  `ninja-dashboard/sql/migrations/*.sql`.
- Operations reads existing schemas via `inspectdb`-generated models
  with `Meta: managed = False`.
- Cross-schema views (analytics that join Operations and ingest data)
  live in SQL migrations under `sql/migrations/`, referenced by
  Operations as `managed = False` models.

**Approve / Edit / Veto:**  ☐

### 5.3 User model

**Recommendation:** Custom `AbstractUser` subclass in
`operations.users.User` from day one, empty at first. Retrofitting
Django's user model post-launch is genuinely painful; declaring a
custom user now costs nothing.

**Approve / Edit / Veto:**  ☐

### 5.4 Roles / permissions

**Recommendation:** Django groups + Django permissions.

**Permissions are the atoms** — named capabilities registered on
`operations` app models. Groups are named bundles of permissions
assigned to users. Views + serializers gate on the permission name,
never on the group name. That way renaming or splitting a group
doesn't break authorization.

**v1 permission catalog** (each is a real `auth_permission` row seeded
by migration):

| Codename | What it grants |
|---|---|
| `view_clients` | Read canonical clients, links, policies. |
| `view_devices` | Read canonical devices, links, observations. |
| `view_software` | Read software catalog, installations, decisions. |
| `view_findings` | Read findings and their subjects. |
| `write_decisions` | Approve / Reject / Investigate software decisions. |
| `approve_merges` | Approve / reject / split merge candidates. |
| `manage_findings` | Assign, suppress, resolve findings. Edit runbooks. |
| `manage_client_policy` | Edit per-client policy (authorized RMM/AV/etc., agent SLA). |
| `manage_catalog` | Edit global `software_catalog` (tenant_id IS NULL rows). |
| `manage_collectors` | Register / rotate / disable collector_instances + tokens. |
| `manage_sources` | Register / configure source_instances. |
| `manage_secrets` | Read / rotate encrypted per-client credentials. |
| `manage_users` | Create / edit / disable Operations login users, group membership. |
| `manage_taxonomy` | Edit global reference tables (`sources`, `collectors`, `finding_types`). |
| `run_queries` | Execute whitelisted saved queries on the Queries page. |

**v1 seed groups** (group → permission set):

- `admin` — every permission above.
- `operator` — `view_*`, `write_decisions`, `approve_merges`,
  `manage_findings`, `manage_client_policy`, `run_queries`.
- `viewer` — `view_*`, `run_queries`.

Adding a group later is a data migration, not code. Adding a permission
later requires code + migration (registered on a model). No custom RBAC
framework. Per-client scoping introduced only if a concrete requirement
forces it.

**Approve / Edit / Veto:**  ☐

### 5.5 Client slug rules

**Recommendation:**

- Auto-derived from client name, kebab-case, ASCII-only, lowercase.
- Editable via admin UI; unique per tenant.
- `all` is reserved.
- Immutable once used in URLs — renaming a client's name updates
  `display_name` but not `slug`, to avoid breaking bookmarks and audit
  entries.

**Approve / Edit / Veto:**  ☐

### 5.6 Canonical normalization

**Recommendation:** One text helper for the common case, plus
**explicit type-specific variants** so per-field rules stay named and
inspectable instead of hidden inside an overloaded `canonical()`.

All live in `operations.util.canonical`; each returns `""` on `None`
or empty input. Stored on rows in a `canonical_*` column (indexed);
raw preserved in a `raw_*` column for display and audit.

```python
def canonical_text(x):
    # Default for name-like text: software name, publisher, group name,
    # display name, notes-keyed lookups.
    # Trim, lowercase, collapse internal whitespace.
    return "" if x is None else " ".join(str(x).strip().lower().split())

def canonical_hostname(x):
    # Strip DNS suffix, lowercase, drop trailing dot, ASCII-only.
    # DOES NOT collapse dashes/underscores — they can be significant.
    ...

def canonical_username(x):
    # Strip domain prefix (DOMAIN\user → user), lowercase.
    # Preserves internal punctuation.
    ...

def canonical_email(x):
    # Trim, lowercase the domain part, preserve the local part case
    # (per RFC 5321). If matching in a case-insensitive user store
    # (M365/Google), a match_email() variant lowercases fully.
    ...

def canonical_mac(x):
    # Strip separators (:, -, .), lowercase, validate 12 hex digits.
    # Returns "" for malformed input; never guesses.
    ...

def canonical_serial(x):
    # Trim, uppercase, drop internal whitespace.
    # DOES NOT strip leading zeros — they are significant on some
    # hardware serials.
    ...

def canonical_uuid(x):
    # Lowercase, dash-normalized 8-4-4-4-12. Returns "" if not a
    # valid UUID.
    ...
```

Rules:

- **Never call `canonical_text` on typed data.** MAC, serial, email,
  UUID all get their own function. Reviewer-catchable in code review.
- Each helper is pure and has unit tests naming the specific rule
  (uppercase serial preserves leading zeros; email preserves local
  part case; MAC returns `""` for malformed; etc.).
- Adding a new typed field = new helper, not overloading an existing
  one.

**Approve / Edit / Veto:**  ☐

### 5.7 Unbound external identity handling

**Recommendation:** Applies uniformly to any source's external
identity — Ninja org, AD computer, Entra user, DHCP lease, VM UUID —
that arrives via ingest without a link to a canonical entity.

- Observation lands in `dead_letter_observations` (§6.4) preserving
  the full envelope.
- An `unlinked_external_identity` finding fires against the
  `source_binding` subject (§5.15). Payload names the entity kind
  (client / device / user / etc.), external ID, external display name.
- Operator resolution options (recorded in the audit log):
  1. **Bind to existing canonical entity** — pick a client / device /
     user; add a `*_links` row; replay dead-lettered observations.
  2. **Create new canonical entity and bind** — create the client /
     device / user, then bind and replay.
  3. **Ignore permanently** — add a suppression rule (§4.10) matching
     the external ID; observations continue to dead-letter but no
     finding fires.
- Never auto-create canonical entities from observations. Auto-
  created entities grow without owners and pollute reports.
- Retention: unresolved dead-lettered observations retained
  indefinitely; resolved retained 30 days past `resolved_at` (§6.4).

**Approve / Edit / Veto:**  ☐

### 5.8 Testing strategy

**Recommendation:** Three layers:

- **Model + unit tests** — Django `TestCase`, in-memory SQLite for speed
  where possible, Postgres testcontainer for anything using RLS,
  `jsonb`, or PL/pgSQL.
- **API tests** — DRF `APITestCase` against a Postgres testcontainer.
  Exercises auth + tenant scoping + RLS enforcement.
- **Browser tests** — Playwright, small suite (login, decision write,
  merge approve, org switch, deep-link round-trip). Not a full E2E
  matrix.

Fixtures generated by `manage.py seed --scenario={demo|realistic|empty}`
from an anonymized prod snapshot. Anonymization is a separate
`manage.py anonymize` command run once on a fresh dump before it is
committed to the dev fixture store; the command:

- Replaces email addresses with `user{n}@example.test`.
- Replaces hostnames with `host-{n}.internal`.
- Replaces MACs with deterministic pseudo-MACs derived from a keyed
  hash (`OPERATIONS_ANONYMIZE_KEY` env var; single key per fixture
  vintage).
- Replaces IPv4/IPv6 addresses with RFC 5737 / 3849 documentation
  ranges.
- Replaces client / org display names with `Client-{n}`; slugs with
  `client-{n}`.
- Replaces serial numbers with hash-derived pseudo-serials.
- Leaves timestamps, categories, versions, and structural data alone.
- Deterministic: same input row → same anonymized output within one
  fixture vintage, so joins survive.

Encrypted secrets are dropped, not anonymized. Fixture is committed
after `anonymize` succeeds; raw dump is discarded from the workstation.

**Approve / Edit / Veto:**  ☐

### 5.9 Merge review concurrency

**Recommendation:** Optimistic locking. Every merge_candidate row has a
`version` int. Write requires the version the operator loaded. Second
writer gets a 409 with "someone else acted on this, refresh." Applies
to any decision-write, not just merges.

**Approve / Edit / Veto:**  ☐

### 5.10 Timezone display

**Recommendation:** Operator's TZ by default in the UI (from user
profile). Scheduled or emailed reports render in the client's TZ
(from `clients.timezone` field). Reports include both if delivered to
mixed audiences.

**Approve / Edit / Veto:**  ☐

### 5.11 MFA on local auth

**Recommendation:** Deferred. Local auth is break-glass only; small user
set; rate-limit + strong-password enforced; usage produces a
`local_auth_used` audit row. If ever exposed to routine use, add
`django-otp` as a backend.

**Approve / Edit / Veto:**  ☐

### 5.12 Static asset serving

**Recommendation:** Whitenoise inside the Operations container. Matches
"everything in one container" preference. Nginx sidecar only if v2 adds
public exposure with WAF/rate-limit needs.

**Approve / Edit / Veto:**  ☐

### 5.13 API documentation

**Recommendation:** `drf-spectacular` for OpenAPI schema, Swagger UI +
Redoc mounted at `/api/docs/` and `/api/redoc/`. Free once API-first is
committed. Documentation is part of the release artifact.

**Approve / Edit / Veto:**  ☐

### 5.14 `software_catalog` layering

**Recommendation:** Single table, layered.

- `software_catalog.tenant_id` is nullable. `NULL` = global default,
  non-null = tenant override.
- RLS policy: `USING (tenant_id IS NULL OR tenant_id =
  current_setting('operations.tenant_id', TRUE)::bigint)`.
- Read pattern: `SELECT DISTINCT ON (canonical_name) ... ORDER BY
  canonical_name, tenant_id NULLS LAST` — tenant-specific row wins
  when present, otherwise falls back to global.
- Global rows (`tenant_id IS NULL`) editable only by users with the
  `manage_catalog` permission (§5.4) — seeded on the `admin` group.
  Tenant-override rows editable by users with `manage_catalog`
  scoped to the current tenant (v1: same permission, single-tenant;
  extended when multi-tenant activates).
- Seeded at M0 with ~50 curated global entries (RMM, AV_EDR,
  Remote_Access categories). Tenant overrides are added on demand.

**Why:** Every MSP benefits from the shared taxonomy. Tenants who
disagree (this MSP considers Splashtop RMM but we categorized it
Remote_Access) override without forking. Standard SaaS-app pattern.

**Approve / Edit / Veto:**  ☐

### 5.15 Finding subject polymorphism

**Recommendation:** Findings do not require a `client_id`. Every
finding attaches to a **subject** modeled as `(subject_type,
subject_id)`:

- `subject_type` ∈ `client | device | client_user | source_binding | collector_instance`.
  Uses `client_user` — not `user` — to avoid confusion with
  `operations.users` (Django login accounts for AMRose staff).
  **Software is deliberately not a subject type.** Per §4.5 software
  is observation-only — there is no canonical `software_row` table
  with a UUID id to point at. Software-related findings target the
  *device* the install lives on (per-install: subject_type='device')
  or the client (aggregate: subject_type='client'). The finding's
  payload (`finding_details jsonb`) carries the `canonical_name` and
  any other software attributes needed for display and dedup.
- `subject_id` is **UUID** in all cases (every remaining subject
  target — `clients`, `devices`, `client_users`, `source_bindings`,
  `collector_instances` — has a uuid PK per §6.1). Stored as `uuid`
  on the findings row, not `text`.
- Client-scoped findings (`unauthorized_rmm`, `rare_recent`, etc.)
  have `subject_type = 'client'` or `'device'`; both are within a
  tenant-scoped table so RLS still enforces isolation.
- Source-level findings (`unlinked_external_identity`,
  `stale_collector_binding`) have `subject_type = 'source_binding'` or
  `'collector_instance'`, which resolve to a tenant but not a client.
- Convenience view `findings_by_client` exposes only those whose
  subject resolves to a client:

  ```sql
  CREATE VIEW operations.findings_by_client AS
  SELECT f.*, sub.client_id
  FROM operations.findings f
  JOIN LATERAL (
      -- clients: the subject IS the client, so its own id is client_id.
      SELECT id AS client_id
        FROM operations.clients
       WHERE id = f.subject_id AND f.subject_type = 'client'
      UNION ALL
      SELECT client_id
        FROM operations.devices
       WHERE id = f.subject_id AND f.subject_type = 'device'
      UNION ALL
      SELECT client_id
        FROM operations.client_users
       WHERE id = f.subject_id AND f.subject_type = 'client_user'
      -- 'source_binding' and 'collector_instance' do NOT resolve to a
      -- client and are excluded from this view.
  ) sub ON TRUE;
  ```

  Findings whose subject cannot resolve to a client (infrastructure
  findings) are visible in the general findings list, not here.

**Polymorphic FK integrity — not enforced by DB constraint.**
`(subject_type, subject_id)` cannot be a real foreign key because it
targets different tables per row. Integrity is enforced in the
service/serializer layer at write time:

1. Serializer looks up the subject via `(subject_type, subject_id,
   tenant_id = current tenant)`.
2. If not found → 422 validation error; no finding row written.
3. The `tenant_id` join guarantees the subject belongs to the current
   tenant — a cross-tenant `subject_id` fails the lookup and cannot
   be smuggled through.
4. `findings.tenant_id` is set from the current tenant (RLS-enforced
   on write) and must equal the resolved subject's `tenant_id`. The
   serializer asserts both; belt-and-suspenders against a mislabeled
   write.

A soft "orphan finding" nightly job scans for subjects that no longer
exist (deleted after the finding was written) and marks the finding
`resolved` with reason `subject_removed`. Prevents dangling references
without cascade-delete gymnastics across polymorphic targets.

Prevents nullable `client_id` + preserves ability to page on
infrastructure findings that have no client owner + keeps tenant
isolation airtight despite the polymorphic FK.

**Approve / Edit / Veto:**  ☐

---

## 6. Data model

Full column inventory lives in `sql/migrations/` and Django migrations;
this section shows only the core shape.

### 6.1 `operations` schema — Django-owned

Grouped by tenant-scoping class (§4.16). ID types: `uuid` for every
instance-level identity, small `int` (bigserial) for reference
taxonomy. `tenant_id` is a `bigint` foreign key to `tenants.id`.

**Global tables (no `tenant_id`, no RLS).**

```
tenants                 (id bigserial, slug, display_name,
                         brand_config jsonb, created_at)
sources                 (id smallserial, name, kind, capabilities jsonb)
collectors              (id smallserial, name, kind, capabilities jsonb)
finding_types           (id smallserial, name, default_severity,
                         runbook_path, description)
auth_group              Django default
auth_permission         Django default
```

Reference-only; edited via Django admin by users with the
`manage_taxonomy` permission (§5.4). Never carry `tenant_id`.

**Tenant-scoped tables (`tenant_id NOT NULL`, RLS-enforced).**

```
-- Django auth users (Operations login accounts for AMRose staff).
-- Kept as bigserial PK because AbstractUser inherits it; do NOT
-- change without a full auth migration. All references (owner_id,
-- actor_id, decided_by, resolved_by) use bigint FK to this table.
users                   (id bigserial, tenant_id, email, username,
                         is_active bool, timezone text NOT NULL
                                                DEFAULT 'UTC',
                         ...standard AbstractUser fields...)
user_tokens             (id uuid, tenant_id, user_id bigint REFERENCES
                                                users(id),
                         name, hash, revoked_at, last_used_at)

clients                 (id uuid, tenant_id, slug, display_name,
                         timezone text NOT NULL DEFAULT 'UTC',
                         deleted_at, version int NOT NULL DEFAULT 1)
client_links            (id uuid, tenant_id, client_id, source_id,
                         external_id, external_name,
                         version int NOT NULL DEFAULT 1)
client_policies         (id uuid, tenant_id, client_id, category,
                         approved_products text[], agent_sla_days,
                         version int NOT NULL DEFAULT 1)

-- Canonical device entity (§4.17). Same shape as clients: Operations owns
-- the row, sources contribute observations via device_links.
devices                 (id uuid, tenant_id, client_id,
                         canonical_hostname, canonical_serial nullable,
                         canonical_vm_uuid nullable,
                         device_kind text CHECK (device_kind IN
                           ('physical','vm-with-agent','vm-agentless',
                            'hypervisor-host','network-device','unknown')),
                         deleted_at, version int NOT NULL DEFAULT 1)
device_links            (id uuid, tenant_id, device_id, source_id,
                         external_id, external_name,
                         first_seen_at, last_seen_at,
                         version int NOT NULL DEFAULT 1)

-- Canonical end-user entity — a client's employee / end-user, distinct
-- from `operations.users` (Django auth users; the AMRose operators
-- logging into Operations). Planned for a later module; shape declared
-- now so device_links / audit / findings can reference consistently.
client_users            (id uuid, tenant_id, client_id nullable,
                         canonical_email nullable,
                         canonical_username nullable, display_name,
                         deleted_at, version int NOT NULL DEFAULT 1)
client_user_links       (id uuid, tenant_id, client_user_id,
                         source_id, external_id, external_name,
                         version int NOT NULL DEFAULT 1)

-- source_instances.client_id is NULLABLE. Tenant-level sources
-- (e.g., fleet-wide Ninja OAuth credential that discovers all Ninja
-- orgs) have client_id = NULL. Per-client sources (AD, DHCP,
-- vCenter, per-tenant M365 Graph) carry client_id.
source_instances        (id uuid, tenant_id, client_id uuid nullable,
                         source_id, config jsonb, enabled,
                         CHECK (
                           -- source_kind determines whether client_id
                           -- is required; enforced in application layer
                           -- via source.capabilities.scope ∈
                           -- {'tenant','client','either'}
                           TRUE
                         ))
collector_instances     (id uuid, tenant_id, name, kind, token_hash,
                         version, capabilities jsonb, last_heartbeat_at)
source_bindings         (id uuid, tenant_id, source_instance_id,
                         collector_instance_id, schedule text,
                         enabled, version)

entity_observations     (see §4.7 — includes tenant_id, uuid ids)
dead_letter_observations (id uuid, tenant_id, source_binding_id nullable,
                         collector_instance_id, received_at, envelope jsonb,
                         reject_reason, resolved_at, resolved_by)

software_decisions      (id uuid, tenant_id, client_id, canonical_name,
                         decision text CHECK (decision IN
                           ('approve','reject','investigate',
                            'approve_publisher')),
                         reason, decided_by bigint REFERENCES users(id),
                         decided_at, version)

-- Current-state derived table populated by
-- refresh_software_installations_current() (§4.5). Real table, RLS-
-- enforced, populated only via the SECURITY DEFINER refresh function
-- (M0 grants: EXECUTE on the function, not direct writes on the table).
-- Composite PK; no synthetic uuid — software is observation-only and
-- has no canonical id per §4.5, §5.15.
software_installations_current
                        (tenant_id, client_id uuid, device_id uuid,
                         canonical_name text, publisher, version,
                         install_location, install_date,
                         first_observed_at, last_observed_at,
                         refreshed_at,
                         PRIMARY KEY (tenant_id, client_id, device_id,
                                      canonical_name))

-- merge_candidates denormalizes the member fields it needs so that the
-- 90-day observation retention (§4.13) does not create dangling refs.
-- We keep the observation IDs for provenance, but they may become NULL
-- after retention; the denormalized member_snapshots row is what the
-- merge review UI actually reads.
merge_candidates        (id uuid, tenant_id, client_id, entity_type,
                         canonical_key,
                         member_snapshots jsonb NOT NULL,   -- [{obs_id, source, external_id, hostname, last_seen, ...}]
                         member_observation_ids uuid[],     -- nullable / historical
                         match_reason text, confidence numeric,
                         status text CHECK (status IN
                           ('open','merged','split','rejected')),
                         version int)

findings                (id uuid, tenant_id, finding_type_id,
                         subject_type text CHECK (subject_type IN
                           ('client','device','client_user',
                            'source_binding','collector_instance')),
                         subject_id uuid NOT NULL,
                         finding_details jsonb NOT NULL DEFAULT '{}',
                             -- carries software canonical_name, etc.
                             -- for findings whose narrative involves an
                             -- entity kind not in subject_type.
                         severity text CHECK (severity IN
                           ('critical','high','medium','low','info')),
                         status text CHECK (status IN
                           ('open','acknowledged','investigating',
                            'suppressed','resolved','wontfix')),
                         owner_id bigint nullable REFERENCES users(id),
                         sla_due_at, first_seen_at, last_seen_at,
                         last_reviewed_at,
                         version int NOT NULL DEFAULT 1)
suppression_rules       (id uuid, tenant_id, finding_type_id,
                         subject_match jsonb, reason, expires_at,
                         created_by bigint REFERENCES users(id),
                         created_at)
notification_routes     (id uuid, tenant_id, client_id nullable,
                         finding_type_id nullable,
                         severity_min text CHECK (severity_min IN
                           ('critical','high','medium','low','info')),
                         channel text CHECK (channel IN
                           ('email','slack','teams','webhook')),
                         target text,
                         mode text CHECK (mode IN
                           ('immediate','digest')))

secrets                 (id uuid, tenant_id, name, encrypted_value bytea,
                         rotated_at, created_by bigint REFERENCES users(id))

-- audit_log (see §4.11). Full schema:
audit_log               (audit_id uuid, tenant_id,
                         actor_id bigint nullable REFERENCES users(id),
                         actor_kind text CHECK (actor_kind IN
                           ('user','collector','system')),
                         source text CHECK (source IN
                           ('ui','api','ingest','management_command',
                            'background_job','celery')),
                         action text, entity_type text, entity_id uuid,
                         before_state jsonb, after_state jsonb,
                         ip_address inet, user_agent text, occurred_at)

run_log                 (id uuid, tenant_id, kind, subject_ref jsonb,
                         started_at, ended_at, ok bool, rows int,
                         error text)
```

RLS policy on every table above:

```sql
ALTER TABLE operations.<t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.<t> FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.<t>
  USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
```

`FORCE` applies RLS even to the table owner. The `TRUE` (`missing_ok`)
argument to `current_setting` returns `NULL` when the GUC is unset;
casting `NULL::bigint` yields `NULL`, and the comparison
`tenant_id = NULL` evaluates to `NULL` (not `TRUE`), so RLS returns
zero rows. An unscoped connection therefore cannot read tenant data —
correct outcome; no exception raised. See §6.3 for how the setting
is guaranteed to be present in normal request flow.

**Layered tables (`tenant_id NULLABLE`, RLS allows NULL or match).**

```
software_catalog        (id uuid, tenant_id nullable, canonical_name,
                         categories text[], publisher_hint,
                         eol_date nullable, notes)

-- Uniqueness split by whether tenant_id is NULL. Postgres treats
-- multiple NULLs in a UNIQUE as distinct by default, so one plain
-- UNIQUE (tenant_id, canonical_name) would permit duplicate global
-- rows. Two partial indexes prevent that:
CREATE UNIQUE INDEX software_catalog_global_unique
  ON operations.software_catalog (canonical_name)
  WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX software_catalog_tenant_unique
  ON operations.software_catalog (tenant_id, canonical_name)
  WHERE tenant_id IS NOT NULL;
```

Global rows have `tenant_id = NULL`; tenant overrides carry
`tenant_id`. Read pattern (see §5.14):

```sql
SELECT DISTINCT ON (canonical_name) *
FROM operations.software_catalog
WHERE tenant_id IS NULL
   OR tenant_id = current_setting('operations.tenant_id', TRUE)::bigint
ORDER BY canonical_name, tenant_id NULLS LAST;
```

RLS policy:

```sql
CREATE POLICY tenant_or_global ON operations.software_catalog
  USING (tenant_id IS NULL
      OR tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
```

Writes to `tenant_id IS NULL` rows require the `manage_catalog`
permission (§5.4), enforced in the serializer — not RLS. Tenant
overrides require the same permission scoped to the current tenant.

### 6.2 Read-only reads from existing schemas

- `ninja_core.organizations`, `ninja_core.devices`,
  `ninja_core.device_snapshots`.
- `ninja_patches.patch_facts`, `ninja_patches.current_patch_state`,
  `ninja_patches.device_troubleshooting_signal`.
- `ninja_inventory.v_source_observations_current` and merge-candidate
  views (migrations 060–064) — Operations wraps these with its own
  merge-review workflow tables.
- `ninja_agent_compliance.platform_observations` — the concrete
  precedent for the generalized `entity_observations`. v1 keeps both
  and reconciles; v2 may collapse.

### 6.3 RLS setting lifecycle

`operations.tenant_id` is a Postgres GUC set per connection or per
transaction. All application code paths must set it before running
queries; RLS policies fail closed (no rows returned) when unset.

Roles:

- `operations_app` — application role used by Gunicorn workers.
  Cannot bypass RLS. Must set `operations.tenant_id` before any query.
- `operations_migrate` — has `BYPASSRLS`. Used only by Django migrations
  and `manage.py` commands that legitimately need cross-tenant access.
- `operations_readonly` — used by the whitelisted Queries page runtime.
  Cannot bypass RLS. Runs under the same `ATOMIC_REQUESTS=True` as
  the rest of the app, so `SET LOCAL operations.tenant_id` set by
  `TenantMiddleware` persists across the query. If a query dispatch
  ever bypasses ATOMIC_REQUESTS (e.g. streaming very large result
  sets), the view must open its own `transaction.atomic()` and
  re-issue `SET LOCAL` inside it.
- `metabase_ro` — used by Metabase for its own read-only queries.
  Cannot bypass RLS; Metabase questions declare tenant explicitly.

Setting the GUC — **transaction-scoped, not connection-scoped:**

`SET LOCAL` only persists inside an open transaction. Django defaults
to **autocommit mode**, where each query opens and closes its own
implicit transaction — so a `SET LOCAL` issued outside an explicit
transaction is silently discarded before the next query runs. This is
the specific footgun that would let a middleware-set tenant GUC
disappear before views execute a query. Guaranteed contract:

- **`DATABASES['default']['ATOMIC_REQUESTS'] = True`** in Django
  settings. Every request runs inside one transaction; `SET LOCAL`
  set at the top of the request persists to every query in that
  request; commit/rollback at the end resets automatically.
- Long-lived request handlers that need explicit nested transactions
  use `transaction.atomic()` savepoints, not top-level transactions —
  the outer request transaction owns the GUC lifetime.

Concrete request-scope flow:

- **`TenantMiddleware`** runs after auth, before view dispatch.
  Resolves tenant from the request (v1: always `1`; multi-tenant:
  from `request.user.tenant_id`). Issues
  `SET LOCAL operations.tenant_id = %s` on the current connection —
  which is inside the ATOMIC_REQUESTS transaction — using
  parametrized SQL through `connection.cursor()`.
- A **query-time assertion** (`connection.execute_wrappers` hook,
  enabled when `DEBUG=True` or `OPERATIONS_STRICT_TENANT=1`) verifies
  `SHOW operations.tenant_id` returns non-empty on every query.
  Requests that reach a query without the GUC set raise `500` and
  log; the RLS policy already ensures no data leak either way, but
  this catches misconfiguration during development.

Non-request execution paths:

- **Management commands.** Wrapped in a `with tenant_context(tenant_id):`
  context manager that opens `transaction.atomic()` and issues
  `SET LOCAL`. Refusing to enter this context = command aborts.
- **Celery / background jobs.** Same context manager, tenant read from
  the job payload.
- **Collector ingest endpoint.** `TenantMiddleware` applies exactly as
  it does for UI requests; tenant resolved from
  `collector_instances.tenant_id` at token validation, then set as
  GUC before any tenant-table write.
- **Migrations.** Run under `operations_migrate` with `BYPASSRLS`.
  Migrations must not use `SET LOCAL operations.tenant_id` — they
  operate cross-tenant by design.
- **Health check (`/healthz`).** Uses a dedicated `operations_health`
  role that can only `SELECT 1` — no table access. No RLS involvement.
  Not wrapped in ATOMIC_REQUESTS (explicitly excluded via route
  decorator) to keep the health path free of transaction overhead.

Consequence of ATOMIC_REQUESTS worth naming: every view runs in a
single transaction. Views that intentionally want to commit partial
work mid-request (rare) must use `transaction.non_atomic_requests` on
the view decorator + open explicit inner transactions. This is a
known-quantity Django pattern; not a novel constraint.

Documented in `operations/db/tenant.py`; violated by tests via a
pytest fixture that resets the GUC between tests.

### 6.4 Dead-letter observations

Ingest that cannot be resolved to a canonical entity, source_instance,
or schema version lands in `dead_letter_observations`:

- Full envelope preserved as `jsonb`.
- `reject_reason` enumerated: `unlinked_external_identity`,
  `unknown_binding`, `unknown_schema_version`, `hash_mismatch`,
  `validation_failed`.
- A finding is created against the `source_binding` or
  `collector_instance` (subject-polymorphic, see §5.15), so the
  problem is visible in the operator queue.
- The Sources page has a "Dead-Lettered" tab showing counts, grouped
  by external identity (Ninja org id, AD SID, VM UUID, etc.), with a
  "Bind / Create + bind / Suppress" action per group (§5.7).
- Retention: unresolved retained indefinitely; resolved retained 30
  days past `resolved_at`.

## 7. URL contract

Committed. Both apps honor. Documented in `docs/url_contract.md`.

```
/                                                    → redirect to last selected client
/orgs/{slug}/                                        → client overview
/orgs/{slug}/inventory/devices/                      → device list + merge queue
/orgs/{slug}/inventory/devices/{device_id}/
/orgs/{slug}/inventory/software/                     → software list + decisions
/orgs/{slug}/inventory/software/{canonical_name}/
/orgs/{slug}/inventory/policy/                       → client policy editor
/orgs/{slug}/inventory/reports/{report_name}/
/orgs/{slug}/inventory/queries/{query_name}/
/orgs/{slug}/findings/                               → finding queue for this client
/orgs/{slug}/findings/{id}/
/orgs/all/inventory/software?product={canonical_name}
/admin/                                              → Django admin (superuser only)
/api/                                                → DRF root
/api/docs/                                           → Swagger
/api/observations                                    → collector ingest (POST)
/api/work                                            → collector task pull (GET)
/healthz                                             → 8091, loopback
```

Metabase columns must build URLs conforming to this contract.

## 8. v1 build order

Milestones. Each ships to prod behind a feature flag until reviewed.

**M0 — Foundation** (~1 week)

- Django app skeleton in `operations/`.
- Compose service `operations` on ports 3002 + 8091.
- Postgres schema `operations` + first migration:
  - Global tables: `tenants`, `sources`, `collectors`, `finding_types`.
  - Tenant-scoped tables: `users`, `user_tokens`, `clients`,
    `client_links`, `source_instances`, `collector_instances`,
    `source_bindings`, `dead_letter_observations`, `audit_log`,
    `run_log`, `secrets`.
  - Layered table: `software_catalog`.
  - RLS policies + roles (§6.3): `operations_app`,
    `operations_migrate`, `operations_readonly`, `operations_health`.
- **Bootstrap migration (`0002_bootstrap_clients`, one-shot):** seed
  `operations.clients` from `ninja_core.organizations`, populate
  `client_links` with `source='Ninja'` rows. This is the *only*
  migration in which Ninja is authoritative for canonical identity
  (§4.17, §5.1).
- Seed rows:
  - `sources`: Ninja only in M0 (SentinelOne, LogMeIn, ScreenConnect,
    AD, DHCP, vCenter, HyperV added when their ingest modules land).
    Seeding taxonomy without any code path invites confusion.
  - `collectors`: `internal-ingest` (in-process pipeline used by the
    ingest container, §4.9) and `ninja-hosted-script` (external
    HTTPS collectors running under Ninja scripts). Other kinds
    (`native-agent`, `file-drop`, `manual`) added when implemented.
  - `collector_instances`: one row for the `internal-ingest`
    collector serving tenant 1, used by the ingest container.
  - `finding_types`: baseline set — `unlinked_external_identity`,
    `stale_collector_binding`, `unauthorized_rmm`, `unauthorized_av`,
    `unauthorized_remote_access`, `install_path_suspicious`,
    `rare_recent`, `eol_runtime`, `suspicious_name`,
    `multi_av_conflict`. Each seeded with `runbook_path` pointing at
    a stub `docs/runbooks/{type}.md` (see M0 deliverable below).
- **DB privilege grants** (in the same migration):
  - `operations_app` → `USAGE, SELECT, INSERT, UPDATE, DELETE` on all
    `operations.*` tables and sequences.
  - `operations_migrate` → owner of `operations.*`; `BYPASSRLS`.
  - `operations_readonly` → `USAGE, SELECT` on `operations.*` (Queries
    page, §5.13, §6.3).
  - `operations_health` → `SELECT 1` no table grants.
  - `metabase_ro` → `USAGE, SELECT` on `operations.*` (deep-link
    reports).
  - `ninja_ingest` (existing role from ninja-dashboard) —
    - `USAGE, SELECT, INSERT` on
      `operations.entity_observations`,
      `operations.dead_letter_observations`,
      `operations.run_log`.
    - `EXECUTE` on
      `operations.refresh_software_installations_current(bigint)`
      (and any future `refresh_*_current` functions).
    - **No direct write grant on
      `operations.software_installations_current`.** The current-state
      table is populated only via the `SECURITY DEFINER` refresh
      function, which runs as its owner (`operations_migrate`) and
      handles the cross-tenant read + write without granting the
      caller elevated privileges.
    - No other tables. This is what lets the existing ingest
      container write through the internal-ingest collector without
      being able to touch policy, catalog, findings, or decisions.
- **Runbook stubs (M0 deliverable):** one `docs/runbooks/{type}.md`
  per seeded finding_type. Each file has H1 title + "Placeholder —
  runbook TBD" body. Filled in as milestones activate the finding
  type. Prevents the "referenced runbook doesn't exist" 404 in the
  finding detail page.
- Auth (local backend), Django admin, seed user + `admin`,
  `operator`, `viewer` groups.
- Base template with brand context processor + client selector.
- Middleware: `TenantMiddleware`, `ClientScopeMiddleware`.
- CI: black / ruff / mypy / pytest + Playwright smoke.

**M1 — Devices submodule** (~2 weeks)

- Canonical device entity: `operations.devices` + `device_links`
  binding `device → (source, external_id)`. Mirrors client-first
  shape (§4.17).
- `merge_candidates` table + review workflow — same shape used later
  for users and any future canonical entity type.
- Read views onto `ninja_inventory.v_source_observations_current`
  (migrations 060–064) as one *observation source*, not the truth.
- Approve / Reject / Split candidates → resolves to a canonical
  device, writes/updates `device_links` rows. Audit rows on every
  action.
- Bootstrap import: reconcile existing Ninja devices from
  `ninja_core.devices` into `operations.devices` with matching
  `device_links`. Same one-shot pattern as M0 clients.
- Device detail page (cross-source view): all links, all
  observations, no source-of-truth badge — Operations *is* the
  source of truth for the canonical row.
- Deep-link contract wired.
- Metabase links from device rows in current dashboards. Dashboard
  migration to `device_links` is per-dashboard, not required in M1.

**M2 — Software submodule ingest + classification** (~2 weeks)

- `ingest/inventory/software.py` in the existing ingest container:
  pulls `/queries/software` (fleet-wide) or per-device fallback,
  writes to `entity_observations`.
- Software catalog seed (RMM, AV_EDR, Remote_Access ~50 products
  total).
- Classification module runs at ingest, stamps rule results as
  findings.

**M3 — Software submodule UI + decisions** (~2 weeks)

- Software list with filter (category, rule, decision status).
- Decision buttons (Approve / Reject / Investigate) with reason.
- Client policy editor for RMM / AV / Remote_Access.
- Importer for existing `decisions_global.csv` — one-shot management
  command, tagged with `source='csv_import_2026'`.

**M4 — Findings & reports** (~1 week)

- Finding queue + assignment + suppression.
- 5 canonical software reports (unauthorized RMM by org, unauthorized
  AV, rare+recent, decisions activity, coverage gaps).
- 3 canonical device reports (unmanaged VMs, merge candidates by age,
  source coverage).

**M5 — Queries page + polish** (~1 week)

- Whitelisted query registry. Read-only Postgres role for the queries
  runtime.
- 10 seed queries covering the top ad-hoc questions.
- Login page polish. Notification routes (email only in v1).
- Retention job. Documentation pass.

**Total: ~9 weeks of engineering to v1.** Individual milestones can ship
independently behind flags — devices submodule delivers value on its own
before software lands.

## 9. Planned but not v1

Named to prevent re-designing later.

- Bulk operations (approve/reject N rows with shared reason).
- Global search (hostname / org / product from anywhere).
- Universal CSV export from every list view.
- Saved views / bookmarks per user.
- Recent activity feed per client.
- Print / PDF client reports.
- Webhooks out (PSA integration, Slack channels).
- Data-quality dashboard (stale sources, missing fields, low coverage).
- Feature flags per user or per client.
- Prometheus / OpenTelemetry metrics export.
- Additional collector kinds: native agent, direct pull, file drop,
  manual upload.
- Additional sources: AD (via Ninja-collector), Windows DHCP, direct
  vCenter, direct Hyper-V, M365 Graph, Entra ID, backup vendors.
- Additional finding categories: `EOL_Runtime` reports, network device
  discovery, backup coverage gaps.
- SSO backend (Google Workspace OIDC).
- `django-otp` on local backend if MFA required for routine use.
- Custom RBAC framework if per-client scoping of operators required.

## 10. Explicit non-coverage

- **CIS Controls 1.3, 1.4, 1.5** — active discovery, DHCP logging,
  passive discovery. Would need additional data sources not in v1.
- **CIS Controls 2.6, 2.7** — library allowlisting, script
  allowlisting. Requires EDR or application-allowlisting integrations
  we don't have.
- **SaaS features** — sign-up, billing, per-tenant admin, uptime SLA.
  Multi-tenant seam preserved; product surface not built.
- **Legal frameworks** — DPA per external MSP, sub-processor list,
  breach notification workflow. Required before any external MSP
  customer; out of v1 scope.
- **Real-time / websocket updates.**
- **Mobile-optimized UI.**
- **Internationalization.**

## 11. Environment + Ops

- **Prod:** am-ch-01, Portainer auto-deploy from `master` branch
  (confirmed against ninja-dashboard's REQUIREMENTS.md §7 and the live
  repo). Compose file adds `operations` service. Real `.env` in
  `/amr-ch-01_data/ninja-dashboard/`.
- **Dev:** Windows workstation. `docker compose up --build` brings the
  full stack including Operations. Postgres seeded via
  `manage.py seed --scenario=realistic` against an anonymized snapshot
  pulled with `scp am-ch-01:/amr-ch-01_data/ninja-dashboard/backups/…`.
- **Branch strategy:** development on `feature/operations-v1` until M0
  ships behind a flag. Subsequent milestones on short-lived branches;
  merge to `master` when ready to deploy. Aligns with the existing
  `master (prod) / develop (integration) / feature|fix|chore/*` model
  in REQUIREMENTS.md §7.
- **Backups:** Postgres backups inherit ninja-dashboard's existing
  `pg_dump` job — no new backup config needed. Verify `operations`
  schema is in scope.
- **Secrets rotation runbook:** `docs/runbooks/rotate_secrets.md`
  covers Django SECRET_KEY, session key, DB DSN, collector tokens,
  per-client credentials. Rotation via management command.
- **Metrics:** deferred (planned-not-v1). Structured logs to stdout
  match existing container pattern.

## 12. Governance

Follows `Development/DEVELOPMENT.md`:

- BLUEPRINT (this file) is the current in-flight design and is
  overwritten per major task cycle. Superseded content moves to
  `docs/decisions/`.
- Commit-hash reporting after every push per Agent Work Rule #6.
- `TODO.md` Inbox / Backlog / Completed maintained.
- CHANGELOG updated on every version bump; VERSION starts at `0.1.0`.
- `CONTEXT.md` for Operations added after M0 lands.

---

## Sign-off

The design in §1–4 and §6–12 is locked pending BLUEPRINT approval.
§5 blocks require a walkthrough before M0 begins — either inline in
this document (mark boxes) or in a review session.

**First-migration critical (irreversible-with-difficulty):**

- §4.17 canonical entity principle — clients, devices, users are all
  first-class in Operations; sources are observations. Ninja is not
  a parent.
- §5.1 client-first canonicalization + one-shot bootstrap from
  `ninja_core.organizations` (bootstrap ≠ authority).
- §5.2 schema ownership rule (Django `operations` schema vs SQL-managed
  `ninja_*` schemas).
- §5.3 custom user model on `AbstractUser` (Operations login users,
  distinct from canonical `client_users`).
- §5.14 `software_catalog` layering with nullable `tenant_id`.
- §5.15 finding subject polymorphism (no nullable `client_id` on
  findings; `dead_letter_observations` for unresolved ingest).

These six must be reviewed and locked before any code lands. The rest
of §5 is cheap to change during the milestones.

### Review changelog

- **draft v0.1** — initial draft.
- **draft v0.2** — review feedback incorporated. Changes:
  - §4.5 `rare_recent` inequality direction fixed.
  - §4.9 collector envelope IDs clarified as UUIDs; reference-table IDs
    as small ints.
  - §4.16 tenant-scoping split into three explicit classes (Global /
    Tenant-scoped / Layered); Django auth position documented; RLS
    bypass rules named.
  - §5.1 mapping/backfill from `ninja_core.organizations` spelled out.
  - §5.14 `software_catalog` layering rule made explicit.
  - §5.15 finding subject polymorphism added; kills nullable
    `client_id`.
  - §6.1 rewritten by scoping class; all instance IDs typed `uuid`,
    reference IDs `smallserial`; `dead_letter_observations` added;
    RLS policy statements included; `FORCE ROW LEVEL SECURITY` and
    `missing_ok = TRUE` semantics documented.
  - §6.3 RLS lifecycle section added — role split, GUC set/reset
    contract, migration/management-command/health-check behavior.
  - §6.4 dead-letter workflow documented.
  - §11 prod branch corrected to `master`; branch strategy aligned to
    REQUIREMENTS.md §7.
- **draft v0.9** — review pass v3 items resolved.
  - §5.15 subject_type: `software` removed. Software is
    observation-only per §4.5 with no canonical UUID id to target;
    software-related findings now target `device` (per-install) or
    `client` (aggregate). Added `finding_details jsonb` column on
    `findings` to carry `canonical_name` and other software
    attributes for display and dedup. §6.1 CHECK constraint updated.
  - §5.15 `findings_by_client` view corrected: `SELECT id AS
    client_id FROM operations.clients` on the client branch
    (`clients` has `id`, not `client_id`). Software resolution
    branch removed (no longer a valid subject_type).
  - §4.13 retention rewritten to remove the stale "materialized
    views" language. Current-state tables are regular RLS tables
    (§4.5); retention calls the refresh functions before pruning.
  - §4.16 tenant-scoped list + §6.1 inventory both updated to include
    `software_installations_current` as a tenant-scoped RLS table.
    Migrations, grants, and RLS policy coverage now name it
    explicitly.
  - §4.5 refresh function's `ON CONFLICT` clause now uses
    `LEAST(t.first_observed_at, EXCLUDED.first_observed_at)` and
    `GREATEST(...)` for `last_observed_at`, preserving age semantics
    across backfills and replayed older observations.
- **draft v0.8** — self-review pass v2 items resolved.
  - Header status corrected from `draft v0.1` (stale) to current.
  - §6.1 `manage_global_taxonomy` reference renamed to `manage_taxonomy`
    to align with the §5.4 permission catalog.
  - §4.7 `entity_observations` gains promoted columns `client_id`,
    `device_id` (both nullable, filled at binding resolution).
    Downstream tables and views read the promoted columns, not
    `raw_data`/`canonical_data`. `entity_key` documented per
    entity_type. Note added on binding-resolution flow.
  - §4.5 `software_installations_current` reshaped from a
    materialized view to a **regular tenant-scoped table with RLS**.
    Materialized views don't re-run base-table RLS at query time
    and can't carry `CREATE POLICY`, so a MV was not tenant-safe.
    Refresh happens via a `SECURITY DEFINER` function
    `refresh_software_installations_current(p_tenant_id)` owned by
    `operations_migrate` (BYPASSRLS). Full SQL for the table, RLS
    policy, and refresh function inlined.
  - §8 M0 grants adjusted: `ninja_ingest` gets `EXECUTE` on the
    refresh function, no direct write on
    `software_installations_current`. Elevated cross-tenant refresh
    is bounded to the SECURITY DEFINER function; the caller stays
    unprivileged.
- **draft v0.7** — self-review pass. Design gaps and doc
  inconsistencies flagged in v0.6 addressed:
  - §5.14 RLS cast corrected from `::int` to `::bigint` (matched to
    §6.1 `tenant_id bigint`).
  - §4.9 unified ingest write path — HTTP and in-process both go
    through `operations.ingest.observation_pipeline`. Added
    `internal-ingest` collector kind + M0 seed row so the existing
    `ingest/` container writes with a real `collector_instance_id`,
    same idempotency + validation + dead-letter handling as HTTPS
    collectors.
  - §4.5 defined `software_installations_current` materialized view
    — the current-state target rules run against. Refresh strategy,
    unique index, RLS behavior spelled out. Clarifies software as
    observation-only (no canonical `software_row` table).
  - §4.13 retention rewritten to resolve the observation-vs-
    merge-candidate conflict: retention job first refreshes
    current-state views + denormalizes merge candidate provenance
    (into new `member_snapshots jsonb` column on `merge_candidates`),
    then prunes observations. Prune order + failure semantics named.
  - §6.1 merge_candidates now carries `member_snapshots jsonb`
    (denormalized member metadata) alongside the
    `member_observation_ids uuid[]` (provenance-only, may become
    NULL post-retention).
  - §6.1 optimistic-locking `version` columns added to `clients`,
    `client_links`, `devices`, `device_links`, `client_users`,
    `client_user_links` — bringing §6.1 into line with §5.9's
    "applies to any decision-write" claim.
  - §6.1 enum column types made explicit via CHECK constraints on
    `devices.device_kind`, `software_decisions.decision`,
    `merge_candidates.status`, `findings.subject_type`,
    `findings.severity`, `findings.status`,
    `notification_routes.channel`, `notification_routes.mode`,
    `notification_routes.severity_min`, `audit_log.actor_kind`,
    `audit_log.source` (which now includes `background_job` and
    `celery`).
  - §6.1 `users.id` explicitly bigserial (Django AbstractUser
    default); all references (`owner_id`, `actor_id`, `decided_by`,
    `resolved_by`, `created_by`) typed `bigint REFERENCES users(id)`.
    Consistency note added: uuid PK on entity tables, bigint FK to
    users.
  - §6.1 `users.tz` renamed to `users.timezone` for consistency
    with `clients.timezone`. Default `'UTC'`.
  - §4.12 unique key on `entity_observations` extended to include
    `tenant_id` for defense-in-depth against cross-tenant collisions.
  - §5.14 permission name aligned to `manage_catalog` (from §5.4);
    removed the orphan `manage_global_catalog`.
  - §5.15 `findings_by_client` view definition inlined (SQL, with
    an explicit note that infrastructure-scoped findings are
    excluded).
  - §6.3 Queries page role now names its ATOMIC_REQUESTS relationship
    explicitly.
  - §5.8 fixture anonymization policy defined — separate
    `manage.py anonymize` step, deterministic keyed-hash rules,
    encrypted secrets dropped rather than anonymized.
  - §8 M0 seed narrowed to only implemented `sources` and
    `collectors`. Added DB privilege grants (`operations_app`,
    `operations_migrate`, `operations_readonly`, `operations_health`,
    `metabase_ro`, `ninja_ingest`) as an M0 migration.
    Runbook stubs added as an M0 deliverable to prevent
    referenced-but-missing files.
  - §4.13 client single-timezone caveat added — multi-site clients
    pick their primary; per-report override deferred.
- **draft v0.6** — remaining §5 blocks approved with two edits.
  - §5.4 permissions defined as a real capability catalog
    (`view_clients`, `write_decisions`, `approve_merges`,
    `manage_findings`, `manage_client_policy`, `manage_catalog`,
    `manage_collectors`, `manage_sources`, `manage_secrets`,
    `manage_users`, `manage_taxonomy`, `run_queries`, etc.).
    Groups become named bundles; views/serializers gate on
    permission name, never group name.
  - §5.6 canonical normalization split into type-specific helpers —
    `canonical_text`, `canonical_hostname`, `canonical_username`,
    `canonical_email`, `canonical_mac`, `canonical_serial`,
    `canonical_uuid`. Per-field rules named and inspectable;
    calling `canonical_text` on typed data is a code-review
    error.
  - §5.5, §5.7, §5.8, §5.9, §5.10, §5.11, §5.12, §5.13 approved
    without changes. All 15 §5 blocks now have decisions.
- **draft v0.5** — §5 approval-with-edits applied. Changes:
  - §5.1 decision block now names `source_instances.client_id`
    nullability explicitly (schema-side already correct in v0.4;
    decision text updated).
  - §5.15 `subject_type` uses `client_user` (not `user`) to avoid
    collision with Django login users. `subject_id` typed `uuid`.
    Polymorphic FK integrity section added — enforcement in
    serializer/service layer via `(subject_type, subject_id,
    tenant_id)` lookup, orphan-scan nightly job for deletion
    handling.
  - §4.17 wording updated: "users" split into "client users" with
    explicit note distinguishing from `operations.users` (Django
    auth).
  - §5.1, §5.2, §5.3, §5.14 approved without further edits.
- **draft v0.4** — review v2 feedback incorporated. Changes:
  - §6.3 `SET LOCAL` + autocommit footgun addressed:
    `ATOMIC_REQUESTS=True` mandated; request-scope, management-command,
    Celery, ingest, migration, and health-check flows spelled out;
    query-time assertion hook added for dev-mode misconfiguration
    catch.
  - §4.7 `entity_observations` types corrected — instance IDs are
    `uuid`, `tenant_id` is `bigint`, `client_id` is nullable `uuid`
    (nullable until binding resolved).
  - §6.1 `source_instances.client_id` made nullable — tenant-level
    sources (e.g., fleet-wide Ninja) have `client_id = NULL`;
    per-client sources carry it. Scope declared per source kind in
    `sources.capabilities`.
  - §4.16 + §6.1 Django auth join tables named explicitly:
    `user_groups`, `user_permissions` as tenant-scoped custom
    Through models with `tenant_id` + RLS. Closes the join-table
    hole where `auth_user_groups` would otherwise reference
    tenant-scoped `user_id` without carrying `tenant_id` itself.
  - §6.1 `software_catalog` unique constraint replaced with two
    partial unique indexes — one on `canonical_name WHERE tenant_id
    IS NULL`, one on `(tenant_id, canonical_name) WHERE tenant_id
    IS NOT NULL`. Prevents duplicate global rows.
  - §6.1 RLS `missing_ok` explanation corrected: `NULL::bigint`
    yields `NULL`, comparison returns `NULL` (not exception),
    RLS returns zero rows.
- **draft v0.3** — canonical entity principle promoted. Changes:
  - §4.17 added — canonical entity principle. Clients, devices,
    users are first-class in Operations; sources are observations;
    Ninja is not authoritative for identity except during M0
    bootstrap.
  - §5.1 rewritten client-first. M0 bootstrap explicitly framed as
    bootstrap-not-authority.
  - §5.7 renamed and generalized: `unlinked_external_identity` covers
    any external identity (client, device, user, VM UUID, etc.)
    arriving without a canonical link.
  - §5.15 and §6.4 aligned to `unlinked_external_identity` naming.
  - §6.1 adds canonical `devices` + `device_links`, and
    `client_users` + `client_user_links` shape (M1 activates devices;
    users declared for future consistency).
  - §8 M0 expanded to seed reference taxonomy (sources, collectors,
    finding_types) and roles (§6.3). M1 reshaped to build canonical
    devices with links, not just merge candidates.
  - Sign-off first-migration-critical list now names §4.17
    explicitly.
