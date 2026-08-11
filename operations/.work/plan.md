# Active Operations implementation plan

## E5.3 scoped maintenance — Patch Evidence Windows 11 readiness filter

**Status:** implementation and local validation complete; awaiting separate
commit and deployment approval. This is a narrow Patch Evidence reader
extension after the Ninja `w11Compatible` custom field was made API-readable
and ingested; it does not resume the deferred patch-category work or replace
any existing E5.3 scope.

**Goal:** allow an operator to restrict current device-patch evidence to the
Ninja Windows 11 compatibility result.

**Scope:** `apps/core/views.py`, `templates/patch_evidence.html`, focused
tests, and this plan. Add a fixed semantic selector in a collapsed Advanced
device attributes filter backed by the current
`ninja_core.custom_field_values` record for `w11Compatible`: Capable, Not
capable, Undetermined, or Not assessed. Preserve the generic table/CSV schema,
current patch-state semantics (one latest row per device/patch), and existing
filters/count cards.

**Out of scope:** patch-category controls, generic custom-field/query-builder
work, schema/index migrations, changes to Ninja field values or permissions,
EOL logic, and deployment until separately approved.

**Decision:** join the latest value by Ninja device ID, the same source ID
already used to attach patch evidence to an Operations device. `Capable` is an
exact stored value; alert/error prefixes map the source's Not capable and
Undetermined values without flattening the detailed Ninja result. Missing
values are explicitly selectable as Not assessed.

**Validation:** focused unit/source-contract test, Django checks, migration
drift, Python compile, scoped Ruff/format, template rendering or request smoke
check, and `git diff --check`. No migration is expected.

**Checkpoint:** fresh ingest completed with `w11Compatible` in the production
allowlist: 1,539 current device values, 801 Capable. The Evidence reader now
joins the latest field value by Ninja device ID and exposes only the semantic
filter under collapsed Advanced device attributes; the generic table and CSV
schema remain unchanged. Measured current intersection of Capable plus
`FEATURE_UPDATES` has 320 Rejected records/171 devices, 193 Manual/164, and 5
Approved/5; this evidence confirms the source device IDs align. A device can
appear in more than one status for different patches.

**Validation completed:** `pytest apps/core/tests -q` (54 passed, 2 expected
Postgres-integration skips), `manage.py check`, migration drift, Python
compile, template loading, and `git diff --check`. Whole-file Ruff/format
remain unsuitable acceptance gates because `apps/core/views.py` has known
pre-existing findings outside this scoped change.

**Next action:** review the diff, then obtain separate approval to commit and
push/deploy. No migration is included or expected.

## E5.3 scoped maintenance — Findings queue: filter-aware device impact

**Status:** deployed through `f1b5cc0`; device OS context CSV correction
validated and commit/deployment approved 2026-08-11. This is a
bounded typed-reader correction under the existing E5.3 track, not a competing
plan or a replacement for its generic-reader/CSV work.

**Goal:** make the Findings queue readable and actionable by showing an exact
count of affected devices for the active filters, providing a device-level CSV
export, and removing misleading/redundant filter presentation.

**Scope:** Operations read/UI behavior only: apply the online/coalescing
conditions before queue counts and rows; group issue types by category in the
selector; make bulk controls clearly selected-row actions; add a device-impact
count and CSV that includes direct device findings plus software-finding
exposures. Preserve finding state, decisions, routes, tenant scope, and the
existing per-row actions.

**Out of scope:** schema migrations, finding emitter changes, EOL classifier
changes, new device-list filters, data rebuilds, changing bulk-action semantics,
deployment, generic entity read models, generic CSV/redaction work, and any
other E5.3 consumer cutover.

**Decision:** one filtered finding queryset is the authority for the queue
total, severity tiles, device impact, and exports. A device impact includes
direct device-subject findings and devices exposed to matching software
findings through `operations.v_device_software_exposure`; it must not count
software titles as devices.

**Affected files:** `apps/core/views.py`, `templates/findings_queue.html`,
focused Operations tests, and this plan.

**Validation:** focused tests for filter/device-impact behavior and rendering,
Django checks/migration drift, scoped lint, and diff check. No production
queries or deployment are in scope.

**Checkpoint:** device availability/coalescing now constrains the queryset
before severity totals, headline count, rows, and exports. The header reports
the exact filtered finding count and distinct affected-device count; device CSV
has one row per device and includes the finding types that affect it. Type
options are grouped by category, and disabled bulk controls make their
selected-row scope explicit. The existing generic issue CSV remains a
complete filtered-set export so its row count agrees with the headline; the
screen itself remains capped at 500 rows for responsiveness. The follow-up CSV
will expose device OS name, release, and build wherever current inventory has
them. Lifecycle cycle and security-support end remain lifecycle-specific.

**Validation completed:** `pytest apps/core/tests -q` (51 passed, 2
Postgres-integration skips), focused Ruff for the new test, `manage.py check`,
`makemigrations --check --dry-run`, `py_compile`, and `git diff --check`.
Whole-file Ruff/format remain unsuitable as acceptance gates because
`apps/core/views.py` has pre-existing findings outside this scoped change.

**Next action:** commit the device-context CSV correction, push `origin` then
the required mirror, and verify the automatic Portainer redeploy. No migration
is included or expected.

## E5.3 scoped maintenance — Patch Evidence usable filtering

**Status:** deployed in `2bd4205`; SQL sort-expression hotfix validated and
commit/deployment approved 2026-08-11. This is an
independent, bounded reader correction under the existing E5.3 plan; it does
not alter the Findings work above or introduce patch-category work.

**Goal:** make Patching → Evidence responsive by default and let an operator
filter current patch evidence by device availability, reporting source, role,
and OS group as well as its existing status, severity, client, and patch search.

**Scope:** `apps/core/views.py`, `templates/patch_evidence.html`, focused
tests, and this plan. An unfiltered view will use the existing observed-time
index to show a clearly labelled recent slice before joining device data.

**Out of scope:** patch category filters or taxonomy work, patch ingest/data
changes, schema/index migrations, queue/finding changes, permissions, and
deployment until separately approved.

**Decision:** device availability comes from `device_session_current`, with
Any / Online / Offline / a specific registered source choices. Status and
severity selectors use Ninja's stored values so choices actually filter; this
is a reader normalization only. The screen stays capped, and no unfiltered CSV
will claim to be a complete report.

**Validation:** focused tests, Django checks, migration drift, Python compile,
scoped lint, diff check; production query-plan evidence already showed the
existing unfiltered join/sort exceeds a 10-second timeout while a filtered
feature-update title search completes in 169 ms.

**Checkpoint:** active `current_patch_state` contains 78,972 device-patch
rows. It has indexes on category, status, severity, and observed time. The
current blank Evidence page joins and sorts the complete population to show
only the first 1,000 rows. The first deployment omitted `CASE` before
`UPPER(cps.severity)` in the new sort expression, producing a syntax error;
the one-line query correction is ready for validation and deployment.

**Validation completed:** `pytest apps/core/tests -q` (54 passed, 2 existing
Postgres-integration skips), focused Ruff/format, Django checks, migration
drift, Python compile, and diff check. A production `EXPLAIN ANALYZE` of the
bounded default completed in 233 ms under a 10-second statement timeout.

**Next action:** commit the SQL syntax hotfix, push `origin` then the required
mirror, redeploy, and repeat the Evidence-page request that previously failed.
No migration is included or expected.

## E5.3 scoped maintenance — Patch Evidence filtered summary

**Status:** implementation and validation complete; commit/deployment approved
2026-08-11. This is a
small extension of the deployed Patch Evidence reader, not a competing plan.

**Goal:** show exact operational counts after any Evidence filter, so the
table is accompanied by useful scope context rather than only global status
tiles.

**Scope:** `apps/core/views.py`, `templates/patch_evidence.html`, focused
tests, and this plan. Add generic cards for matching patch records, devices,
clients, and online devices, all derived from the same filtered relation as
the table.

**Out of scope:** patch category work, ingest, schema/index migrations,
finding changes, exports beyond the existing filtered behavior, and deployment
until separately approved.

**Decision:** counts describe the current result scope. With no filter they
describe the clearly labelled recent sample; with filters they describe the
full matching relation, even if the table display is capped.

**Validation:** focused tests, Django checks, migration drift, Python compile,
scoped lint, and diff check.

**Validation completed:** `pytest apps/core/tests -q` (54 passed, 2 existing
Postgres-integration skips), focused Ruff/format, Django checks, migration
drift, Python compile, and diff check. Production `EXPLAIN ANALYZE` for the
unfiltered sample aggregate completed in 133 ms under a 10-second timeout.

**Next action:** commit the filtered-summary change, push `origin` then the
required mirror, and verify the automatic Portainer redeploy. No migration is
included or expected.

Track: **ADR-0010 generic ecosystem completion — Phase E5**

**Status:** E1-E5.2 deployed. E5.3 scope restated 2026-08-05 against measured
evidence; the typed-identity decision gate is closed. ADR-0012 states the
governing rule; see `.work/plan.md` for the full restatement.

## Goal

Expose the deployed generic entity, source-evidence, claim/effective/conflict,
candidate, relationship, and source-health contracts through tenant-safe
Operations read models and admin workflows, then cut named consumers to those
contracts only after aggregate parity.

## Scope and affected files

- additive tenant-scoped read views and narrowly scoped reveal functions in
  Django migrations; no canonical ID, source identity, or typed foreign-key
  changes
- unmanaged read models and an explicit restricted-evidence permission
- generic entity list/detail, candidate decision, relationship evidence, and
  row-based source-instance health surfaces under the existing Admin shell
- audited POST-only reveal for protected raw/restricted evidence
- named Operations/ingest/API/export/evaluator/finding/notification consumer
  inventory and parity gates before direct-table privileges are revoked
- focused contract, permission, route/template, migration, and deployed
  aggregate checks

## Confirmed inventory

- Production scale: 5,348 entity anchors, 24,980 generic links, 30,164 current
  observations, 266,594 current claims, 181,380 effective values, 168
  conflicts, 4,890 candidates, zero effective relationships, five source
  instances, and 14 active source-instance/type groups.
- Existing redacted claim/effective views are safe default readers. Django
  admin exposes some E1-E3 evidence, but the custom Operations admin has no
  generic entity/candidate/relationship pages and source health still exposes
  fixed device/client count columns.
- The Device Identity & raw tab reads raw observation JSON on ordinary GET.
  `operations_app` retains `SELECT` on observation current and underlying E3
  effective/conflict tables, although raw claims/history and all protected E4
  evidence are already denied.

## Decisions

- Basic UI visibility is registry/class driven. Source names never select
  templates, fields, or behavior. Typed client/device labels may extend the
  generic entity shell; unknown future classes use a safe generic label.
- Default list/detail reads are redacted and contain counts/placeholders for
  protected evidence. Raw or restricted values require an explicit
  permission, a POST action, tenant validation, and an `audit_log` event that
  records metadata but never the revealed value.
- The new reveal permission defaults denied; superusers retain Django's normal
  permission override. GET, CSV, findings, logs, and aggregate validation never
  include protected values.
- Generic candidate attach/reject actions call the existing E4 atomic services;
  they do not duplicate link/history/audit logic. Observed-only records remain
  visible but are not presented as pending authority decisions.
- Relationship pages initially expose deployed evidence/effective state. No
  relationship is fabricated to exercise an empty production engine.
- Direct-table grants remain until every named reader is cut to a redacted or
  typed effective contract. Revocation is a separate migration in E5.2, not a
  speculative change bundled with the first UI slice.

## Delivery steps

1. E5.1: add generic redacted read views for entity summary, source evidence,
   conflicts, relationships, candidates, and source-instance/type health.
2. E5.1: add Operations Admin entity list/detail and candidate queue/actions;
   extend Sources with row-based type counts and link the new surfaces from the
   existing Admin navigation and landing page.
3. E5.1: validate migration/view security, tenant filters, redaction, service
   reuse, pagination, templates, HTTP behavior, and aggregate production
   parity; release/deploy only after basic checks pass.
4. E5.2: add POST-only permission-checked reveal functions/routes, audit
   metadata-only access, move Device Identity & raw and other named readers,
   then revoke obsolete raw/effective direct-table grants with denial tests.
5. E5.3: inventory and cut APIs, CSV exports, evaluators, findings,
   notifications, and approved typed readers one at a time after aggregate
   parity. Preserve typed device/session/patch/software views where their
   semantics are class-specific.
6. Record any remaining compatibility columns/readers for E6 contract work;
   do not delete history, Agent Compliance, or legacy snapshots here.

## Validation

- Python compile, focused Ruff, Django check, migration drift, focused tests,
  template loading/request smoke checks, and `git diff --check`.
- SQL review for `security_barrier`, `current_tenant_id()`, explicit grants,
  role denial, registry-driven grouping, and no raw values in default views.
- Deployed aggregate row/count parity, tenant filtering, ACLs, route status,
  candidate action/no-op invariants, version/migrations, container health, and
  current HTTP-500/traceback/error counts.
- No local Docker rehearsal; the user requested basic proportional testing.

## Checkpoint and next action

E4 corrective `0.107.3` / `47bb68b` is deployed and mirrored with migration
0115 applied, exact ACLs, forced RLS, enabled triggers, no-op projectors, healthy
services, and zero current errors. Unrelated backlog, instruction, DESIGN, and
probe-file changes remain outside this plan and release staging.

E5.1 release `0.108.0` / `6433f44` is deployed and mirrored. It includes seven
security-barrier tenant read views owned by the
dedicated no-login/non-BYPASSRLS view role; generic entity list/detail and
candidate attach/reject pages; row-based source-instance/type counts; and
Admin navigation/landing integration. Default views exclude raw payloads and
protected source-event actor data. Compile, Django check, migration drift,
nine focused E4/E5 tests, template loading, and diff checks passed. Production
view counts and ACL/owner/tenant checks match the intended contract; six
authenticated read-only renders returned HTTP 200, all containers were
healthy, root/health returned 302/200, and current error counts were zero.

E5.2 release `0.109.0` is implemented locally. A new permission defaults
denied; reveal endpoints are POST-only and non-cacheable; database functions
verify active user, tenant, and direct/group/superuser permission, append a
metadata-only event to the existing audit log, and only then return the
requested current observation or attribute value. Device identity GET no
longer loads raw payloads. Client-candidate and device-merge reads use a safe
observation metadata view, permitting observation payload and E3 protected
table grants to be revoked while retaining the required update path. Django
check and migration drift pass; 11 focused E4/E5 contract tests and template
loading pass. The pre-existing four observation-model DJ008 warnings remain
outside this change.

E5.2 release `0.109.0` / `6d180bc` is deployed and mirrored. Migration 0117
and its artifact hash match; the permission defaults to zero assignments;
function/view ownership and exact ACLs pass. Device identity and generic entity
GETs returned 200 with no raw observation SELECT, reveal GET returned 405 with
no audit delta, and no reveal was invoked. All containers are healthy and
current error/500/privilege counts are zero.

E5.3 inventory found no data API beyond schema documentation and confirmed the
generic entity CSV is redacted. Typed presence/session/patch/software remain
approved device-domain contracts. Ninja collection, resolver attribute sync,
and evaluator role sync still independently write Device role/OS cache values;
older duplicate/CMDB findings also retain sensitive serial/URL details and must
be sanitized in this phase.

Aggregate parity across 5,272 current devices found exact selected-effective
matches of 4,708/4,708 role, 28/5,186 hostname (4,982 case/trim and 5,073
alphanumeric-equivalent), 4,682/4,706 OS name, 4,704/5,189 OS family, 4,410/
4,697 serial, 3,949/4,885 VM UUID, and 4,533/4,545 virtual flag. Typed blanks
account for 466 OS-family, 253 serial, and 913 VM-UUID mismatches, so generic
selection improves completeness but is not byte-for-byte cache parity.

**Decision gate closed 2026-08-05.** It rested on a conflation in the parity
table above: hostname, serial and VM UUID are write-once anchors set at
promotion, while role/OS/type are continuously refreshed caches. Comparing an
anchor captured months ago against a live selection will diverge by
construction, and that divergence is not a cutover signal.

Measured: zero `UPDATE ... SET canonical_*` statements exist repo-wide, and
`asset_field_history` holds zero `serial` and zero `vm_uuid` rows across 5,273
assets despite an enabled trigger watching both. Nothing clears identity today
and nothing planned would start, so "retain on withdrawal" needs no decision.

Restated E5.3 work:

1. One projector writes `os_name`, `os_family`, `os_group`, `device_role`,
   `device_type` from `entity_attribute_effective_current`.
2. Delete the four producer writes: `resolver.py:996`, `:1028`, `:1068`, and
   `evaluator.py:316`. Per ADR-0012 no evidence producer may write state.
3. Repoint facet propagation (`resolver.py:1078+`), which currently writes
   `assets` / `os_instances` **from** the cache columns, to read the effective
   contract. This writer is missing from the original three-writer inventory;
   removing the others without it silently freezes 5,273 assets and 5,255
   os_instances.
4. Sanitize findings embedding serial / CMDB-URL detail.
5. Enforce by revoking `UPDATE` on the five columns from the ingest role once
   the projector owns them.

Out of scope: `evaluator.py:718` writes `lifecycle_status` under ADR-0011's
audited lifecycle contract, not as a source-derived cache. Anchors are
untouched.
