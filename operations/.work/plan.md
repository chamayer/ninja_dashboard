# Active Operations implementation plan

## ACTIVE TASK — Group merge review for multi-member candidates

**Status:** implementation in progress.

**Goal:** provide a review and one-confirmation merge action for merge
candidates containing more than two current Computers.

**Scope:** Operations merge-candidate queue, group merge view, and existing
device merge helper. No schema, resolver, or automatic-merge behavior change.

**Decision:** validate every snapshotted active member belongs to the same
client, retain the oldest member as the technical anchor, move each other
member into it transactionally, and mark the candidate merged. Existing
pairwise merge behavior remains unchanged.

**Validation plan:** Django check, changed-template loading/compilation, and
`git diff --check`.

**Validation completed:** `python operations/manage.py check`, Python
compilation, and `git diff --check` pass.

**Checkpoint:** the queue now links multi-member candidates to a group review
page. The generic Computer identity section is also being wired to the same
review action when the current Computer belongs to an open candidate.

**Next action:** obtain commit approval if this should be released.

## ACTIVE TASK — Clear Hudu archive candidates in Findings

**Status:** complete — awaiting commit approval.

**Goal:** make each Hudu archive candidate understandable and actionable from
the Findings list: show the Hudu record instead of treating its organization as
the subject, link safely to an exact same-client Operations Computer when one
exists, and replace the hidden per-row management menu with direct actions.

**Scope:** Findings list presentation and client-side action affordances only.
No schema, evaluator, candidate-rule, permission, or source-action queue
change. A Hudu record remains source evidence, not a canonical Computer; an
exact name-and-client Computer link is explicitly presented as a possible
related Computer rather than an identity claim.

**Affected files:** Findings view, Findings template, focused Findings tests,
and this plan.

**Decision:** `cmdb_asset_stale` has no canonical Computer subject because its
linked source records are no longer resolvable. Its row therefore names and
links the exact Hudu record, retains the organization in context, and, only
when exactly one same-client hostname matches, provides a clearly qualified
Operations Computer link. Archive in Hudu is a direct per-row action with a
required reason and confirmation; it uses the existing guarded queue endpoint.

**Validation plan:** focused Findings tests, Django check/template load, and
diff check. No production mutation.

**Validation completed:** Python compilation; focused Findings tests (13
passed); Django system check; and `git diff --check`. A full Ruff pass still
reports pre-existing issues in the large Findings view and label module; this
change introduced no new F/E diagnostic. Ruff format check also reports
pre-existing formatting drift, so no broad mechanical rewrite was made.

**Checkpoint:** completed locally. Hudu candidates now display as `Hudu
archive candidate` in the Type selector, link to the exact Hudu record, and
show an exact-name/client Operations Computer link only when unique. The
per-row `Manage` disclosure is replaced by visible actions, including Archive
in Hudu for authorized users; bulk checkboxes and selected-item actions remain.
No production mutation or deployment has occurred.

**Follow-up:** the subject link now uses the persisted Hudu-to-Computer source
link when present; the Hudu URL remains a separate evidence link. Merge
candidates expose their existing two-member merge operation in a dedicated
Action column. Validated locally; no manual Portainer redeploy requested.


## ACTIVE TASK — Findings actions: bulk Computer retirement

**Status:** complete.

**Goal:** let an authorized operator retire multiple eligible Computers from
the Findings workflow, and establish the reusable action boundary for future
Operations and source API actions.

**Scope:** add a registered bulk action for the existing “No current source
record reports this Computer” finding. It must require a shared reason, select
only active Computers in `pending_cleanup`, retain evidence/history, retire the
canonical Computer and entity atomically, resolve the selected finding, and
write one audit event per Computer. Add a dedicated lifecycle permission and a
Findings UI control. Do not call source APIs in this slice.

**Affected files:** finding action registry/handler, lifecycle access policy,
Findings template and focused tests, User permissions migration, release
metadata, and this plan. No source-data rewrite.

**Decision:** a Finding remains a derived fact. An action is an explicit,
registered operator operation with a permitted finding type, required
permission, validation, and audited handler. `manage_lifecycle` is independent
of catalog administration; the migration grants it to existing catalog
managers for continuity. Future source API actions use this same registration
boundary but require their own source capability and confirmation design.

**Validation plan:** focused finding-action and lifecycle-permission tests,
Django check, migration review, and diff check.

**Checkpoint:** individual retirement exists only from an eligible Computer’s
detail page, guarded by `manage_catalog`; Findings bulk actions currently alter
only finding state and have no authorization check.

**Expanded scope:** register **Archive in Hudu** as the first external source
action. The existing source-agnostic ``cmdb_asset_stale`` evaluator condition
is the candidate rule: a current Hudu record has at least one integrated,
linked external record and none still resolve. It excludes unlinked records,
archived Hudu records, and any asset for which a linked record remains current
(including offline or stale). The web application queues exact current Hudu
asset targets; ingest alone resolves the Hudu secret reference, calls the API,
and records a per-target outcome. It is never an automatic archive or side
effect of Operations retirement.

**Checkpoint:** implemented the generic registered Findings-action registry;
the initial lifecycle action; a generic, auditable `source_action_requests`
queue; and the initial `Archive in Hudu` action. `cmdb_asset_stale` is now one
finding per eligible current Hudu record, not a client aggregate. The web
action rechecks the exact Hudu observation then queues it; the ingest worker
rechecks again, resolves the Hudu credential, calls the archive endpoint, and
refreshes Hudu evidence so source data resolves the finding. It uses the raw
Hudu company ID because legacy normalized child observations intentionally do
not populate `parent_external_id`.

**Validation completed:** Python compilation, Django migration-state check,
Django system check, focused Findings/lifecycle tests (16 passed), diff check,
and a read-only/live Hudu API inspection. An explicitly approved archive of
the disposable Hudu `Test-Asset` returned HTTP 200 and a direct read-back
reported `archived: true`, confirming the configured key supports the action.
Ruff exposed and the implementation corrected one undefined stale-detail cap;
the remaining `views.py` lint findings pre-exist this change.

**Release:** version 0.122.59, commit `17a6887` (Add auditable Hudu archive
actions), pushed to `origin` and `a-m-rose` on 2026-09-11. Portainer deployed
the commit; Operations migrations 0159 and 0160 applied successfully, and
both Operations and ingest health endpoints are healthy. A post-deployment
Hudu findings evaluation emitted 198 individual archive candidates.

**Next action:** none. Source actions are operator-confirmed; do not archive a
candidate without a separate operator request.

**Scope:** make a VMware guest with an exact VMX path use a stable, source-
scoped observation identity: Ninja organization plus normalized VMX path.
Retain changing Ninja node IDs and node UUIDs as raw evidence, never as a VM
UUID. Route current parent-host data through the existing source evidence
contract and retain a path-only guest as a valid Computer with unavailable
guest details. Existing duplicate Computers are not silently merged; exact-path
clusters become reviewable candidates after the evidence identity correction.

**Affected files:** Ninja collection/observation identity, historical-evidence
normalization, the guarded Operations reconciliation command, focused tests,
and this plan. No schema migration, UI redesign, or broad inventory-model
replacement.

**Decision:** `ninja_core.devices` remains the raw per-Ninja-node record store.
`entity_observation_current/history` and `entity_source_links` carry a stable
source record identity. For a VMware guest that reports a VMX path, that key is
the Ninja organization and normalized VMX path; for one without a path, the
existing Ninja node identity remains the safe fallback. `operations.devices`
remains the single Computer anchor. A shared MAC may connect a VMware guest and
an OS agent to that Computer; a VMX path never becomes `canonical_vm_uuid`.
A storage-path change is a review candidate absent an independent strong
signal. Existing raw records and observation history are retained.

**Validation plan:** focused identity/observation tests for guest-path
continuity, path absence, shared-MAC attachment, and raw-ID retention; Python
compilation; Django check; migration dependency/reversibility review; and
`git diff --check`. No custom diagnostic scripts. Production reconciliation,
commit, push, and deployment require their own approval.

**Checkpoint:** live investigation found 144 current Ninja VMware guests; 27
have no MAC, IP, or guest OS but all 27 have a VMX path. `82livigent01` is a
black-box appliance with VMware Tools unavailable and only a VMX path.
`82fileserv3` has a stable VMX path and shared MAC with its Ninja OS-agent
record. Current code writes Ninja `uid` into `canonical_data.vm_uuid` and keys
all Ninja observations by changing numeric node ID; both behaviors conflict
with this decision. Unrelated `.work/` artifacts remain unstaged.

**Checkpoint:** implementation is complete. VMware guests with a valid VMX
path now use external namespace `vmware_guest_vmx_path`, parent identity
`organization:<Ninja organization ID>`, and a normalized VMX path external ID.
The numeric Ninja node ID and its `uid` are retained as `ninja_node_id` and
`ninja_node_uid` source evidence; neither is written as `vm_uuid`. The first
corrected collection attaches the stable path observation to the existing link
for its currently reported Ninja node, then the existing snapshot reconciler
withdraws obsolete per-node observations. Future host moves resolve by the
stable path identity. Historical-restoration code no longer reintroduces the
bad VM UUID assertion.

The packaged `reconcile_ninja_vmware_guest_duplicates` management command
measures and combines only same-Ninja-organization, exact-normalized-VMX-path
groups. It defaults to read-only, requires an expected group count and SHA-256
digest for apply, locks the target set, and uses the existing Computer combine
operation. Derived source links converge through the normal ingest projection,
as they do after an operator-initiated combine. A live read-only measure found 53
eligible groups, 475 affected Computers, and 853 retained Ninja guest records;
the exact digest must be generated again from the deployed command immediately
before apply. It does not merge changed paths, name-only matches, or groups
crossing clients.

**Validation completed:** Ruff on every changed Python module, Python
compilation of all changed modules, `python manage.py check` (passed), command
discovery/help (passed), and `git diff --check` (passed). The focused ingest
test file was skipped because the workstation lacks the ingest image's optional HTTP dependency. The repository
hardcoded-domain-mapping ratchet failed on four pre-existing, unrelated
constants (`_COVERAGE_STATES`, `_MATCHERS`, `_SIGNALS`, and
`_TAG_OWNED_SOURCES`); this change introduced none. The selected Operations
integration test module contains no discoverable tests in this checkout.

**Checkpoint:** version 0.122.55 was deployed as `b0ff76e`. The fresh
production dry run found 53 exact-path groups containing 476 Computers with
digest `26010b8b06241781a33bcd2c1806ea5475dde2837cd6d8fed295bb84120cb113`.
The pinned apply transaction rolled back completely when its eager derived
source-link projection encountered a pre-existing history-window constraint
for unrelated legacy Ninja compatibility evidence. No Computers were combined.
The command now follows the existing UI combine boundary: it atomically moves
source evidence and tombstones duplicates, while the normal ingest projection
converges source links later.

**Release and validation:** version 0.122.55 (`b0ff76e`) and safeguard version
0.122.56 (`f7aaef3`) were pushed to `origin` and `a-m-rose` on 2026-09-10;
Portainer deployed `f7aaef3` with no migration. The guarded post-deployment
dry run measured 53 groups, 476 Computers, digest
`26010b8b06241781a33bcd2c1806ea5475dde2837cd6d8fed295bb84120cb113`; the
pinned apply combined 423 duplicate anchors. The final dry run reports zero
eligible groups. Operations and ingest health endpoints both report healthy.

**Release:** version 0.122.45, commit `5bf5d07` (Reorganize Computer details
and patching), pushed to `origin` and `a-m-rose` on 2026-09-10. Portainer
deployed the matching commit; no migration was included. Operations and ingest
are healthy, and the Operations health endpoint returned `ok`.

**Validation completed:** Django check, Python compilation, configured
template loading, focused existing device-detail/lifecycle tests (5 passed),
`git diff --check`, and deployed service-health checks. The test environment
emitted only pre-existing Python 3.14/Django async deprecation warnings.

**Hotfix checkpoint:** deployed Details exposed a missing `section` key while
building the section list for rendered claims. The section was calculated but
not copied into the final field object. The correction restores that key only;
no query, data, schema, or layout behavior changes. Validate the failing
Details route after release.

**Previous release checkpoint:** Details now organizes every normalized displayed
claim into Identity and inventory, Operating system, Hardware and
virtualization, Network, Security and management, or Other reported
information. Each value lists its reporting source and record type, and real
conflicts retain both reported values. Source records now contains the former
Observations table, Hudu related-record context, exact evidence links, and the
existing lifecycle review/retire/restore actions. Old Observations bookmarks
redirect directly to that section. Overview has an attention-only lifecycle
banner and no longer makes dead-end links to Details; tabs are Overview,
Details, Patching, Activity, Software. The new Patching tab shows existing
policy/override, restart and install information, and current Ninja patch
evidence.

## Previous release — Restore Computer Overview software access

**Goal:** restore Computer Overview rendering after the source-aware software
release while preserving the secure view boundary.

**Scope:** add one SQL migration that grants the dedicated
`operations_view_owner` read access to the specific base tables used by the
two source-aware software views. The application role continues to read only
the views. No data rewrite, source-state change, privilege expansion for the
application, or UI change.

**Affected files:** `../../sql/migrations/108_software_evidence_view_owner_grants.sql`
and this plan.

**Decision:** security-barrier views execute with their owner’s privileges,
not the caller’s. The view owner therefore needs SELECT on their explicit
dependencies; granting that owner is the least-privileged fix, rather than
granting `operations_app` direct table access.

**Validation plan:** SQL dependency/grant review, migration-order review,
configured Django check, and `git diff --check`. Validate the failed Overview
route after an explicitly approved deployment.

**Release:** version 0.122.44, commit `daad050` (Restore software evidence
view access), pushed to `origin` and `a-m-rose` on 2026-09-09. Portainer
deployed the matching commit and applied
`108_software_evidence_view_owner_grants`. Both Operations and ingest became
healthy. The failed exposure query now succeeds as `operations_app` with
tenant context; the unauthenticated host route correctly redirects to sign-in.

**Validation completed:** `manage.py check`, `git diff --check`, SQL
dependency/grant and migration-order review, a rolled-back live privilege
trial, deployed migration-record verification, runtime-role query verification,
and both service health checks passed.

**Final checkpoint:** migration 108 now grants only the dedicated view owner
the complete direct dependency set plus `USAGE` on `catalog`; the application
role remains view-only. A live transaction applied those grants temporarily,
ran the failing source-aware exposure query as `operations_app` with tenant
context, returned successfully, and rolled back.

**Initial diagnosis:** live Operations logs identify the failure as
`permission denied for table software_installations_current` from
`v_device_software_exposure`. Live privilege checks confirm
`operations_view_owner` lacks SELECT on the two views’ direct software,
source-binding, evaluator-configuration, and catalog dependencies. The
runtime application role retains SELECT on the views and has no direct table
grant.

## Previous release — Finish Computer details and source-aware findings

**Goal:** finish the Computer detail experience and source-state handling as a
single release: keep Overview compact and actionable, make Details show all
normalized source fields under the existing Admin field-visibility policy, and
ensure patch findings are active only for online Computers.

**Scope:** `templates/device_detail.html` retains clickable cards, the
per-Computer Include/Exclude patch override, and colored observation status;
`views.py` removes the Details whitelist while preserving configured
visibility and adds source evidence state to the Computer software inventory;
`patch_findings.py` limits patch findings to online Ninja-backed Computers;
the reviewed SQL migration derives source-specific software evidence state and
filters active software exposure; `entrypoint.sh` uses bounded threaded
Gunicorn workers. No raw-payload exposure, data rewrite, or new test script.

**Affected files:** `entrypoint.sh`, `templates/device_detail.html`,
`apps/core/views.py`, `../../ingest/patch_findings.py`,
`../../sql/migrations/107_software_installation_evidence_state.sql`, root
`VERSION`, `CHANGELOG.md`, and this plan.

**Decision:** Details renders every normalized, display-safe attribute claim;
Admin → Configuration → Fields remains the authority for which values are
visible. Overview remains a concise operational summary. Patch findings require
an online current Ninja observation. Software installation history is the
source-specific evidence store; a security-barrier view derives current,
offline, stale, or withdrawn state from it and the shared source lifecycle
contract. Software exposure requires current or offline evidence.

**Validation plan:** Python compilation, Django check, configured template
loading, focused existing device-detail/lifecycle and findings tests, SQL
migration review, and `git diff --check`. No custom diagnostic script.

**Current checkpoint:** deployment exposed a migration error before any schema
change: `evaluator_config.id` has no database default, so the migration must
not create the optional administrator configuration row. The corrected
migration relies on the code default and the existing Classifier configuration
screen, which creates that row with the Django UUID default when an operator
saves it. The software evidence view uses the
existing per-source SCD-2 installation evidence rather than adding a second
source field to the combined current row. It preserves software inventory and
history while limiting active exposure to current or offline supporting
evidence. Pre-existing user work under `.work/` is excluded from staging.

**Validation completed:** Python compilation of changed modules; `python
manage.py check`; configured loading of `device_detail.html`; focused existing
device-detail, lifecycle, and findings tests (15 passed); `docker compose
config --quiet`; SQL migration/read-model review; and `git diff --check`.
The test environment emitted pre-existing Python 3.14/Django async deprecation
warnings only. Compose reported its existing obsolete top-level `version`
warning. The Windows development host has no POSIX `sh`, so entrypoint shell
syntax was not separately checked.

**Release:** version 0.122.43, commits `32708ac` (source-aware behavior) and
`b5132cd` (migration startup correction), pushed to `origin` and `a-m-rose`
on 2026-09-09. Portainer deployed `b5132cd`; SQL migration
`107_software_installation_evidence_state` applied successfully, and both
Operations and ingest health endpoints returned healthy. A separate startup
Ninja device-collector refresh logged an invalid blank bigint in the legacy
active-device materialized-view refresh; it did not affect this migration or
service health and is outside this release scope.

**Validation completed:** `python manage.py check`; Django-configured loading
of `device_detail.html`; focused existing device-detail/lifecycle tests (5
passed); and `git diff --check`. The test environment emitted pre-existing
Python 3.14/Django async deprecation warnings only.

**Release:** version 0.122.42, commit `01732f4` (Refine Computer overview
posture), pushed to `origin` and `a-m-rose` on 2026-09-09. No migration was
included. Portainer deployed commit `01732f4` successfully and the Operations
health endpoint returned `ok`.

**Validation plan:** Django check, configured template loading, focused
existing device-detail/lifecycle tests, and `git diff --check`. No migration,
new test script, production query, or deployment.

**Validation completed:** `python manage.py check`; Django-configured loading
of `device_detail.html`; focused existing device-detail/lifecycle tests (5
passed); and `git diff --check`. The test environment emitted pre-existing
Python 3.14/Django async deprecation warnings only.

**Release:** version 0.122.41, commit `3e52d28` (Improve Computer review
workflow), pushed to `origin` and `a-m-rose` on 2026-09-09. No migration was
included. Portainer deployed commit `3e52d28` successfully and the Operations
health endpoint returned `ok`.

**Release:** version 0.122.40, commit `a057b3f` (Compact Computer agent
requirements), pushed to `origin` and `a-m-rose` on 2026-09-09. No migration
was included. Portainer deployed commit `a057b3f` successfully and the
Operations health endpoint returned `ok`.

**Latest scope:** finish the Computer Overview as an operator surface. Remove
identity/cache noise from the header; consolidate evidence review and the
existing lifecycle action; and present coverage requirements and exemptions as
separate policy rows. No change to source evidence, coverage evaluation,
exemption storage, or lifecycle action permissions.

**Decision:** the header contains only the Computer identity plus role/OS.
Availability, lifecycle review, issues, hardware facts, and coverage policy
remain separate. A Needs review Computer shows its source-record summary and
the existing reason-required retirement control together. Coverage exemptions
are displayed by required platform/entity type, with their existing add/remove
actions retained.

**Validation:** Django check, configured template loading, focused existing
device-detail/lifecycle tests, Python compilation, and diff check. No new test
scripts or production writes.

**Current checkpoint:** the Overview header now shows only role and OS below
the Computer name; availability and issue totals remain their own cards, while
serial and type remain Basic computer fields. The Review & lifecycle card
shows the source-record summary, routes to full observations/evidence, and
retains the existing reason-required retirement action. Coverage policy lists
effective requirements with exemption reason/removal controls and retains any
exemption whose requirement is no longer active so policy data is not hidden.

**Validation completed:** Python compilation, Django check, configured
device-detail template loading, focused existing device-detail and lifecycle
tests (5 passed), and `git diff --check` passed. The effective-policy query
will be exercised against PostgreSQL after an approved deployment.

**Next action:** obtain explicit approval for release commit/push and the
resulting Portainer deployment; no migration is included.

**Goal:** let an Operations administrator move directly from an observation on
a Computer to that exact source-evidence record without exposing raw payloads;
and make each Computer inventory platform cell use the same compact source
state rather than a separate Present/Absent interpretation.

**Scope:** the Computer Observations tab, the existing redacted Entity evidence
reader, the Computer inventory reader/template/CSV, and source-withdrawal
lifecycle/finding evaluation. This follow-up clarifies the one-line
platform-cell precedence and tooltips only. Migration 0156 seeds a
source-record withdrawal finding and corrects the existing Computer-level
removal finding. No resolver, source connector, external API action, or
automatic retirement change.

**Decision:** the Computer page retains its concise source-observation table.
An adjacent **Evidence** link opens the existing administrator-only, redacted
evidence page scoped to the selected observation. Raw payload access remains
the separate audited reveal action. Inventory summarizes the same observation
state by platform: Online has no age; Offline/Stale shows its evidence age;
Withdrawn shows its removal age; and No record remains distinct. Requirement
evaluation and filters stay intact, so source state is not mistaken for a
coverage requirement. A source-record withdrawal is a source-specific finding;
only no current source observations across the Computer moves it to Needs
review and opens the existing Computer-level removal finding. The review link
opens the Observations tab, where the existing reason-required retirement
control is available.

**Follow-up decision:** a real source state is never overwritten by requirement
policy. Current records show Online, Offline, Stale, or Current; withdrawn
records show Withdrawn. Only absent source evidence becomes Missing when the
platform is required or N/A when it is not. Tooltips state the exact meaning.

**Validation:** template loading, Django check, focused existing generic-admin
and device-detail tests where applicable, Python compilation, and diff check.
No new test scripts and no production queries or writes.

**Checkpoint:** the Observations tab now carries each observation UUID in its
safe read-model query. Administrators see an adjacent Evidence link that opens
the existing redacted Entity evidence screen filtered to that source record;
non-administrators do not receive a link to an administrator-only route.
The inventory reader now summarizes current/withdrawn evidence and exposes a
Needs review link for Computers with no current sources. The evaluator and
migration are implemented; validation remains. Migration 0156 is included.

**Validation completed so far:** Python compilation, Django check,
migration-drift check, Django-configured template loading, the existing focused
generic-admin and device-detail/finding tests (15 passed), and `git diff
--check` passed for the evidence-link portion. The first standalone
template-loader invocation was invalid because it did not configure Django
settings; the same load passed through `manage.py shell`.

**Validation completed:** Python compilation; Django check; migration-drift
check; UTF-8 migration-plan review showing 0156; Django-configured loading of
the four changed templates; focused inventory, generic-admin, finding, and
lifecycle unit suites (35 passed); and `git diff --check` pass. SQLite warns
that two pre-existing `NULLS DISTINCT` constraints cannot be represented; no
database migration was applied locally.

**Next action:** obtain separate approval to prepare the release, commit, and
push the platform-cell clarification. No new migration is included; migration
0156 was released in 0.122.35. Do not manually redeploy.

**Follow-up validation completed:** Python compilation, Django check,
configured coverage-template loading, focused Computers inventory tests (8
passed), and `git diff --check` pass.

**Latest checkpoint:** the Platforms dropdown behavior is unchanged; No
platform records now appears in its own bottom Other section. Validation next.

**Latest scope:** complete the universal source-record lifecycle follow-up.
Migration 0158 adds an editable source-record lifecycle mapping registry and
the safe lifecycle read model. Hudu archived records are its first seeded
mapping: they remain current source records and visible history, but do not
qualify as current Computer evidence. The evaluator, review finding, Hudu
archive reader, Observations tab, and Findings evidence date consume the
shared contract. No new operator action or generic lifecycle filter is added.

**Current checkpoint:** the Observations Hudu-record section now runs on the
Observations tab. Its source table separates Record state from Source status.
The existing Hudu archive filters derive their archive fact through the shared
lifecycle mapping. The lifecycle evaluator moves a Computer to Needs review
and maintains the no-current-sources finding only when no record qualifies as
current Computer evidence; archived records no longer suppress review. The
finding queue displays a source evidence/withdrawal date when the finding has
one, instead of showing evaluator refresh time as device activity.

**Decision record:** ADR-0011 now records the source-record lifecycle
qualification contract, including the default treatment of unmapped records
and the prohibition on source-specific evaluator exceptions.

**Validation completed:** Python compilation of all changed Python and
migration files; Django check; migration-drift check; Django-configured
loading of the changed templates; focused existing findings, Computer
inventory, detail-helper, and lifecycle-policy tests (23 passed); SQL review
of migration 0158; and `git diff --check` all pass. The local SQLite migration
preview renders PostgreSQL-only policy/view SQL without executing it; no
production migration or data change was run.

**Next action:** obtain explicit approval to prepare a release, including the
pending 0157 and 0158 migrations, then commit and push. Do not manually
redeploy.

**Release correction:** the first production evaluator invocation after
0.122.37 exposed one stale SQL alias in the no-current-sources query. The
single query correction is prepared as 0.122.38. The failed evaluator
transaction rolled back; migrations 0157 and 0158 remain successfully applied.

**Release validation:** 0.122.37 (`6674d57`) and its evaluator correction
0.122.38 (`11de195`) were pushed to `origin` and `a-m-rose`. Portainer's Git
deployment applied Django migrations 0157 and 0158 and restarted healthy
Operations and ingest services. The manual platform-evaluator run completed at
2026-09-09 16:11 UTC with 10,061 findings affected. Ninja coverage evaluation
was skipped because its collection was in progress; lifecycle qualification
still ran. The initial failed evaluator transaction made no partial change.

**Next action:** no remaining implementation work. Do not commit this
post-release plan checkpoint alone.

## Source-record lifecycle follow-up checklist

- [x] Add an Evidence link beside each source observation, opening the exact
  redacted source record. Released in 0.122.35.
- [x] Show source-observation state in Computers inventory and surface a
  Computer-level Needs review state when every current source record is gone.
  Released in 0.122.35.
- [x] Keep platform cells compact and use source state before requirement
  policy. Released in 0.122.36.
- [x] Keep current Platforms filter behavior unchanged and move No platform
  records into a bottom Other section. Implemented locally; not released.
- [x] Rename the Computer-level finding to No sources currently report this
  Computer. Implemented locally with migration 0157; not released.
- [x] Correct the Observations Hudu reader so its Hudu-record section runs on
  the Observations tab and shows the linked archived record.
- [x] Change the Observations table labels to Record state and Source status;
  a Hudu row must read Current / Archived without repeating the source name.
- [x] Add a universal source-record lifecycle contract, distinct from source
  record presence: Active, Archived, Retired/decommissioned, or Unknown.
- [x] Derive whether each source record counts as current Computer evidence
  from that contract through administrator-managed mappings, rather than
  source-specific evaluator code.
- [x] Move lifecycle review and the Computer-level no-current-sources finding
  to the derived qualification. Archived/retired records remain visible and
  linked but do not keep a Computer out of Needs review.
- [x] Display a finding's relevant evidence date, such as Last source
  evidence, rather than presenting evaluator refresh time as device activity.
- [x] Align Hudu's existing archive filters with the universal record-lifecycle
  contract; do not add a generic lifecycle filter until other sources expose a
  useful operator-facing lifecycle state.
- [x] Record the broader finding-action boundary separately: only explicit,
  permission-checked, confirmed, audited actions per finding type; no generic
  arbitrary source-API action. No new source API action is implemented here.

## ACTIVE TASK — Clarify Computers inventory summaries, coverage filtering, and Findings links

**Status:** implementation and local validation complete; approved release
preparation in progress for 0.122.29.

**Goal:** make a device-subject finding open the live Computer detail URL even
when the finding retains an earlier client reference; remove internal
implementation comments from the device issue table; and make the Computers
page distinguish stable all-inventory source counts from filtered inventory
results with source-specific status selection; and make the Computers
population include every current computer-capable platform record rather than
hiding records that have not resolved to a Computer.

**Scope:** Findings queue read-model context, the Computer-detail template,
and the Computers inventory view/template. No finding data rewrite,
source/evaluator change, migration, or changes to finding semantics.

**Decision:** a finding retains its recorded client as historical context, but
its device-detail link must use the current live Computer's client slug. If
that Computer is no longer live, show no link rather than constructing a stale
route. Operator-facing templates contain no internal implementation comments.
Computers source cards are an unfiltered, one-Computer-per-source view using
the worst applicable coverage status. The filtered summary is separate and
shows inventory scope plus Hudu presence. Source-specific coverage conditions
are selected together so different sources can have different statuses.
The inventory population is the union of active Operations Computers and all
current computer-capable source records. A source record is grouped only when
it already has a live resolved Computer; otherwise it remains a visible
source-only row. Requirement evaluation remains unchanged, so Missing retains
its existing meaning and unrequired platforms remain Not applicable.

**Affected areas:** Findings queue view, Computer-detail template, Computers
inventory view/template and tests, and this plan. No migration is expected.

**Validation:** Django check/migration drift, Python compilation, template
loading, relevant existing findings and inventory tests, and diff check. No
new test scripts and no production writes.

**Checkpoint:** device-subject finding links now use the live Computer's
client slug and name, while retaining the finding client only as fallback
historical context. Removed internal comments from the Computer issue table.
No finding rows or source data were changed. Computers now shows an unfiltered
source summary that counts each Computer once per source using its worst
applicable status; its filtered summary shows clients, Computers, In Hudu, and
Not in Hudu. The Coverage menu has one row per source with source-specific
status selection; selected source rows are combined with AND semantics.

**Validation completed:** existing Findings/device-detail tests passed (12);
the focused Computers coverage suite passed (8); Django check, migration
drift, Python compilation, changed-template loading, and `git diff --check`
pass. No migration is included. Release 0.122.27 was committed and pushed as
`f1744be`; Portainer rejected direct redeploy requests, and the operator then
directed that no further redeploy requests be made.

**Next action:** inspect current platform record types and implement the
complete source-record inventory population; run focused local validation. No
migration 0155 is included. Commit and push the approved release; do not
manually request a Portainer redeploy.

## ACTIVE TASK — Retire Computers and keep historical rebuilds out of normal search

**Status:** committed and pushed as 0.122.26 / `bb6c304`; deployment not
manually triggered at operator direction.

**Goal:** give operators a reversible, audited way to retire a Computer and
make normal search present current Computers rather than every retired rebuild
with a reused name.

**Scope:** Computer-detail lifecycle action, audit/anchor synchronization,
normal search filtering with an explicit include-retired option, and compact
same-client/name history context on the Computer detail. No automatic
retirement, source-observation rewrite, merge, or production bulk change.

**Decision:** retirement is an operator-owned lifecycle decision, not a source
assertion and not a soft delete. Retiring sets the Computer lifecycle to
`retired`, marks its generic anchor retired with the same reason/time, writes
an audit event, retains all source evidence, and removes it from normal
inventory/coverage/search. Restore is the inverse, also reasoned and audited.
Only an administrator may make either decision. Name reuse supplies history
context only; it never retires or merges another Computer automatically.

**Affected areas:** detail/search and current-Devices views and templates, URL
routing, existing entity/device lifecycle stores, lifecycle decision record,
and this plan. No migration is expected.

**Validation:** Django check/migration drift, Python compilation, focused
existing tests and template loading, scoped lint/format where applicable, and
diff check. No new test scripts and no production writes.

**Checkpoint:** detail pages now offer an admin-only retire/restore action with
a required reason. It updates the Computer and generic anchor atomically and
writes a `device.lifecycle.*` audit event. Normal search and the current
Devices page exclude retired Computers; search can explicitly include them.
The Overview tab shows other same-client/name Computers as separate records
for operator context. No records were retired automatically.

**Validation completed:** focused existing lifecycle/detail/findings tests
passed (15); Django check, migration drift, Python compilation, and the three
changed templates loading all pass; `git diff --check` passes. Docker-based
checks could not run because Docker Desktop is unavailable locally. Whole-file
Ruff/format still reports pre-existing issues and line-ending formatting beyond
this scope.

**Next action:** no further action in this scope. Portainer deployment and
live validation remain external state, not inferred from the push. No migration
is included.

## ACTIVE TASK — Separate Computer inventory from OS-installation history

**Status:** deployed in 0.122.24. Follow-on identity-policy work is active below.

**Goal:** keep one counted Computer inventory record for each physical machine
or VM, while recording an OS installation separately when it has a distinct
life across Computers. A Ninja VM-guest observation is evidence only about the
Computer; a Ninja OS-agent observation is evidence about the OS installation
and may also contribute hardware evidence to the Computer it runs on.

**Scope:** additive Operations entity/relationship contracts, their
projector-owned evidence path, and Computer-detail presentation needed to show
the current OS and its hosting/name history. The existing `Device` table and
its entity anchor remain the Computer implementation during transition. No
production data repair, automatic merge, historical rebuild, or change to the
main Computers denominator is included.

**Decision:** use the following vocabulary. `Entity` is the generic storage
term. `Asset` is the broad inventory category. `Computer` is the physical or
virtual asset counted by Inventory and is currently represented internally by
`Device`. `OS installation` is a client-owned canonical entity only when its
own continuity is established; it is never another Computer inventory row.
`runs_on` is a dated relationship from OS installation to Computer. A source
observation remains evidence, not any of these entities. Computer-name reuse
is a cross-record history/navigation signal, never identity proof. An MCS
rebuild therefore creates a new Computer and OS installation; a proven OS move
closes one `runs_on` relationship and opens another.

**Constraints:** do not reuse the old `assets` / `os_instances` compatibility
tables as canonical identity anchors. ADR-0013 must be amended because its
assertion that an OS installation cannot move is contradicted by the approved
model. Relationship state must be produced through the shared evidence and
relationship projector; no connector, resolver, or UI route writes
source-derived relationship state. Source-free historical continuity must be
explicitly operator-authored and audited.

**Affected areas:** entity-class and relationship-type registry migration;
OS-installation canonical model and tenant/RLS constraints; Ninja observation
classification/projector; safe detail read model and template; ADR-0013;
model vocabulary; relevant focused existing tests.

**Validation:** Django check, migration drift/SQL review including RLS and
runtime grants, Python compilation, focused existing tests and template load,
and `git diff --check`. No new test scripts and no production writes.

**Checkpoint:** the repository already has `operations.assets` and
`operations.os_instances`, but ADR-0013 correctly identifies them as
projector-written compatibility caches, not canonical entities. Generic
`Entity`, relationship evidence history, and effective relationship projection
already exist. `Device` is a one-to-one `Entity` anchor and will remain the
Computer inventory anchor initially. The relationship registry has no
OS-to-Computer contract yet.

**Checkpoint:** migration 0153 adds the client-scoped `os_installation` entity
class, an OS-installation anchor and stable agent-record identity map, and the
one-to-many `os_installation_runs_on_computer` relationship. The database
trigger enforces the entity class/client match. The new projector groups agent
records already observed on the same Computer into one OS installation; a
stable agent identity moving to a different Computer changes the dated
relationship. `vm.guest` records never create an OS installation. The Computer
detail page displays the current tracked OS installation through a
security-barrier view. Existing Computer queries and counts are untouched.

**Validation:** root Python compilation passes; Django check and migration
drift pass; the device-detail template loads; the existing focused
`test_findings_queue` suite passes (10 tests); and diff check passes. Scoped
Ruff found only the migration's standard typing/import issues, which were
corrected; repository-wide views/models diagnostics predate this change.

**Next action:** commit the approved 0.122.24 release, push both deployment
remotes, trigger Portainer deployment, and verify migration 0153 plus service
health. The pending migration will create
canonical OS-installation anchors from current agent observations on its first
post-deploy projection; it does not change Computer inventory counts.

## ACTIVE TASK — Make automatic Computer identity rules operator-managed

**Status:** implementation complete; awaiting release approval.

**Goal:** move every automatic Computer matching decision currently embedded in
the resolver into visible, ordered policy data, so an administrator can review
and adjust matching confidence, required signals, and conflict blockers without
adding source-specific code exclusions.

**Scope:** an additive tenant-scoped identity-match policy registry, writable
Operations Admin surface, its seeded general rules, and resolver/fast-path
consumption. The existing stable source-record identity, usable-serial
normalization, tenant boundary, deleted-anchor rejection, and unique-candidate
checks remain non-bypassable implementation safeguards. No automatic merge,
production-data repair, historical rebuild, or source-specific policy is in
scope.

**Decision:** policy selects the ordered matcher (`source_identity`, `serial`,
`vm_uuid`, `hostname_mac`, or `hostname`), whether client scope and a unique
candidate are required, confidence, and which strong signals block that rule.
Code exposes and safely executes only these generic evidence primitives; it
does not contain a per-platform, virtualization, or customer exception. A
known conflicting configured signal blocks auto-attachment; no applicable
policy fails closed rather than promoting a Computer.

**Affected areas:** Operations model/admin/migration, `ingest.identity` policy
reader, fast path and resolver/promotion integration, ADR-0013 amendment, and
this plan.

**Validation:** migration review (tenant/RLS/grants/seed), Django check and
migration drift, Python compile, relevant existing tests, template/admin import
smoke check, and `git diff --check`. No new test or diagnostic scripts and no
production writes.

**Checkpoint:** migration 0154 adds `identity_match_policies`, RLS, explicit
runtime/ingest grants, and five seeded general rules. Operations Admin exposes
the policies as editable rows; deletion is disabled so a rule can be disabled
without losing its rationale. The collector fast path, delayed resolver, and
promotion recheck use one validated policy reader. Stable source identity now
selects only a live Computer. The evaluator's strong name+MAC review proposals
also require the enabled policy and honor its configured VM-UUID blocker.

**Validation completed:** Python compilation, Django check, migration drift,
focused existing ingest tests (2 passed; 3 existing Postgres tests skipped),
scoped Ruff, formatter check for files in scope, migration SQL review, and
`git diff --check` all pass. Whole-file Operations Admin formatting is not an
acceptance gate because it has pre-existing formatting outside this change.

**Next action:** obtain explicit approval to prepare the release (version and
changelog), commit, and push the reviewed migration. Deployment will apply
migration 0154; it does not repair or merge existing Computers.

## ACTIVE TASK — Reorganize the computer detail page around observations

**Status:** implementation.

**Goal:** preserve the current five device-page workflows while making the
computer the subject, showing every current source observation (including OS
agents and VM guests), and showing approved attributes as value plus reporting
source(s).

**Scope:** `device_detail` data reads and template organization; normalized
field-visibility configuration; and the MAC-address visibility correction. The
tabs stay five: Overview, Observations, Details, Activity, and Software. No
ingest, identity-resolution, or raw-evidence permission change.

**Decision:** source observations are distinct evidence of one computer.
Online/coverage remains agent-derived. Details uses the existing typed
attribute-claim read model, which already redacts sensitive/restricted values;
raw payloads remain accessible only through the existing audited admin reveal.
MAC address is an internal operational identity field, not redacted. Admins
manage the visibility classification through Operations → Admin → Config →
Fields; the setting changes presentation only.

**Validation:** read-only sample of available observation and claim data;
Django check, template load, focused existing device-detail tests where
available, compilation, and diff check. No new test scripts.

**Checkpoint:** Overview retains operational cards, controls, exemptions, and
issues and now adds Basic computer fields. Sources is now Observations and
lists every attached current/withdrawn source record with its plain-language
kind, reported status, record ID, and timestamps. Details shows each approved
typed value with the exact source record(s) that report it, flags conflicting
values, and provides separate expandable source-record sections. Legacy
`?tab=identity` bookmarks route to Details. Raw payload access is unchanged.

**Checkpoint:** migration 0151 changes `device.mac_address` from `sensitive`
to `internal`. Operations → Admin → Config → Fields now lets an authorized
admin set each normalized field's visibility level; changes are audited and
do not alter collected data.

**Validation:** Django check, migration-drift check, template loading, Python
compilation, diff check, and the existing focused `test_findings_queue` suite
pass (10 tests). The new observation and typed-claim queries were planned
read-only against production with tenant context and use the device/claim
indexes. Earlier attempts to run that focused suite from the wrong directory
failed only because its relative fixture paths were not present.

**Checkpoint:** the deployed page exposed a regression: its source-evidence
view is derived and waits for the next source-link sync after a manual merge,
so it cannot immediately show combined observations. Details also included
operational counters that belong on Overview/Activity.

**Next action:** add a safe current-observation read model, limit Details to
hardware/OS/network attributes, then validate and request release approval.

## ACTIVE TASK — Make strong-device review source-neutral and lossless

**Status:** release preparation.

**Goal:** let an operator confirm that two strong-evidence device anchors are
the same computer without choosing a source as the winner or discarding the
losing anchor's software inventory.

**Scope:** the existing two-device merge review, its merge helper, the strong
candidate entry point, and this plan. No automatic merge, production data
repair, schema migration, or host-to-guest relationship model is in scope.

**Decision:** a confirmed pair retains the older canonical anchor solely as a
stable technical identifier (UUID tie-breaker), moves both sets of current
observations to it, and presents that as combining observations of one
computer. It is not a source winner. Current software rows are reconciled by
their current-table identity before the remaining rows are moved; no software
row is simply dropped. The page groups repeated source-link rows by source.

**Validation:** sample current production strong proposals read-only; Django
check, template load, focused existing tests where applicable, formatting, and
diff check. No new diagnostic or test scripts.

**Checkpoint:** production sampling found 40 open `identity_strong` proposals.
Every sampled profile contains an agent observation and none includes a
`vm.host`; the Ninja `vm.guest` records are observations of the guest computer,
not observations of the physical host. The old UI asks the operator to choose
a survivor and defaults to Ninja. Its merge helper also deletes every current
software row on the losing anchor, so it does not meet this goal.

**Checkpoint:** the review now asks “Are these the same computer?” and uses
the older anchor only as a deterministic technical identifier, without a
source preference. Repeated source links are grouped by source. The current
software merge path reconciles same-product rows, then moves remaining rows;
it no longer drops the losing anchor's inventory.

**Validation:** read-only production query grouped all 40 open strong
proposals. Every profile contains an agent observation and none contains a
`vm.host`. Django check, changed-template loading, Python compilation, and
diff check pass. The new current-software reconciliation statements were
parsed and planned against production inside a rolled-back transaction; each
uses the existing device/product index. Repository-wide Ruff reports existing
violations in `views.py`; it is not a clean baseline.

**Next action:** commit the approved 0.122.20 release, push both deployment
remotes, monitor Portainer's automatic update, and verify health.

## ACTIVE TASK — Restore device merge review route

**Status:** release preparation.

**Goal:** make merge-candidate review links open the existing device merge
screen without a server error.

**Scope:** one obsolete template route name and this plan. No device-data,
identity, schema, or merge-behavior change.

**Decision:** use the current `org_index` route and its `org_slug` parameter
for the merge page's client breadcrumb; `client_detail` no longer exists.

**Validation:** template load, Django check, and diff check. No new test
scripts.

**Checkpoint:** production traceback identifies `device_merge.html` reversing
the retired `client_detail` route before it can render the review page. The
breadcrumb now targets `org_index`.

**Next action:** commit and deploy the approved 0.122.19 patch release.

## ACTIVE TASK — Strengthen device identity creation and resolution

**Status:** release preparation.

**Goal:** make the existing source-observation-to-device resolver apply the
same strong identity proof irrespective of arrival order, while retaining
review rather than automatic merging for existing split devices.

**Scope:** resolver matching and promotion, strong duplicate proposals, and
the existing merge-review presentation. Hudu remains non-identity
documentation evidence and continues to attach only through explicit relayed
source cards. No automatic merge, production-data repair, or schema change is
in scope.

**Affected areas:** `ingest/identity/`, Ninja observation writing, generic
source observation writing, merge-candidate projection, and review UI.

**Decisions:** source observations stay individually visible. Exact source ID,
usable same-client serial, and same-client normalized hostname plus a shared
valid MAC are automatic identity proof. Name-only remains a review candidate.
The resolver never moves an observation already attached to a different
device; it produces a high-confidence duplicate proposal instead. Existing
source-link match labels are unchanged because persisting identity-decision
provenance needs its own reviewed schema change; the review queue now shows
the actual strong-match reason.

**Validation:** read-only production query validation of the strong-pair SQL,
Django check, template loading, Python compilation, Ruff, formatting, and
diff check. No new test scripts.

**Checkpoint:** the reported pair is an active `WINDOWS_WORKSTATION` agent
and active `HYPERV_VMM_GUEST` record with the same client, normalized name,
and MAC; the guest record has no serial and Ninja assigns it a different
record UUID. Current production has 507 active Ninja agent/guest pairs with
the same client/name/MAC: 491 are correctly one device and 16 are split.
The resolver only applies MAC proof while grouping *unresolved* observations;
its fast and existing-device paths do not use MAC, and already attached
observations are never reconsidered. Canonical merge candidates are currently
hostname-only, so they cannot distinguish these strong pairs from weak
collisions. The review is now mapping a unified evidence tier and safe
remediation path.

**Checkpoint:** the fast path, delayed resolver, Ninja writer, and promotion
recheck now all use the same same-client normalized-name-plus-MAC proof before
the weaker hostname fallback. The existing merge queue receives a 0.9900
strong-identity proposal for every already-split pair and exposes both device
links plus the manual merge review. Read-only production validation found 40
current strong pairs across identity sources, including the 16 split Ninja
agent/guest pairs; they remain review-only.

**Validation:** Python compilation, Django check, template loading, Ruff,
Ruff formatting, and diff check pass. The read-only strong-pair query and the
full candidate `INSERT … ON CONFLICT` statement's `EXPLAIN` both ran against
production successfully without writing data. No new test scripts were added.

**Next action:** commit and deploy the approved 0.122.18 release. Identity-
decision provenance on the Source identities tab remains a separately reviewed
schema change; it is not needed for safe attachment or review of strong
duplicates.

## ACTIVE TASK — Make Computers Clear reliably reset filters

**Status:** complete; released as 0.122.17 / `d3b652d`.

**Goal:** make the Computers Clear control reliably remove every filter.

**Scope:** Computers filter template behavior and this plan. No query,
migration, or data change.

**Decision:** Clear explicitly navigates to the current path without its query
string, rather than relying on form/link interaction with duplicated controls.

**Validation:** template load, Django check, and diff check. No new test
scripts.

**Checkpoint:** Clear is rendered as an ordinary link inside the filter form,
but the user reports it does not reset the active filters.

**Checkpoint:** Clear now prevents the form interaction and explicitly reloads
the current path without query parameters.

**Validation:** Django check, template loading, and diff check pass. No new
test scripts were added.

**Next action:** none.

## ACTIVE TASK — Simplify Computers Hudu cell content

**Status:** complete; released as 0.122.16 / `73d1a45`.

**Goal:** remove repeated Hudu archive/link information and replace technical
card wording with human-facing link wording.

**Scope:** Computers Hudu table-cell template and this plan. No query,
migration, or data change.

**Decision:** render one Hudu record directly; reserve the summary/Details
expander for multiple records. Use `links` / `No links` instead of `cards`.

**Validation:** template load, Django check, and diff check. No new test
scripts.

**Checkpoint:** one record now renders directly as type, state, link status,
and direct links. Multiple records retain the compact summary/Details view.

**Validation:** focused coverage tests (8 passed), Django check, template
load, and diff check pass. No new test scripts were added.

**Next action:** none.

## ACTIVE TASK — Simplify Computers Hudu record filtering

**Status:** complete; released as 0.122.15 / `42e4d87`.

**Goal:** expose the useful Hudu record combinations as one plain-language
filter while keeping total Hudu presence separate.

**Scope:** Computers Hudu filter parsing, matching behavior, template controls,
and this plan. No migration or data change beyond the pending performance view.

**Decision:** keep In Hudu and Not in Hudu as total presence. Add one record
filter with Any, Has current, Has archived, Current only, and Archived only.
The result row always retains all Hudu records.

**Validation:** focused coverage tests, Django check, template load,
compilation, migration SQL review, and diff check. No new test scripts.

**Checkpoint:** multi-select Current/Archived state controls did not clearly
express the requested four useful record searches. The record filter is now
hidden and disabled unless In Hudu is selected, and the backend ignores it
otherwise. It supports Any, Has current, Has archived, Current only, and
Archived only while details retain all records.

**Validation:** focused coverage tests (8 passed), Django check, template
load, compilation, migration SQL review, and diff check pass. No new test
scripts were added.

**Next action:** none.

## COMPLETED SUBTASK — Make Hudu record-state filters multi-select with full context

**Status:** superseded by the simpler record-filter choices above; included in
0.122.15 / `42e4d87`.

**Goal:** allow Current and Archived Hudu state filters to combine while every
matching row retains its full Hudu record context.

**Scope:** Computers Hudu query/view, state-filter behavior, template controls,
and this plan. No source-data or identity-link changes.

**Decision:** retained the full-record display and narrow Hudu-computer
evidence view, then replaced the intermediate checkboxes with the simpler
plain-language record-filter choices above.

**Validation:** focused coverage tests, Django check, migration SQL review,
template load, compilation, and diff check. No new test scripts.

**Checkpoint:** the previous archive scope hid the counterpart record, making
an archived match unable to disclose an existing current Hudu record. Current
and Archived now qualify a row independently, while every matching row retains
both record types in its Hudu details. Migration 0150 scopes Hudu computers
before card expansion.

**Validation:** focused coverage tests (8 passed), Django check, migration SQL
review, template load, compilation, and diff check are in progress.

**Next action:** none.

## ACTIVE TASK — Make Hudu archive scope an explicit filter choice

**Status:** complete; released as 0.122.14 / `1cc567b`.

**Goal:** replace the additive archived-Hudu checkbox with clear current,
archived-only, and combined record scopes.

**Scope:** Computers Hudu filter parsing, query conditions, template controls,
and this plan. No migration or data change.

**Decision:** Hudu uses one archive-scope selection: `Current only` (default),
`Archived only`, or `Current + archived`. The legacy checkbox query parameter
continues to map to `Current + archived` for bookmarked links.

**Validation:** focused existing coverage test, Django check, template load,
and diff check. No new test scripts.

**Checkpoint:** current behavior exposed archived records as an additive
checkbox, so it could not express an archived-only view. The new archive mode
selects current-only, archived-only, or both, and the two duplicate controls
stay synchronized. Legacy archived-checkbox URLs map to `both`.

**Validation:** focused coverage tests (8 passed), Django check, template
load, compilation, and diff check pass. No new test scripts were added.

**Next action:** none.

## ACTIVE TASK — Synchronize duplicate Computers filter controls

**Status:** complete; released as 0.122.13 / `fd14a3b`.

**Goal:** ensure changing a filter in the top row or matching table-column menu
produces one consistent submitted value.

**Scope:** Computers template filter behavior and this plan. No query,
migration, or data change.

**Decision:** controls with the same checkbox name and value synchronize on
change. This fixes archived-Hudu state and avoids the same discrepancy for
other duplicated filter controls.

**Validation:** template load, Django check, and diff check. No new test
scripts.

**Checkpoint:** the top and column Hudu menus each render
`show_archived_hudu=1` inside the same GET form. Unchecking one therefore left
the other checked and still submitted the filter.

**Checkpoint:** matching duplicate checkboxes now synchronize their checked
state before form submission. Django checks, template loading, and diff checks
pass; no test scripts were added.

**Next action:** none.

## ACTIVE TASK — Prevent archived Hudu no-link filter timeouts

**Status:** complete; released as 0.122.12 / `ebdaccc`.

**Goal:** keep Computers usable when archived Hudu records and the `No links`
filter are selected together.

**Scope:** the Computers Hudu query, a read-only Operations migration, and this
plan. No source-data or identity-link changes.

**Decision:** use a narrow, security-barrier Hudu-computer observation view for
the no-link filter. It determines whether relayed cards exist without expanding
one SQL row per card; other filter paths retain their detailed-card read model.

**Validation:** Python compilation, Django checks, migration review, template
load, and diff check. No new test scripts.

**Checkpoint:** production logs show the exact URL exceeds Gunicorn's
30-second worker timeout in the card-expanded evidence query. The duplicate
query parameters are harmless; archived evidence makes the expansion too slow.
The conditional no-link read now uses the new compact view and returns NULL
card fields, preserving the existing Python rendering path without expanding
cards. Compilation, Django checks, template loading, migration SQL review, and
diff checks pass; no test scripts were added.

**Next action:** none.

## ACTIVE TASK — Simplify Computers Hudu details and filter menus

**Status:** complete; released as 0.122.10 / `e4dd249`.

**Goal:** make the Hudu column compact while retaining record-level detail,
and make Computers filter menus close predictably.

**Scope:** `apps/core/views.py`, `templates/coverage.html`, and this active
plan. No migration, source write, data-model change, or filter-semantics
change.

**Decision:** the Hudu cell shows a short current/archive/card summary with a
Details expander containing each separate record and its links. Filter menus
allow multi-selection but only one filter menu is open at a time; click-outside
and Escape close menus. Hudu detail expanders close other Hudu detail
expanders, but do not affect filters.

**Validation:** basic Django check, template load, Python compilation, and
diff check. No new test scripts. Commit, push, and deployment require
separate approval.

**Checkpoint:** the Hudu cell now summarizes a single record as its
current/archive state and card count, or multiple records as current/archive
counts. Its Details expander retains each individual record and direct links;
only one Hudu expander is open at a time. Filter menus now coordinate so one
is open at a time, outside-click and Escape close them, and checkbox clicks
preserve multi-select. Python compilation, Django system checks,
coverage-template loading, and diff checks pass. No tests or test scripts were
added.

**Next action:** none.

## COMPLETED TASK — Device issue drill-through and source-match visibility

**Status:** complete; released as 0.122.3 / `be93ffa`.

**Goal:** make the device header's issue count open the same combined set of
direct and installed-software issues that it counts, and make unresolved Hudu
records discoverable on the device Sources tab without presenting them as
confirmed source identities.

**Scope:** `apps/core/views.py` and the device-detail/Issues templates. No
migration, source write, identity merge, or change to source-link derivation.

**Decision:** the header uses an explicit device-impact filter in the existing
Issues queue: direct device findings plus active software findings exposed to
that device. The Sources tab retains its current confirmed-source table, then
adds a separate Hudu match section for *unlinked* current Hudu observations
with the same normalized hostname. Same-client/name rows are shown first;
name-only rows are visibly lower confidence. Archived state and the number of
currently reported Hudu cards are disclosed. These rows never count as a
source identity or Hudu presence and cannot create a link.

**Steps:** add the queue's device-impact filter and point the header to it;
load unlinked Hudu name matches for the device view; render the distinct
Sources section; run basic checks.

**Validation:** basic Django check, template load, Python compilation, and
diff check. Commit, push, and deployment require separate approval.

**Checkpoint:** live inspection of `md0421-1` shows three confirmed links
(Ninja, SentinelOne, LogMeIn) and one unlinked, archived Hudu Computer Assets
record with the same client/name and no relayed cards. Its 15 displayed active
issues comprise one direct device issue and fourteen inherited software
issues; the header previously sent `subject_id`, which returned only the one
direct issue. The header now sends `device_id` with snoozed records included;
the Issues queue resolves direct device findings plus the current software
exposure findings. The Sources tab now has a separate possible-Hudu-matches
section for unlinked same-name records, ordered same-client/name before
name-only and showing archive/card state. Basic Django check, template loading,
Python compilation, and diff check pass. No new tests were added.

**Deployment:** `be93ffa` was pushed to `origin` and the required `a-m-rose`
mirror. Portainer deployed that exact configuration; Operations and ingest
restarted healthy and Operations `/healthz` returns OK. The public device and
Issues routes return their expected login redirects (302) without an
authenticated browser session. Metabase was still in its normal startup health
check at the final poll; no Operations, ingest, or Postgres failure was
present.

**Next action:** none.

## PENDING TASK — Guard remaining Ninja external-ID casts

**Status:** implemented and locally validated; pending commit/push approval.

**Goal:** prevent malformed or out-of-range `external_id` values from raising
Postgres cast errors in the remaining Operations and ingest queries that join
Ninja source links.

**Scope:** `apps/core/client_workspace.py`, `apps/core/views.py`,
`ingest/intel/windows_servicing.py`, and focused regression tests. No source
data changes, compatibility-schema changes, or dashboard changes.

**Decision:** retain the existing Ninja-source and numeric-syntax predicates,
but make each projected numeric value a range-checked `CASE` expression. The
predicate alone is insufficient because the planner can evaluate a cast before
the predicate. Invalid values therefore join nothing rather than failing a
page render or ingest run.

**Steps:** replace the four casts; add a regression test for the guarded
expressions; run focused lint/tests, Django checks, and diff checks.

**Validation:** source-level regression coverage plus proportional Python and
Django checks. Live deployment verification requires a separately approved
commit/push/deploy.

**Checkpoint:** all four callers now make the conversion inside a
range-checked `CASE`: two shared Operations page queries use one helper,
Client workspace guards the integer Ninja location join, and Windows servicing
guards the bigint Ninja-device join. Malformed, blank, and oversized IDs now
produce NULL and cannot abort a request or source run. Focused pytest: 21
passed; Python compilation, Django check, migration drift, changed-file Ruff,
and `git diff --check` passed. Full `views.py` Ruff remains blocked by its
pre-existing findings (including the duplicate `timezone` import and an
unrelated f-string at line 979); this change adds none.

**Next action:** obtain separate approval to commit and push the scoped fix,
then verify the affected live pages and Windows servicing ingest after deploy.

## ACTIVE TASK — Coverage triage filters

**Status:** performance follow-up in progress; 0.121.2 (`9141a19`) is deployed.

**Goal:** replace the client/platform aggregate with a device-level Coverage
surface that makes current agent status and current Hudu documentation visible.

**Scope:** `apps/core/views.py`, `templates/coverage.html`, focused view/
template tests, and migration `0146_hudu_device_links_read_model.py`. The
pending external-ID guard remains a separate logical release change and will
not be folded into a Coverage commit. No finding lifecycle change or data
rebuild is in scope.

**Decision:** each required device/platform pair is classified as **Online**,
**Offline**, **Stale**, or **Missing**. Missing/stale use the native evaluator
findings; online/offline use current agent presence. The page will have one
summary card per required platform, with clickable Online/Offline/Stale/Missing
counts, and an ungrouped device table. Client, Online in, Required platform,
and Status filters are multi-select; selections inside a filter are ORed and
filters are combined with AND. The Hudu column says only **In Hudu** or **Not
in Hudu**, then lists existing Hudu cards by source and ID. Hudu data is shown
only when its current asset is safely attached to the canonical device; an
unresolved Hudu asset cannot be joined by hostname and remains in the existing
CMDB findings workflow. The platform-less lifecycle-only “Missing from Ninja”
section is removed because it cannot identify Ninja truthfully.

**Steps:** derive effective requirements in the page query, build statuses and
platform summaries, add filtered links and Hudu display data, then run focused
request/template tests, Django check, changed-file lint, and diff check.

**Validation:** focused request/query-shape and template tests, migration SQL
review (tenant guard, view ownership, grants, and explicit DML revokes), Django
check, migration-drift check, changed-file lint, and diff check. Deployment
and live read-model verification require separate approval.

**Checkpoint:** implemented the approved page. It resolves profile/global
requirements with per-client overrides and device exemptions, classifies each
required platform as Online/Offline/Stale/Missing, provides clickable
per-platform count cards, and renders an ungrouped device table with Hudu,
OS family, and device type. All six filters are multi-select. Migration 0146
adds a tenant-scoped `security_barrier` read model, owned by
`operations_view_owner`, that exposes only a device-attached Hudu asset URL
and card source/ID; it has an explicit runtime DML revoke and a grant limited
to SELECT. Coverage consumes it, using the existing platform-alias registry to
write known names such as SentinelOne correctly. A Ninja card that resolves to
the displayed device uses that device's name rather than a raw Ninja ID.
Unresolved Hudu assets remain outside this page because they cannot be safely
attached to a device. A Hudu section on device detail is explicitly deferred.

Focused pytest (3 tests), Django check, migration-drift check, migration SQL
render review, Python compilation, template load, changed-test/migration Ruff,
and `git diff --check` pass. Full-file Ruff has 48 established findings in the
large views module; this work adds none (the previous baseline had 50). Ruff
does not parse Django templates. The local SQLite database cannot execute this
Postgres-only view. An authorized read-only live `EXPLAIN ANALYZE` before the
read-model addition ran the Coverage requirement query in 1.280 seconds for
13,419 device-platform rows; live read-model and page verification wait for an
approved deployment.

**Deployment:** committed as `b1f6e27`, pushed to `origin` and the required
secondary mirror, and redeployed through Portainer. Portainer reports that
commit as the deployed configuration. Migration 0146 is applied; Operations,
ingest, Postgres, and Metabase are healthy. `/healthz` returns 200 and the
public Coverage route redirects to login (302). An in-container, runtime-role
probe executed the actual Coverage query and result-building path with a 200
result. The host has no active Django account suitable for an authenticated
browser render, so a real signed-in UI session was not exercised from the host.

**Follow-up scope:** replace the tall native multi-select controls with compact
checkbox dropdowns. The submitted query parameter names and multi-select
semantics stay unchanged. No migration or data change is involved.

**Checkpoint:** the follow-up has the requested two visible filter rows with
searchable checkbox dropdowns. Hudu presence, Hudu link availability, and
SentinelOne exemption are independently filterable; cross-filter selections
combine with AND. The Hudu column is width-constrained and wraps its card list.
The shared `filterbar` style initially placed the two row containers beside
each other, so Coverage overrides it to stack them. The first live full-fleet
render also produced a 3.9 MB response and exceeded Gunicorn's 30-second
timeout; device rows now paginate at 100 while the CSV remains complete.
Focused Coverage tests, Django check, template loading, Python compilation,
focused Ruff, and diff checks pass.

**Deployment:** committed as `9141a19`, pushed to `origin` and the required
secondary mirror, and redeployed through Portainer. Operations and Postgres are
healthy; `/healthz` returns 200 and the public Hudu-filtered Coverage URL
redirects to login (302). An in-container deployed-path probe for
`?hudu=in_hudu` returns 200 with 4,527 matching devices and exactly 100 rows
rendered, confirming pagination prevents the prior full-fleet timeout. Metabase
was still in its ordinary startup health check at the final short poll; no
Operations or Postgres failure was present.

**Next action:** none. A Hudu section on device detail remains deferred by
request.

### Inventory Computers — expand Coverage into the master computer inventory

**Status:** complete; released as 0.122.0 / `6c138f2`.

**Goal:** turn Coverage into the master Computers inventory, under top-level
Inventory navigation, while retaining coverage state only where a computer has
an agent requirement.

**Scope:** Coverage view/template/tests, primary navigation and URL routing,
and one additive tenant-scoped read-model migration. No source writes,
automatic identity merges, or data rebuild.

**Decision:** Inventory is organized by asset class, not source. The first
page is **Inventory → Computers**. Hudu is evidence about a computer, never a
navigation category or authority. The page will include active canonical
computers and active Hudu **Computer Assets** records. A confirmed Hudu card
attachment decorates its canonical computer row. An unattached Hudu record
gets its own inventory row; an exact same-client/name match is displayed only
as a possible match and never changes identity. Hudu data remains in its Hudu
column: present/no linked cards or its listed card references. Source columns
show current source status. Agent coverage cells apply only where a
requirement exists; otherwise they say Not applicable.

**Boundary:** Hudu also reports non-computer assets (for example servers,
printing, network devices, and locations). They are not dropped or recast as
computers; they need their own future Inventory asset-class pages. This change
implements only Computers and does not create a Hudu source-owned inventory
section.

**Validation:** focused request/template/migration tests, Django check,
migration-drift review, Python compilation, scoped lint/format, diff check,
and authorized live read-only row/count checks after an approved deployment.

**Checkpoint:** current production Hudu source data has a `Computer Assets`
layout (4,484 active observations in the authorized read-only check). The
existing `v_device_hudu_link_current` intentionally exposes only Hudu rows
already attached to a canonical device, so it cannot render an unlinked
computer such as Test-Asset. A new narrow inventory read model is required.

**Checkpoint:** implementation adds migration 0147 with a tenant-scoped,
read-only `v_cmdb_inventory_evidence_current` projection for all current
`cmdb.asset` observations, including unattached records and their card
references. It is source-neutral; Computers is its first consumer and filters
to Hudu's `Computer Assets` layout. The Coverage reader now starts from all
active canonical computers, adds unattached Hudu computer rows, overlays
confirmed Hudu attachments, and shows a unique same-client/name Ninja result
only as a possible match. `/inventory/computers/` is the primary route under
Inventory → Computers; `/coverage/` remains compatible. Hudu shows No linked
cards explicitly, source columns remain separate, and non-required coverage
is Not applicable. Focused tests pass (6), Django system/migration-drift
checks, Python compilation, template loading, focused Ruff/format, and diff
checks pass. Authorized production-scale timing: the expanded requirement
query is 0.736 seconds for 13,666 rows and the Hudu Computer Assets projection
is 0.313 seconds.

**Validation:** after generalizing migration 0147, focused Coverage tests pass
(6), `manage.py check` passes, `makemigrations --check --dry-run` reports no
changes, Python compilation passes, scoped Ruff/format checks pass, and
`git diff --check` passes. No additional data probes or test scripts were run.

**Deployment:** `6c138f2` was pushed to `origin` and the required
`a-m-rose` mirror. Portainer rebuilt the stack; Operations and ingest are
healthy, Operations `/healthz` returns OK, migration 0147 is applied, and the
unauthenticated `/inventory/computers/` route returns its expected login
redirect (302). The explicit Portainer Git-redeploy endpoint returned HTTP 400
because the stack had already picked up the current commit through its Git
update; the observed container restart and applied migration confirm the
deployment completed.

**Next action:** none.

### Inventory Computers CSV follow-up

**Status:** archive/CSV behavior released as 0.122.1 / `aa3afac`; filter-close
behavior is implementation in progress.

**Goal:** make the Computers CSV export contain the same current per-platform
columns as the rendered table, and make Hudu archive status visible without
mixing archived records into the normal current-inventory result.

**Scope:** the Computers view/template/tests and one additive read-model
migration exposing source archive state. Includes closing an open filter
dropdown when the user clicks elsewhere on the page. No source writes or
identity changes.

**Decision:** export one column for each current table platform, preserving the
table's value order: possible Ninja match, coverage state, direct source
Online/Offline state, then Not applicable. Hide archived Hudu evidence by
default, expose it with a Hudu checkbox toggle, and label it clearly in the
Hudu cell. Attached non-archived Hudu evidence belongs to Computers regardless
of Hudu layout; unattached Computer Assets and Servers records are computer
candidates.

**Validation:** focused Coverage/migration tests, Django check, migration-drift
review, compilation, and diff check.

**Checkpoint:** migration 0148 is applied in production. Active attached Hudu
evidence from any layout and unattached Computer Assets/Servers candidates are
included in Computers; archived Hudu evidence is hidden by default and can be
included from the Hudu filter. The CSV includes the current individual
platform columns. The remaining small UI follow-up closes filter dropdowns on
an outside click.

**Next action:** validate, commit, push, redeploy, and verify the filter-close
behavior.

### Performance follow-up — Coverage load time

**Goal:** measure and reduce the live Coverage page load time without changing
its current coverage or Hudu-filter semantics.

**Scope:** read-only live timing first, then the smallest page-query or render
change supported by the measurement. No raw credential inspection, data
change, or migration is in scope.

**Decision:** keep the Hudu read model and all existing Hudu filters, but read
and aggregate its card data once after the device-platform coverage query. The
existing query repeats the Hudu aggregation on every required platform row.
An authorized, tenant-aware live timing probe returned 13,416 coverage rows in
8.399 seconds with that join and 0.655 seconds with the same query minus the
Hudu CTE/join. The standalone Hudu read-model aggregation completes in about
0.2 seconds, so separate device-level attachment is the smallest safe fix.

**Checkpoint:** the Coverage query now returns required device-platform state
without Hudu repetition; a second tenant-scoped query retrieves each Hudu
attachment/card once and attaches it by canonical device ID before the existing
filters run. The Ninja card label remains `Ninja — <canonical hostname>` when
the card resolves to that device. Focused Coverage tests pass (3), Django
system check passes, focused Ruff and format checks pass, Python compilation
passes, and `git diff --check` passes. The exact deployed Hudu attachment
query returned 7,276 rows in 0.265 seconds; combined with the 0.655-second
no-Hudu Coverage query, this removes the measured 8.399-second join shape.

**Deployment:** released as 0.121.3 / `d241afe`; pushed to `origin` and the
required `a-m-rose` mirror. Portainer restarted the stack. Operations and
Postgres are healthy, `/healthz` returns 200, and the public Coverage route
correctly redirects unauthenticated users to login (302). An authorized
in-container probe confirmed the deployed second-query implementation and
completed the complete Coverage request path with a 200 result in 1.645
seconds. Metabase was still completing its normal health check immediately
after the stack restart; it does not participate in the Operations page path.

**Next action:** none. A Hudu section on device detail remains deferred by
request.

## COMPLETED TASK — Descriptive category on the Products page

**Status:** implemented, validated read-only against production, pending
commit/push approval.

**Goal:** `catalog.v_product_category_effective` (root migration 104,
descriptive taxonomy: browser, dev_tools, media, ...) had real data but
nothing in Operations read it. Wire it into the Products page as its own axis.

**Decision:** kept fully separate from the existing "Category" filter/column,
which is actually the security-relevant capability axis (av/rmm/remote_access)
despite the generic name — confirmed by reading `_software_page_data`
(`operations/apps/core/views.py`), where the existing "Not categorized"
count already reads `catalog.v_product_capability_effective`, not a
descriptive taxonomy. Conflating the two would have redefined an existing
live metric's meaning. New param `product_category`, new context keys
(`descriptive_categorized_titles`, `descriptive_category_rows`,
`active_product_category`), new "Type" chip strip/column/CSV column in
`software_products.html`. `_software_page_data` also serves the Overview page
and its CSV export, both left untouched — this axis is scoped to Products only.

**Scope:** `operations/apps/core/views.py` (`_software_page_data`,
`software_products`), `operations/templates/software_products.html`. No
migration, no schema change, no capability-model change.

**Validation:** `python manage.py check` clean; `py_compile` clean; `ruff
check` on `views.py` unchanged at 50 pre-existing errors (none in the new
code); template loads via `get_template()` with no syntax error. No focused
pytest suite exists for this page to extend (pre-existing gap), and the local
dev DB is sqlite so the raw Postgres SQL cannot be exercised locally --
validated instead by running the actual new SQL (probe, count, breakdown,
per-title array, both filter branches) directly against production
read-only: 24 categorized titles, 10-category breakdown, `browser` filter
returns 2, `uncategorized` filter returns 22,095 of 22,119 (24 categorized +
22,095 = 22,119, exact). No writes involved anywhere in this change.

**Next action:** request commit/push approval; verify the live page renders
and both chip strips work correctly post-deploy.

### Post-deploy incident — 0.120.2 broke the Products page, fixed as 0.120.3

Deployed 0.120.2, then verified live by logging in and fetching the page
directly (not just an unauthenticated route check) — it returned HTTP 500.
Log traceback: Gunicorn worker killed by its own timeout inside
`_software_page_data`'s main query. Root cause: the new `product_categories`
column used the exact correlated-subquery-per-row shape the pre-existing
`categories` (capability) column already used — `EXPLAIN ANALYZE` on that
pre-existing subquery ALONE, for one canonical_name, measured ~530ms, because
the plan starts from the small evidence table outward through a full
`products` seq scan rather than using the `canonical_name` correlation as an
index lookup. 500 displayed rows x that cost is minutes; adding a second,
near-identical subquery pushed an already-marginal query over the 30s worker
limit. The pre-existing capability column had apparently been running this
way in production already — my change is what finally exercised it hard
enough to surface.

**Fix (0.120.3):** replaced both correlated subqueries with two CTEs
(`category_by_title`, `product_category_by_title`), each a single `GROUP BY`
pass over the whole fleet, LEFT JOINed into the row list once instead of
re-executed per row. The `category`/`product_category` filter predicates were
rewritten the same way (array-containment against the CTE result, replacing
another correlated EXISTS of the same shape) rather than left half-fixed.
Rehearsed against production: `EXPLAIN ANALYZE` on the full rewritten query,
500 rows, both columns populated: 610ms total.

**Lesson:** "the SQL runs correctly" (which I did verify, read-only, before
the first deploy) is not the same claim as "the SQL runs fast enough for a
30s worker" — mirroring an existing pattern inherits that pattern's
performance characteristics, and a pattern that was already marginal doesn't
show up as broken until something adds load to it. Live authenticated
verification (not just a route/login check) is what caught this, immediately
after being asked directly whether the live page had actually been checked.

## COMPLETED TASK — Category confirm/reject review (0.120.4)

**Status:** implemented, rehearsed against production (write path only, in a
rolled-back transaction), pending commit/push approval.

**Goal:** `catalog.category_assertion_operator` (migration 104) had no UI at
all — every category assertion was stuck at "candidate" forever. Capability
already has a full confirm/reject loop (`software_capability_decide`,
ADR-0018); category needed the same shape on its own axis.

**Decision:** dedicated `curate_software_category` permission, not reuse of
`curate_software_capability` — same reasoning as why `authorize_software_product`
got its own permission rather than folding into the capability one: category
is a different decision from capability, so it gets its own grant, even
though (unlike capability) it can never alert. `apps/core/category.py` mirrors
`capability.py`'s write boundary exactly (operator INSERTs, only ever
withdraws via column-restricted UPDATE) but drops the `alertable` field
entirely, since `v_product_category_effective` has no such axis.

**Scope:** `apps/core/category.py` (new), `apps/core/views.py`
(`software_category_decide`, category context in `software_detail`),
`apps/core/models.py` (new permission on `SoftwareCatalog.Meta`),
migration `0144_category_review.py` (permission only, no DDL — same
`SeparateDatabaseAndState` avoidance 0137 documents for capability),
`config/urls.py`, `templates/software_detail.html` (new "Category" card).

**Validation:** `python manage.py check` and `makemigrations --check
--dry-run` clean (migration matches model state exactly); template loads;
`ruff check` on all new/changed files: 0 new findings (`category.py`,
migration, `urls.py` fully clean; `views.py` unchanged at 50 pre-existing;
`models.py`'s 4 pre-existing DJ008 findings untouched). Rehearsed the actual
confirm/withdraw SQL against production in a rolled-back transaction on a
real row (google chrome / browser): candidate → confirmed → candidate,
exactly as designed. No live UI write was exercised (would have left a real
row in production without a specific reason to), only the read-only render
path and the SQL logic in isolation.

**Next action:** none — deployed and verified live (see below).

### Post-deploy: manual assign for zero-evidence keys (0.120.5)

User hit "Unknown — no effective capability/category evidence" on a real
product and asked where to choose one — confirmed neither axis had any way
to originate an assertion when nothing had ever suggested it; confirm/reject
only reacted to existing rows. Added `all_capabilities()`/`all_categories()`
(read the registry vocabulary) and a per-product `missing` list (registry
keys minus keys already present in `product.rows`) in the view, plus a
"Not yet evaluated" dropdown+confirm/reject control in the template,
separate from the existing per-row controls. No backend write-path change
was needed — `confirm()` already writes directly to `*_assertion_operator`
with no dependency on machine evidence existing.

User feedback: don't call it "Assert" in the UI — labeled the action
"Yes, it is" / "No, it isn't" instead of introducing new jargon.

Rehearsed against production, read-only + rolled-back: confirmed
`endpoint_security` as refuted on anydesk (which had zero prior evidence
for that key) without disturbing its existing `remote_access` rows.
`python manage.py check`, template load, and `ruff check` (0 new findings)
pass. Pending commit/push approval and live verification.

## CURRENT TASK — Cross-client serial drill-through

**Status:** deployed as 0.119.9 / `7384e6e`.

**Goal / scope:** make a device-page cross-client-serial link show the entire
conflict group in the existing Issues queue, and make its shared-serial
evidence visible. Scope is the `finding_types` registry, the Issues queue,
the device-detail link, a Django migration, and focused tests.

**Decision:** per-device findings remain the lifecycle/action records. The
registry chooses their drill-through: empty grouping key preserves the current
subject-scoped queue; a configured JSON evidence key opens the same finding
type's whole evidence group. `cross_client_serial` configures `serial`.
The queue validates the grouping key from the registry rather than accepting
an arbitrary JSON field from the request.

**Validation / next action:** migration 0143 registers the field and configures
`cross_client_serial`; the link, queue validation, scope notice, and evidence
text are wired. Focused tests (10), Django check, migration-drift check,
template loading, compilation, and diff check pass. Migration 0143 applied;
both services are healthy. Production confirms the seeded registry key and a
sample serial group resolves to two findings, devices, and clients.

## Device-detail patch signal source guard

**Status:** release authorized as `0.119.6`; commit and deployment pending.

**Goal:** prevent an unrelated source link from crashing a device-detail page
while it loads Ninja patch-signal context.

**Scope:** `apps/core/views.py`, a focused unit test, and this plan. No
schema, source data, patching policy, or rendered patch-signal semantics
change.

**Decision:** derive valid 32-bit Ninja IDs from the device's already-loaded
source links before querying `ninja_patches.device_patch_signal`. The prior SQL
cast every candidate link as an integer; PostgreSQL may evaluate that cast
before filtering source name, so a large SentinelOne ID caused a 500 despite a
valid Ninja link. The new lookup only queries those valid Ninja IDs.

**Validation:** focused helper test, Django check, changed-module compilation,
and `git diff --check`; production reproduction and page verification require
separate deployment approval.

**Checkpoint:** production confirms the reported device has one valid Ninja
link and one out-of-range SentinelOne link. The rewritten lookup queries only
valid Ninja IDs. Focused regression test, Django check, changed-module
compilation, and diff check pass.


## Product authorization scope context

**Status:** deployed as `0.119.5` / `4731a45`.

**Goal:** make a client-scoped product authorization understandable at the
point of decision by showing each currently affected client's device and
installation counts in the existing product-detail selector.

**Scope:** `apps/core/views.py`, `templates/software_detail.html`, and a
focused display contract test. No schema, authorization precedence, or
finding-emission change.

**Decision:** counts come from the full current-installation relation, not the
500-row device list rendered below the fold. The selector remains an explicit
global-or-client permit/deny action; it does not infer ownership or create an
authorization automatically.

**Validation:** focused test, Django check, changed-file compilation, and
`git diff --check`.

**Checkpoint:** deployed as `0.119.5` / `4731a45`. The existing
product-detail authorization selector now labels each current client with its
full device and installation counts. Focused contract test, Django check,
changed-module compilation, template loading, and diff check passed; both
services were healthy after Portainer redeploy. No migration, policy behavior,
or authorization data changed.


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
