# Active Operations implementation plan

## Software capability recognition — Operations integration

**Status:** implementation complete locally; release preparation in progress.
Raw SQL migrations 093–096 create capability evidence, seeded rules, policy
identity mapping, and the LOLRMM corpus. Operations migrations 0136–0138
provide approval suppression, the curator review type/permission, state-only
policy-map model, and unauthorized finding scope repair. The user authorized a
release commit, both remote pushes, coupled redeploy, and simple live checks.

**Goal:** expose and curate global product capability evidence without making
capability truth tenant-scoped; use stable product identities to determine
per-client policy sanctioning; allow only confirmed/vetted capability evidence
to create unauthorized findings.

**Scope:** Operations state-only catalog models and parity tests, product-map
storage/admin, capability review routes and audit events, the software readers;
ingest policy/evaluator wiring and LOLRMM connector; root SQL and Operations
migrations; focused tests and the root plan.

**Decisions:** capability remains global and is read through the catalog
readiness guard; the `core.curate_software_capability` permission is required
for global confirmation/rejection; `platform_product_map` connects an
`operations.agents` row to one or more `catalog.products` identities; unknown
and candidate evidence never create unauthorized findings. `multi_av_conflict`
remains disabled because package inventory cannot establish active protection.

**Validation:** focused Python/SQL contract tests, disposable PostgreSQL
behavioral tests, Operations request tests, migration checks, compilation,
Ruff, and `git diff --check`. Production behavior remains unverified pending
separate authorization.

**Checkpoint:** all planned code is wired. Enforcement and candidate review
remain explicitly off until production product UUID mappings and shadow-mode
results are reviewed; old unauthorized findings are preserved while off. This
does not restore name-containment exemptions. Release validation is limited by
user request to light local checks and simple deployed health, migration, and
endpoint checks.

**Local release checks:** changed Python modules compile and `git diff --check`
passes. Whole-file lint still reports unrelated, pre-existing findings in
`views.py` and `models.py`; the new import/migration-format checks are clean.

**Deployment correction:** `eaff70b` reached Operations migration 0137 but
hit pre-existing `finding_types` identity-sequence drift before the review
type could be inserted. The transaction rolled back. This release synchronizes
the sequence in 0137 before its idempotent upsert and redeploys as `0.116.1`.

## Products-page timeout repair

**Status:** implementation and release preparation in progress as `0.116.2`.

**Goal:** restore `/software/products/` without changing its counter's
meaning.

**Cause and decision:** production logs showed Gunicorn killing the request
after 30 seconds in the whitelist-suggestion distinct-title aggregate. The
existing direct partial expression index is valid, and the equivalent direct
type-ID query measured 57 ms. The ORM's category/type joins prevented that
fast path. Resolve the registry ID first, then count distinct canonical names
directly from active findings; the type is already a software type, so the
result is equivalent.

**Scope:** `apps/core/views.py`, Products/Publishers templates, root
version/changelog, this plan, and light post-deployment page validation. No
schema change.

**Next action:** compile and diff-check, then commit, push, redeploy, and make
authenticated Products and Publisher detail requests plus a health check.

**Next action:** release `0.116.0`, then record deployed migration and service
health evidence. Do not turn on either capability emission flag as part of the
release.

## Software decision scope parity

**Status:** implementation complete; included in the `0.116.2` release.

**Goal:** make Product and Publisher decisions equally capable of applying at
global, client, or device scope.

**Decision:** list pages retain compact global quick actions and link directly
to their detail page's scoped action. Each detail page offers one explicit
scope selector, bounded to clients/devices with current installations of that
title or publisher. The write path rejects a missing/invalid scope and a
client/device that does not currently run the selected title/publisher; it can
no longer silently turn malformed narrow requests into global decisions.

**Scope:** `apps/core/views.py` and the four Products/Publishers templates.
No schema change.

## Software detail legacy-evidence repair

**Status:** implementation and release preparation in progress as `0.116.3`.

**Goal:** keep the scoped Product decision controls reachable when historical
intel has a text-form `details` payload rather than the expected JSON object.

**Decision:** category tags are optional display enrichment. Only dictionary
payloads are read for tags; malformed legacy values are ignored without
changing valid evidence or classification behavior.

**Scope:** `apps/core/views.py`, root version/changelog, and this plan. No
schema change.

## E5.3 scoped maintenance — Issues filter-aware magnitude summary

**Status:** implementation and local validation complete; awaiting separate
approved commit/push/deploy as release `0.115.1`. This is a small restoration
on top of the deployed workflow-oriented Issues redesign; it does not alter
finding actions, software-decision ownership, or any EOL behavior.

**Goal:** restore a quick sense of the magnitude of the current Issues result
set after any filter is applied, including its fraction of the relevant
baseline.

**Scope:** `apps/core/views.py`, `templates/findings_queue.html`, focused
Issues tests, the root release authorities, and this plan. Extend the compact
summary row for matching findings, actionable findings, affected devices,
affected clients, and software policy candidates with a fraction and
percentage. Values must use the already filtered relations behind the page and
exports.

**Out of scope:** changing classifiers or finding state, adding a new filter,
schema/index migrations, category/taxonomy work, EOL changes, or deployment
until separately authorized.

**Decision:** the numerator always describes the active filters. Findings,
actionable findings, and policy candidates are compared with their active
status/snooze baseline before narrow filters; affected devices and clients are
compared with the current non-deleted fleet population. Every denominator is
labeled, so a filtered subset is never mistaken for a fleet-wide total.
Affected devices and clients come from the existing action-finding device
impact relation; software policy candidates remain a title-level count and are
shown separately rather than pretending to be device incidents.

**Validation:** focused test, Django checks, migration drift, Python compile,
template loading, and `git diff --check`. No migration is expected.

**Checkpoint:** the workflow redesign retained a terse actionable/device title
count but removed the prior high-level cards, making filtered magnitude harder
to scan. The page now exposes a Current result scope card row for matching
findings, actionable findings, affected devices, affected clients, and policy
review candidates. It reuses the existing action-finding device-impact list,
so no extra per-filter source relation is introduced. Each card now displays
the filtered value plus a labeled numerator/denominator and percentage:
findings/actionable/policy use the matching status/snooze scope before narrow
filters, while devices/clients use the current non-deleted fleet population.

**Validation completed:** focused Issues tests (6 passed) and the full
Operations suite (56 passed, 2 expected Postgres-integration skips); Django
checks, migration drift, Python compile, template loading, and `git diff
--check` passed. The test runner reported only existing Django deprecation
warnings.

**Next action:** commit release `0.115.1`, push `origin` then the required
mirror, immediately redeploy through Portainer, and verify the rendered Issues
request. No migration is included or expected.

## E5.3 scoped maintenance — Issues workflow-oriented redesign

**Status:** implementation and local validation complete; commit/push/deploy
authorized 2026-08-11. This replaces neither the deployed findings reader nor
the existing Software Decisions workflow; it makes their different
responsibilities explicit in the Issues UI.

**Goal:** make Issues meaningful by separating actionable findings from
title-level software policy candidates, showing useful evidence for each, and
offering only actions that change the owning workflow.

**Scope:** `apps/core/views.py`, `templates/findings_queue.html`, shared
finding-detail formatting, the existing Software Decisions reader/template as
needed for a precise review link, focused tests, and this plan. Retain one
filtered finding relation for exports and counts. Render actionable findings in
the current incident queue; render `whitelist_suggestion` as a software-policy
candidate with spread/reason and a link to the existing decisions workflow.
Refuse generic finding-state actions for that recommendation type in both
single-row and bulk endpoints.

**Out of scope:** changing the finding classifier, software-decision data or
scope precedence, EOL evaluators, schema migrations, generic query-builder
work, unrelated category/taxonomy changes, deletion/rebuilds, and deployment
until the user-authorized commit/push boundary.

**Decision:** a `whitelist_suggestion` is an undecided widespread software
title, not a device incident. Its authoritative actions are existing
SoftwareDecision writes: global, client, or device, with device taking
precedence over client and client over global. The Issues page will not
duplicate those writes; it links into their review context. It stays in the
filtered total/CSV as an auditable finding but no longer receives Ack, Resolve,
Snooze, or Suppress.

**Validation:** focused route/template/action tests, full Operations test
suite, Django checks, migration drift, compile, scoped lint/format where
possible, `git diff --check`, and an approved deployed smoke request after
push. No migration is expected.

**Checkpoint:** Issues now calculates one filtered relation, partitions it
into actionable findings and `whitelist_suggestion` policy candidates, and
keeps the complete relation for the Issues CSV. The generic table uses Subject,
Evidence, and Context instead of mostly blank device-only columns. A separate
candidate table exposes product, publisher, installation spread, reason, and a
link to the existing Software Decisions workflow. Its current state endpoints
and bulk actions fail closed for recommendation rows. Detail formatting now
renders recommendation spread/threshold and fuller vulnerability evidence.

**Validation completed:** focused Issues tests (5 passed); full Operations
suite (55 passed, 2 expected Postgres-integration skips); Django checks,
migration drift, Python compile, template loading, and `git diff --check`.
Scoped Ruff passes for the changed test; whole-file Views and detail-tag lint/
format remain unsuitable because of known pre-existing complexity findings.

**Next action:** review/stage only this scoped redesign, commit, push `origin`
then the mirror, immediately redeploy through Portainer, and verify the
deployed filtered Issues request plus action guardrails. No migration is
included or expected.

## E5.3 scoped maintenance — Patch Evidence Windows 11 readiness filter

**Status:** filter deployed in `95c3537` on 2026-08-11; documentation update
is ready for separate commit approval. This is a narrow Patch Evidence reader
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

**Deployment validation:** `95c3537` was pushed to `origin` and the required
mirror, then deployed through Portainer at the matching configuration hash.
Operations and ingest became healthy, Operations `/healthz` returned 200, and
the tenant-scoped `?win11=capable` Evidence reader returned 200. The current
ingest migration stayed at 088; no migration ran.

**Next action:** obtain separate approval to commit the documentation update.

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
index to show a clearly labeled recent slice before joining device data.

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
describe the clearly labeled recent sample; with filters they describe the
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
