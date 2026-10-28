# PLAN-026 — Source configuration UI

## Status and lifecycle

- Status: ready; design and implementation have not started.
- Defined: 2026-10-28
- Started: —
- Completed: —
- Blueprint: — (planning only; establish an Operations blueprint when implementation is authorized)

## Goal and scope

Add an administrator workflow to create a supported source instance and bind it
to an ingest collector from Operations. The workflow must handle client-scoped
and shared sources, keep connection secrets in the private runtime environment,
and make creation, activation, and first collection deliberate actions.

Initial scope is source creation and its required collector binding, plus the
minimum detail/activation path needed to make a newly created source usable.
Existing Sources status, refresh, and schedule behavior remains compatible.
Do not add arbitrary JSON editing, secret-value entry/storage, source deletion,
client mapping, or automatic collection during form submission. Source-specific
config fields are typed and validated; the first supported platform set is
confirmed during implementation planning, with ScreenConnect shared/client
configuration included.

## Current behavior and design constraints

- `/sources/` is a monitoring surface. Staff can request a refresh and change a
  binding schedule; it has no source-instance creation form.
- `SourceInstance`, `CollectorInstance`, and `SourceBinding` already provide
  the core records. `SourceInstance.config` is JSON; `SourceBinding` associates
  the source with a collector and schedule.
- Existing refresh and schedule POST views require administrator access, CSRF,
  tenant scoping, and the normal Jobs path. The new flow must enforce equivalent
  controls on the server, not rely on template visibility.
- Build the platform selector from supported registered source contracts, not
  arbitrary submitted connector names. Keep platform-specific settings typed;
  do not accept a raw config JSON document.
- Store only secret environment-variable references (for example
  `SC_AMROSE_EXT_GUID` and `SC_AMROSE_SECRET_KEY`). Never accept or render
  credential values. Validate reference names and document that the referenced
  variables must exist in the ingest runtime before activation; provisioning
  those runtime values remains outside the GUI.
- For shared ScreenConnect, require no client assignment and an explicit
  `CustomProperty1`–`CustomProperty8` selection. For client-scoped ScreenConnect,
  require a client. Preserve the existing instance and binding unchanged.
- Create the instance and collector binding transactionally, disabled and
  unscheduled by default. Present an explicit review/activation step; keep
  activation separate from source creation and use the existing binding-scoped
  Jobs refresh action for any first collection.
- Follow Operations tenant/RLS, admin authorization, audit, and source/Jobs
  ownership rules. Determine whether the current supported source contract
  needs a schema change before implementation; prefer the existing models.

## Candidate files

- `operations/apps/core/views.py` or a focused source-configuration view module
- `operations/apps/core/forms.py` or a focused source-configuration form module
- `operations/config/urls.py`
- `operations/templates/sources.html` and a focused create/review template
- `operations/apps/core/tests/test_sources_status.py` and focused create-flow
  tests
- `operations/BLUEPRINT.md`, this plan, and `docs/records/PLAN_REGISTRY.md`

Confirm module boundaries and test setup before editing; the list is a proposed
implementation inventory, not permission to change unrelated source behavior.

## Implementation steps

1. Reconcile the current registry and Git state; inspect supported source
   contracts, collector availability, tenant/RLS conventions, audit helpers,
   and the existing Sources/Jobs request tests.
2. Define the supported platform allowlist and typed configuration fields.
   Document required versus optional fields and secret-reference validation.
3. Add an admin-only creation form and server-side validation for source key,
   platform, source name, client/shared scope, connection fields, secret
   references, collector binding, and optional schedule (default empty).
4. Persist the source instance and disabled binding atomically with tenant
   checks, duplicate protection, and an audit event. Do not enqueue collection
   from the create POST.
5. Add a review/activation path that clearly shows the chosen scope and
   collector. Activation is an explicit POST; initial refresh remains a separate
   explicit action through the existing Jobs API.
6. Add focused request/model tests for permission denial, CSRF/POST behavior,
   tenant isolation, invalid or unsupported config, shared/client validation,
   duplicate keys, atomic rollback, disabled defaults, secret non-disclosure,
   activation, and first-run separation.
7. Run Operations checks, focused tests, migration autodetection/review, plan
   registry validation, and `git diff --check`. Update the active blueprint
   with actual validation and remaining gates.

## Acceptance criteria

- An authorized administrator can add a supported source and its binding from
  the Sources UI; ordinary users cannot create, activate, or bind sources.
- Shared ScreenConnect can be configured without a client and requires an
  explicit customer property. Client-scoped ScreenConnect requires a client.
- Source and binding are created together or not at all, remain disabled and
  unscheduled on creation, and do not trigger collection implicitly.
- Secret values never enter requests, database config, HTML, logs, fixtures, or
  tests; only validated runtime environment-variable references are stored.
- Activation and first refresh are separate visible administrator actions;
  refresh uses the existing Jobs workflow.
- Tenant/RLS isolation and existing Sources page behavior pass focused tests.
- Any required migration is identified and reviewed; no production source
  creation, activation, collection, commit, or deployment is part of this plan.

## Resume gate

This plan records requested design only. Begin implementation after explicit
user approval. Reconcile PLAN-025's current registry/checkpoint state first;
PLAN-025 supplies the shared ScreenConnect configuration contract; preserve its
connector and grouping behavior. Production source/binding writes,
activation, first collection, commit, and origin push retain their separate
approval requirements.
