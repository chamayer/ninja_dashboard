## PLAN-030 — Bulk accept discovered client candidates

**Status/goal:** Complete (released 0.133.0, `020cf560`, 2026-10-30). Let an operator accept selected open source-client
candidates as new Operations clients in one reviewed action.
**Scope/files:** `apps/core/views.py`, `config/urls.py`,
`templates/inventory_clients.html`, `templates/client_mappings.html`, and the
bulk-confirmation template; no schema change. Preserve unrelated dirty edits.
**Decisions:** Reuse the existing accept-as-new behavior for each selected
candidate, including tenant scope, client entity anchor, aliases, source-group
attachment, resolved actor/reason, and audit record. Do not map to existing
clients or alter resolver thresholds. Show selected names/count before the
final POST; require an operator reason; reject the whole batch if any selected
candidate is no longer open.
**Validation:** Python compilation, `git diff --check`, plan-registry validation,
Operations image build, and `manage.py check` pass. No automated tests were
added or run; the user wants a manual dev opportunity. No feature migration,
source collection, candidate acceptance, commit, push, or production deployment
occurred.
**Checkpoint:** Selection, confirmation, atomic all-or-none acceptance, source
group attachment, actor/reason audit, and shared helper are implemented. After
explicit local approval, Compose applied pending migrations 0358 and 0359 and
recreated Operations with the new image. The action is available from both
Inventory → Clients and Client mappings. Operations and Postgres are healthy
at `localhost:3003`; ingest remains healthy and Jobs worker is running. Login
GET returns 200 and `manage.py check` passes. The Jobs ledger remains at 9
completed and 1 failed run; no candidate was accepted and no source collection
ran. Released 2026-10-30 as 0.133.0 at the user's request ("commit plan-030 and
close it out"); ported onto production master with the PLAN-003 R2 findings guard
on the single and bulk accept handlers. Verified deployed: healthy containers,
contract 4, routes respond. The uncommitted copy in the main folder is superseded.

## PLAN-025 — Shared ScreenConnect and Operations inventory summary

**Status/goal:** Complete. Shared ScreenConnect support and the Operations
inventory card are implemented; the authorized first production collection and
its dependent resolver/evaluation chain have completed.
**Scope/files:** `ingest/sources.py`, `ingest/connectors/screenconnect.py`, focused collector tests,
`apps/core/views.py`, `templates/coverage.html`, focused coverage tests, and
root/module checkpoints and registry. Preserve the pre-existing dirty worktree.
**Decisions:** Reuse current Computer membership/reporting filters (PLAN-012).
Operations counts Online/Offline/Stale once per Computer, independent of filters,
with the same classifier for its drill-throughs. Preserve scoped ScreenConnect
`source-instance/self` identities. Shared mode explicitly selects a customer
custom property, rejects client-scoped configuration, and retains ungrouped
evidence; existing resolvers own mappings. Operational contract:
[`screenconnect-source.md`](../docs/reference/screenconnect-source.md).
**Validation:** 39 collector/observation tests and 40 coverage/Computer-read tests
pass; Django system/template checks, Python compilation, collector/config lint,
Operations fatal lint, registry validation and whitespace pass. New collector/test
files pass formatting; existing config/view/test files retain prior formatting.
Dockerfiles already copy every changed runtime file. Live shared collection and
browser behavior are unverified. Root blueprint already exceeds its 4,000-byte
governance limit; unrelated checkpoint reconciliation is outside this scope.
**Checkpoint:** Local implementation and initial production source refresh are
complete. `AMROSE ScreenConnect` (`sc_amrose`) and its `internal-ingest` binding are
enabled with a four-hour schedule (`interval:240`), which the user saved from
the Sources GUI after implementation. Refresh run
`5e27a49b-db4a-45b5-b9aa-93baf9b5adc4` completed with 4,632 rows touched, zero
failed rows, and a complete 4,507-session snapshot. Aggregate metadata shows
4,424 sessions with Company, 83 without it, 125 Company groups, no empty-name
groups, 97 groups with a client, and 28 unassigned groups. The dependent identity
resolver completed at 21:22 UTC (`resolved=417`). Platform evaluation
`e78b011c-aabd-4bde-bf76-f24e293b3c3b` is now stalled, not waiting on AMROSE
data: it was coalesced with a Ninja chain whose `ninja-enrichment`
`9d781258-5917-4be6-9550-091b6c85c53c` stopped before a terminal result at
21:27 UTC. Its dependent `patches` and `patch-classify` runs, then evaluation,
were marked stalled. Portainer logged a successful stack deployment at 21:27;
Docker events show Operations, ingest, and Jobs containers were replaced at
21:27:32. The initiating actor/trigger is not present in the retained logs.
All three services are healthy now. Replay-safe recovery automatically retried
Ninja enrichment (`e67d87c0-0411-4599-86ff-b4a6f4634ea2`), which completed at
21:32 UTC. Its new patches run completed at 21:33:50, patch classification
completed at 21:33:53, and platform evaluation
`c77515f0-bcba-4b0e-8a50-dd298eb63a2e` completed at 21:39:15 with 5,874 rows
touched and no error. The original interrupted workflow remains stalled in
history. The source
refresh completed despite an opportunistic generic relationship projection
error (`relationship source cardinality would be exceeded`), which the pipeline
logged and continued past. No migration, commit, or push.
The shared connector explicitly selects a customer
`CustomProperty1`–`CustomProperty8`, preserves unassigned sessions, and keeps
scoped ScreenConnect identity unchanged. The Operations Computer summary card is
already present in the local worktree; preserve it and the unrelated dirty work.
On 2026-10-28, the user-provided `https://support.amrose.it/` returned HTTP 200
and its published labels identify Company=CustomProperty1, Site=2,
Department=3, Device Type=4. The user added the AMROSE GUID/key to the private
ingest runtime. A read-only request then succeeded with 4,511 Access sessions,
of which 4,506 were active host sessions. CustomProperty1 was populated on
4,422 active sessions and had 125 distinct values; 83 values matched Ninja
organization names case-insensitively, and 85 matched after punctuation-
insensitive normalization (78 Ninja organizations). CustomProperty2 had 90
distinct values with 7 case-insensitive matches; CustomProperty3/4/5/8 had
substantially less or no overlap. The response exposed no explicit
`Group`/`SessionGroup`-named field. A direct read-only `GetSessionGroups` call
to the RESTful API Manager endpoint returned HTTP 500 without group
definitions. Company/CustomProperty1 is supported as customer metadata, but
this does not establish ScreenConnect's separate Host-page container/group
membership; 40 distinct Company values still have no normalized Ninja-name
match. Of 4,506 active hosts, 84 have no Company value. These sessions must
remain source evidence without an empty-name org/container or client mapping.
The existing identity resolver may still associate a session to a client when
it matches a known Computer; otherwise it remains unassigned.
Read-only inspection through the private ingest-host profile found one enabled
ScreenConnect source, assigned to a client, with a different base URL. Do not
use its credential pair against the shared URL. The local connector tests pass
(8); Operations test startup is unavailable on this workstation because the
`shared` Python package imported by `operations/apps/core/admin.py` is absent.
Prior focused Operations checks are recorded above. On 2026-10-28, the
production instance `AMROSE ScreenConnect` (`sc_amrose`) and its `internal-ingest`
binding were created and then enabled with `CustomProperty1` grouping. The
binding remains unscheduled; private GUID/key references are present in the
ingest runtime. Creation and activation are recorded in `operations.change_actions`.
The first refresh completed as recorded above. No migration, commit, or push
was performed. The existing client-scoped UTA instance is unchanged.
Configuration guidance is in
[`screenconnect-source.md`](../docs/reference/screenconnect-source.md).
**Deferred:** A possible cross-scope ScreenConnect serial/MAC identity conflict
needs review without assuming client ownership; tracked in
[`operations/TODO.md`](TODO.md). The separate Host-page container definitions
remain unavailable through the tested RESTful extension. No migration, commit,
or push was added.

## PLAN-032 — Per-instance source display titles

**Status/goal:** Complete. The Sources page displays each configured source
instance name while client-mapping filters retain the shared catalog identity.
AMROSE is labeled **AMROSE ScreenConnect**; the UTA instance keeps its own label.
**Scope/files:** `apps/core/views.py` and `templates/sources.html`; no schema
change.
**Decision:** `source_instances.config.source_name` is the per-instance display
label. Keep `operations.sources.name` as the catalog identity used by client
mapping filters.
**Validation:** Python compilation and staged `git diff --check` passed; tests
were not run. Commit `9aef8fc` is present in both `origin/master` and
`a-m-rose/master`. Live browser verification remains unconfirmed.
**Checkpoint:** The code is committed and pushed to both remotes. No migration
was required. See `docs/records/PLAN_REGISTRY.md` for lifecycle status.

## PLAN-024 — Preserve Ninja software display names

**Status:** Complete locally (2026-10-27; user authorized and expanded scope
2026-10-27).
Goal: show the original Ninja program name wherever a human sees a software
product in Operations while keeping lowercase `canonical_name` as the stable
key for matching, decisions, filters, and URLs. Scope includes the existing
ingest/migration work and every human-facing Operations software UI and export
that renders product names. Existing rows display `canonical_name` as a
fallback until the next Ninja inventory refresh. Commit authorized
2026-10-27; origin push requires explicit migration 0354 and auto-deployment
approval.

**Steps:** add an additive current-installation display column; carry the
trimmed source name through the inventory staging/upsert without including it
in material-change hashing; audit every human-facing product label and wire a
consistent source-name lookup while retaining canonical values for matching
and links; validate the changed paths and whitespace.

**Decision:** source names may vary in case per installation, so preserve the
Ninja title per current installation rather than inventing title case or
changing canonical identity. `software_installation_history` remains unchanged
because this page lists current installations.

**Checkpoint:** migration 0354 adds the current-row column with an empty
default and no fleet-wide backfill. Reads fall back to `canonical_name`, and
ingest writes the trimmed Ninja name on every inventory apply, including
casing-only changes that do not alter material history. The shared resolver
is wired through product/installations pages, details, review and decision
surfaces, findings, client/Computer views, exports, and software admin lists.
Canonical values remain matching, decision, filter, and URL keys. Python
compilation, focused Ruff, plan registry validation, and `git diff --check`
pass. Django checks/template rendering are unavailable because Django is not
installed; tests and live behavior have not been verified. Commit authorized
2026-10-27. Push authorization must explicitly include migration 0354 and its
automatic Portainer deployment.

## PLAN-020 — Operations entity links in tables

**Status:** Complete locally (2026-10-26); plan registry entry added
2026-10-26. Goal: link names for
identifiable clients, Computers, and other entities in tables to detail pages,
preserving links that serve review, evidence, or source-record workflows.
Breadcrumbs should provide useful return paths where straightforward. Scope is
Operations UI templates and only the view context/routes needed to identify
existing detail destinations; no schema or migration changes.

**Checkpoint:** Added direct links across mapping review, client and Computer
inventory, source records, generic entity evidence, patching, software, and
notification tables. Existing candidate/source/filter workflow destinations
remain available. Client and Computer detail pages have breadcrumbs; the
generic entity detail page retains its existing Entity evidence return link.
Python syntax compilation, plan registry validation, and
`git diff --check` pass. Ruff reports no findings on the changed Python lines;
the full files retain unrelated lint findings. Django checks are unavailable
because Django is not installed locally.

**Next:** commit this scoped change locally. Obtain explicit approval before
the `origin` push, including its automatic deployment and any pending
migrations.

## Requirement profile assignment visibility

Active (user authorized 2026-10-23). On the Requirements page, add scoped
baseline rows (All, Servers, Workstations) with validated preset fields and
an explicit role-list conflict choice: copy the All baseline first or replace
that role's list. This preserves the evaluator's existing replacement-list
semantics. Also show each profile's assigned active clients, plus clients
inheriting the default profile, in collapsed lists; permit audited
individual and selected-client bulk assignment from those lists. Scope:
requirement-profile page/view/tests only; no schema, evaluator, automatic
legacy migration, commit, or push. The scoped-editor UI was committed and
pushed as `9024b46`. Expanded scope (user authorized 2026-10-23): retire the
runtime Global fallback without deleting legacy rows. A null client profile
inherits the tenant-default (Standard) profile and a non-null profile is an
override; update evaluator/readers, onboarding, and UI consistently.
Checkpoint: implementation complete locally. Updated evaluator, automatic
resolution, software capability derivation, Computer requirement display,
onboarding, client configuration, profile UI, architecture authority, and
ADR-0042. Compilation, focused Ruff, scope import, plan-registry, and scoped
whitespace checks pass. Django/pytest cannot run on the workstation and the
local Operations container is stopped. Commit/push not authorized.

## Inventory source-record scope

Active (user authorized 2026-10-22). Add a muted `Records` source-population
count to each Computer inventory card and a muted `Computers` header above the
existing Computer-based status rows. `Records` counts only Computer-capable
source records (including unlinked and withdrawn ones), never client/group
records; the existing `Total` remains the status subtotal for Computers.
Scope: coverage view, template, and focused test; no schema or data change.
Checkpoint: aggregate narrowed to the card's Computer record types. Focused
coverage tests (23), Django system check, Python compilation, fatal lint, and
whitespace validation pass. Commit/push not authorized.

## Finding recalculation contract

Active (user authorized 2026-10-22, including commit and deployment push).
Goal: make each normal finding reevaluation refresh its present evaluation
data—including severity, confidence, attribution, and details—while retaining
the original episode start and operator-controlled status. Client-mapping and
platform-infrastructure conditions are critical and appear prominently on the
fleet and client pages. Scope: finding producers, focused regression tests,
and dashboard presentation; no schema or direct production-data migration.
Checkpoint: committed and pushed as `0358966` (origin, then `a-m-rose`).
Focused tests (22), Django system check, Python compilation, fatal lint, and
whitespace validation passed. Deployment is the origin-push automation; no
schema or direct production-data migration is included. Next action: verify
the deployed application and observe normal producer reevaluation.

## Source records runtime-read repair

Active (user authorized 2026-10-22). Production `/inventory/source-records/`
returned HTTP 500 because the new reader queried the restricted
`entity_observation_current` table under `operations_app`. Replace its count,
type-list, row, and name-search reads with the existing tenant-scoped,
read-only `v_entity_observation_admin_metadata` projection; add a structural
regression test. No schema, data, policy, or source-link changes. Validate
the focused test, Django check, lint, whitespace, and the deployed endpoint
after separately approved commit and push. Current checkpoint: implementation
complete locally. Focused source-reader tests (8), Django system check, Ruff
fatal/import checks, plan-registry validation, and whitespace validation pass;
full-file Ruff retains pre-existing complexity/style findings in `views.py`.
Next action: obtain separate commit and deployment-push authorization, then
verify the deployed route under the runtime role.

## Client mappings — recorded and movable (ADR-0040)

Status: ADR-0040 accepted 2026-10-23. Step A ("Computer under the wrong
client?") shipped in a2d0791 (migration 0340, deployed 14:54 UTC). Step B
(decisions 1, 2, 4 on the client page) implemented locally, not committed.
Goal: every automatic client mapping is a recorded decision and any mapped
source group can be moved to another or a new client, one/several/all at once
(user requirement). Order agreed: (1) this; (2) one name-difference finding
per client with a row per source, critical while unconfirmed; (3) automatic
client promotion (ADR-0041).
Audit (code read): resolver name-match attach writes no decision (reason
discarded); both attach paths fill only `client_id IS NULL`, so no move
exists; link rows keep their id when the client changes, so a move must
supersede the decision. Computer side: merges recorded and reversible in SQL
(`split_computer_merge`) but no UI; hostname-variant collapsing unrecorded —
backlog. Production: 177 open `client_name_conflict` findings across ~40
clients (one per source link).
User decisions 2026-10-23: a Computer's findings belong to the Computer and
the client inherits them (stored `client_id` copies move with the Computer);
name differences are critical (amend ADR-0025's "low"); automatic promotion
is not a source authority — it creates a provisional client so operations can
start, verified by an operator later (Track C stands).
Inventory (production, read-only, 2026-10-23): no RLS policy uses
`client_id` (tenant only). Live copies of a Computer's client: `entities`
(device), `findings` (subject_type device), `software_installations_current`,
`software_decisions`, `device_windows_servicing_current`,
`operating_system_installations`, `computer_name_collisions`; history tables
keep what was written. All copies match their Computer (only 8 closed
findings differ). Requirement state stores no client. Inconsistent
relationships: 23 live Computers hold active records from another client
(30 records; e.g. 10 Hudu "Landau Realty" records on Vedorium Computers);
only 9 are covered by `cross_client_conflict`/`cross_client_serial`
findings. 22 LogMeIn device records sit in groups with no active org record.
Legacy `ninja_agent_compliance` has its own client ids; out of scope.

### Step A — one finding: "Computer under the wrong client?" (approved 2026-10-23)

Replaces `cross_client_serial` (and the retired `cross_client_conflict`) with
`computer_client_conflict`, one per Computer, subject the Computer. Evidence:
active records whose client differs from the Computer's (raises), a usable
serial shared with a live Computer of another client (raises), same name in
another client (supporting only). Actions on one/several/all selected issues:
move the Computer to the one other client its evidence names; keep as is
(intended or different machines, recorded per evidence key in decision
dimension `client_conflict_accepted`; new evidence raises it again); source
is wrong (acknowledged, clears when the source is fixed).
Move (`operations.move_computer_to_client`) updates the Computer and every
live copy: device entity, its os_installation entities and
`operating_system_installations` (trigger requires matching client), device
findings, `software_installations_current`, `software_decisions`,
`device_windows_servicing_current`, `computer_name_collisions`. Records keep
their group's client, so records of the old client become evidence.
Files: migration 0340, `ingest/identity/findings.py`,
`ingest/identity/resolver.py` (drop cross_client_serial emitter),
`finding_actions.py`, `identity_actions.py`, `human_labels.py`, `views.py`
summary SQL, tests.
Overlap measurement (2026-10-23, read-only): source-group findings — 28 of 38
open `unmatched_source_group` are for groups already linked to a client
(stale) and 7 duplicate `client_unattached_group`; identity — 190 Computers
carry identity findings, 23 carry two or more types (mostly
`duplicate_device_records` with `identity_conflict`, `computer_name_collision`
or `duplicate_platform_record`). Recorded in TODO as follow-ups.
Checkpoint: step A shipped (a2d0791; hotfix 8f521af after b30f259 shipped
views hunks early). Validated by tests and a rolled-back production
rehearsal; not browser-checked.

### Step B — record automatic mappings; move source groups (2026-10-23)

Migration 0341: `record_automatic_client_mapping_v1` (resolver writes
automatic/resolver decisions only where none exists) and
`move_client_source_group_v1` (moves the link and its history now, because
collectors read a group's client from the link; the group's org record and
device records on the old client; an operator decision naming both clients;
the enabled alias for that name; Computers whose active records all move,
via `move_computer_to_client`; mixed ones are left for
`computer_client_conflict`). Resolver step `_record_automatic_mappings`
(skips until 0341 exists). Client page: select one/several/all source
references, then confirm, move (to a chosen client) or ignore with a reason
(`client_mapping_bulk`, all or nothing).
Validation: Django check clean; Operations 4 and ingest 5 failures, all
pre-existing; new `test_client_source_group_move.py`,
`test_client_resolver_automatic_mappings.py`; lint/format unchanged per
file. Rehearsed on production, rolled back: Prompt's Ninja group "MDA" to
Starfire moved the link (one open history row), the org record and 15
device records, wrote "Moved from Prompt to Starfire: …", left 12 mixed
Computers; the automatic decision wrote once and refused a second time;
commit-time checks passed. Not browser-checked.
Not in scope yet: moving to a new client from this form (use a candidate
Accept), Issues-side bulk for name differences (ADR A, one finding per
client).
Shipped in d121f4d (migration 0341, deployed 15:12 UTC); 358 links await
their automatic decision on the next resolver run.

### Step C — one name-difference finding per client (2026-10-23)

`client_name_conflict` is one finding per client (ADR-0040 decision 6,
amends ADR-0025): a row per source group, "matches" when the name equals the
client's under `_norm`, settled when confirmed or ignored, otherwise
"differs"; critical while any row differs. Per-link findings resolve as
unseen. Issues text lists the differing sources and links to the client
page's source references; Inventory › Clients counts differing groups.
Production preview (read-only): 177 open findings become 28 (43 differing
groups). No migration.
Validation: Django check clean; Operations 4 and ingest 5 failures, all
pre-existing; `test_client_name_drift_contract.py` rewritten for the
per-client contract. Not browser-checked.
Shipped in a9efa19 (no migration, deployed 15:28 UTC).

### Step D — automatic client promotion (ADR-0041, accepted 2026-10-23)

User decisions: map on 2+ computer names owned only by one client; creation
built and switched on; build approved. Migration 0342: provisional marker on
clients (`provisional_since/_reason`, `verified_at/_by`),
`promote_client_candidate_v1` (one recorded change: provisional client as
Accept creates it, or an existing client; source-tier alias; candidate closed
by the resolver), `evaluator_config` row `client_promotion` (thresholds,
required source "Ninja"). `shared/client_evidence.py` holds the
computer-name and kept-separate rules for the candidate page and the
resolver. Resolver step `_promote_candidates` runs before name matching so
the alias attaches the groups in the same run. Inventory › Clients:
"Promoted automatically — verify" (verify, retire an emptied provisional
client) and the settings form.
Validation: Django check clean; makemigrations clean; Operations 4 and
ingest 5 failures, all pre-existing; new `test_client_promotion.py`,
`test_client_promotion_views.py`; lint/format unchanged per file except
other sessions' hunks. Production rehearsal (rolled back) prepared but not
run: SSH to the host timed out at about 16:35 UTC. Not browser-checked.
Production 2026-10-23 (read-only): would map "MDA" (R-U-ON) to Prompt
(3 names); creates nothing (no open candidate is reported by 2+ sources).
Resolver had still not run after the 15:35 collection (collection still
running at 16:03); Jobs re-queue gap is in TODO.
Next action: run the rehearsal when SSH is back, then user approves commit
and push (migration 0342 adds columns to clients; quick).

### Step E — follow-ups built while SSH was down (2026-10-23)

User chose: build stale-finding cleanup, move to a new client, undo-merge
button, re-run interrupted jobs; domains learned + editable (ADR-0042
proposed); "One machine or two?" design first (ADR-0043 proposed); name
matching after checking real data.
- Stale `unmatched_source_group`: the resolver deletes rows whose group now
  has a client link and closes findings whose row is gone (race: a
  collection before the next link sync re-recorded attached groups).
- Move to a new client: "New client…" in the client page move; the client is
  created as Accept creates it (`_new_client`, shared with Accept), then the
  ADR-0040 move runs. No migration.
- Undo merge: "Merged into this Computer" on the Computer overview, Split
  with a reason (`computer_merge_split` → `split_computer_merge`), both
  Computers named again.
- Interrupted jobs: `replay_interrupted_runs` requests again each
  replay-safe run a worker restart interrupted (trigger `recovery`, linked as
  a retry, deterministic request identity, once only, skipped when a later
  run covers it); called beside `reconcile_replay_safe_containment`.
Validation: Django check clean; Operations 4 and ingest 5 failures, all
pre-existing; new tests for each. None rehearsed on production yet (SSH
down). Not browser-checked.
Next action: when SSH is back, rehearse 0342 and 0343, check the stale rows
and a source-refresh scope on production, then commit each change
separately with user approval.

#### PLAN-004 resolver finding lifecycle follow-up (measured 2026-10-26)

At the end of each client-resolver run, reconcile `client_unattached_group`,
`unnamed_source_group`, and `client_link_collision` findings when their source
group is assigned, inactive, or gone. Also close a collision when the group no
longer matches two or more clients. Record a reason for every closure. The
read-only production check found 3 stale `client_unattached_group` findings
among 8 active (one group is now attached to UTA and two refer to inactive
source observations); 5 still describe active unattached groups. No active
client-link collision was found. The open `unnamed_source_group` finding still
describes an active unnamed group. See PLAN-004 in the registry.

Generic entity-candidate withdrawal is a distinct lifecycle and is tracked in
ready PLAN-021; do not treat it as covered by this client-resolver follow-up.

### Step F — client domains (ADR-0042, accepted 2026-10-23)

Open point settled: claims are one source record's assertion (observation
and source field mapping are required), so learned domains are computed when
read (`apps/core/client_domains.py`) and nothing stores them; operator edits
are `client.domains` set decisions through `set_attribute_decision`
(add/remove members; restore drops the edit). Migration 0343 registers the
definition and `evaluator_config` row `client_domains` (min 2 computers;
ignored workgroup/local/...). Client page "Domains": learned (with computer
count), added, removed, with Add/Remove/Restore and a reason (permission
`write_decisions`). Context key is `domain_names` (`client_domains` is taken
by the status panels). Not yet on Inventory › Clients.
Validation: Django check clean; Operations 4 failures (pre-existing);
`test_client_domains.py`. Not rehearsed (SSH down); not browser-checked.
ADR-0043 accepted; build waits for production measurements.
Rehearsed 2026-10-25 (rolled back): 0342 mapped MDA to Prompt and created a
provisional client; 0343 registered the definition; checks passed. Preview:
62 clients, 127 learned domains (NetBIOS short names appear beside DNS ones).
Committed 2026-10-25, not pushed: c40e13c stale cleanup, 8a33233 job replay,
de31c6f move to new client, be55a72 promotion (0342), 00801d2 undo merge,
49ce467 domains (0343). Local master also carries another session's
unpushed eb4f7e1; user asked to review it before any push.
Pushed 2026-10-25 20:26 UTC as 0c812db (with reviewed eb4f7e1); 0342 and
0343 applied; Operations healthy 20:27.

### Step G — Source records identifies records (interim for ADR-0044)

Migration 0344 appends `source_layout` and `source_url` to the safe metadata
view. Source records shows the reported name, the source group (mapped name
or id), the Hudu layout, Open in Hudu / Ninja (Ninja device dashboard
pattern, inlined; user: no shared helper for now), View evidence for admins,
the record's Computer issue count and how many name this record, and why an
unlinked record is unlinked (archived, stale link, group not mapped,
proposed as an asset, not matched). Rehearsed read-only/rolled back on
production: 5,215 unlinked rows, 5,192 with a layout; issue counts per
record work. ADR-0044 (proposed) documents the taxonomy and phased plan;
Hudu "Credit Card" (9 records) needs a decision first.
Validation: Django check clean; Operations 4 failures (pre-existing);
`test_source_records_identification.py`. Not browser-checked.
Layout and why-unlinked are server-side filters; the table is marked
paginated. Committed as a3fb9df. Computers, software title and publisher
pages have the same per-page filter problem (not changed).

### Step H — Credit Card restricted (ADR-0044 phase 1)

User decision 2026-10-25: keep collecting, never show details. Migration 0345
seeds `evaluator_config` `restricted_source_layouts` = ["Credit Card"] and
masks name, hostname, serial, VM UUID and link in the safe metadata view
(appends `restricted`). Source records says "Details not shown". Rehearsed on
production and rolled back: 9 restricted rows with 0 names/links; the other
37,179 rows unchanged. Validation: Django check, makemigrations --check,
`test_source_records_identification.py`, `test_table_controls.py`.
Shipped `fcb488a`. Its per-row check triggered ~0.9 s of JIT per query;
`ee180e1` (0346) joins the setting once: ~0.25-0.36 s on production, masking
unchanged.
Next action: ADR-0044 phase 2 (mapping table).

### Step I — Client renamed at its sources

User rule 2026-10-26 (Prompt → MDA): a source group id that reports a new
name is a rename. All of a client's mapped groups agree on the new name →
the resolver renames the client (recorded, undoable, old name kept as an
alias, slug unchanged). Groups disagree → the client's name finding says
which sources were renamed and which still use the old name, with "Rename
client" on the client page. Evidence: `entity_observation_history` org names
per id (Prompt: Ninja 10-12, Hudu 10-23, SentinelOne/LogMeIn 10-25).
Scope: migration 0347 `rename_client_v1`; resolver `_check_name_drift`;
client page rename form and undo; finding context. Only automatic/review
mappings count, so Undo (rename back + confirm those mappings) sticks.
Built: migration 0347, resolver, client page Rename/Undo, finding text,
ADR-0040 decision 7. Rehearsed on production (rolled back): rename works
(alias "Prompt" kept, slug unchanged, change recorded). Preview: auto-rename
Prompt → MDA and "Park Bookeeping" → "Park Bookkeeping"; County partial
(LogMeIn "County\CNY"). Validation: Django check, makemigrations --check,
Operations 4 / ingest 5 known failures only, new tests pass. Not
browser-checked.
Next action: user approves commit and push (0347 adds a function).

### Step J — Software › Installations (PLAN-012 reader)

One row per installation on a current Computer (`v_device` + shared
selector), with the decision that applies (`shared.software_coverage`,
ADR-0039). Server-side filters: client, search, decision, product,
publisher; count, page and CSV share them. CSV streams. Product links on
client Software and Software › Clients open it filtered. Not stored
per-installation decisions: PLAN-012/017 need measurements before any
projection. Production timings (app role, read-only): page 2-2.5 s,
decision filter about 7.7 s, CSV one client 3.3 s, all 19 s.
Publisher, product, and Computer filters accept multiple exact selections,
with searchable options scoped to current Computer installations; count, page,
and CSV retain selected values through the shared server-side filters. The
table also shows the install path, already included in CSV. No schema or public
route changes. Validation: Python compilation and whitespace check; browser
interaction not checked.
Next action: user approves commit and push; later retire
`org_software_devices` (TODO).

## Client mapping workflow — finish the single-inbox move

Steps 1-5 complete (browser check pending); retirement deferred (user approved 2026-10-22). Goal: finish the 2026-10-07 "Issues is the
single inbox" change for client mapping. Issues is the queue; Inventory ›
Clients shows a "New / discovered clients" view of the same open items; a
client's page decides its source mappings in place. Client mappings stays (not
retired) until Source records can hold the full list; Source records changes
are deferred until the rest is complete.
Steps: (1) fix links to non-existent Issues types (`type=client_mapping` from
the candidate page and `/clients/candidates/`; `type=computer_identity` from
`/admin/entity-candidates/`); (2) mapping decision inline on the client page
with return-to; (3) Issues links for a known client open the client page
decision; (4) New/discovered section on Inventory › Clients, counts matching
Issues; (5) "needs review" measured: 339 of 376 mappings are review (the
unconfirmed default), actionable name differences are already
`client_name_conflict` Issues, so no new Issues — the client page shows the
state. Production 2026-10-22: 28 open candidates = 30 source groups = 30 open
`client_unattached_group` admin findings. No schema change.

Correction: production Issue groups come from `finding_types.issue_group`
("Client mapping" -> `client_mapping`, "Computer identity" ->
`computer_identity`), so those links were valid; the broken ones were
`client_name_differences` (Inventory › Clients, client workspace) and
`computer_identity_matching` (client page).
Checkpoint: steps 1-5 implemented locally. Validation: Django check,
templates compile, Operations suite passes except the 4 failures also on
clean HEAD; new `test_client_mapping_workflow.py`; table-controls guard now
lists `software_tech_checklist.html` (paginated, no table, from 0629674).
Lint/format unchanged per file. Not validated in a browser. Next action:
retire Client mappings after Source records holds the full list (steps 1-5
committed and pushed with user approval).

## R-U-ON process monitors shown on their computers

Active (user approved 2026-10-22, including a deploying migration; the user
chose this lighter design over separate monitor records). Goal: R-U-ON
ProcessOn agents (process monitors; 4 in production, each beside a ServerOn
agent for the same machine) appear on that Computer's R-U-ON source record
instead of being dropped.
Scope: `ingest/connectors/ruon.py`, migration 0338 (adds `process_monitors` to
`v_entity_observation_admin_metadata`), `device_detail` view/template, tests.
Decisions: a monitor pairs only when exactly one ServerOn agent has the same
group, name (case-insensitive) and non-empty private IP; the paired list goes
in the machine record's `canonical_data.process_monitors` (agent id, name,
on/off) with the full agent rows in its raw data. Only machines with monitors
gain the key, so other records' content and history are unchanged; a monitor
flipping on/off now changes its machine record's history. Unpaired monitors
are only counted in the run log. No new record type, shared ingest change or
ADR: monitors are not records of their own. The view column is cast only from
a JSON array, so a malformed value cannot break readers.

Checkpoint: implemented; committed and pushed with user approval (deploys
migration 0338). Validation: `test_ruon_connector.py` 12 pass (pairing rules, monitors listed on the machine, other machines
unchanged, unpaired counted, other types still skipped);
`test_ruon_process_monitors.py` 3 pass (view keeps 0334's columns and adds
only the guarded list with grants/revokes; every unpacking of the extended
Source records rows); `manage.py check` clean; `makemigrations --check` no
changes; ruff clean on changed files (views.py unchanged at 86). Not
validated: migration 0338 on PostgreSQL (no local database), the real R-U-ON
markup for ProcessOn rows, and the deployed page. Pre-existing failures, not
from this work: the domain-mapping ratchet (25 unlisted names from other work;
this session's `COPIED_FIELDS` is now listed), `test_table_controls`
(`software_tech_checklist.html`), `test_e5_generic_admin`
(`ConditionPolicyActivationForm` missing).
Next action: after deploy, open a Computer with an R-U-ON process monitor and
check its Source records row (the monitor appears after the next R-U-ON run).

## Requirements page — edit baselines in the app

Active. Goal: Admin → Config → Requirements edits requirement baselines the way
a client's Configuration page edits its exceptions, replacing the dead
"edit via Django admin" pointer (the models were never registered there).
Scope: `requirement_baselines.py` (new, pure row building and item matching),
`requirement_profiles_list` view (POST actions), `requirement_profiles.html`,
tests. No schema, evaluator, or client-page change.
Decisions: two baselines exist and both are edited here — the global
requirements (client-less `coverage_requirements`, used by clients with no
profile) and each profile's items. "Default for new clients"
(`is_tenant_default`) only preselects a profile when a client is accepted; the
page says so. Per service: Required / Not required. New items take the
service's default thresholds (migration 0312 precedent). Removing a global
requirement disables the row (reversible); a profile item has no enabled flag
and is deleted (history trigger records it). New profiles may start empty, from
the global requirements, or from another profile. A profile assigned to any
client (including deleted ones; FK is PROTECT) cannot be deleted.
Baseline items are offered for "All eligible devices" only: the evaluator's
`resolve_tier` uses a role-scoped baseline list *instead of* the all-devices
list (client overrides add on top), so a servers-only baseline item would
silently drop every other requirement for servers. Existing scoped items are
shown and removable. The replace-vs-add inconsistency is recorded in `TODO.md`.

Checkpoint: implemented; committed and pushed with user approval (deploys; no
migrations). Validation: `test_requirement_baselines.py`
6 pass (row building, legacy matching, default thresholds, audit/guard
source checks, table render) with related table/jobs/client-config tests (27
total); `manage.py check` clean; ruff clean on new files and on the new
`views.py` code (file total unchanged at the 86 pre-existing findings). Not
validated: the POST actions against PostgreSQL (no local database) and the
page in a browser. Next action: try create/require/remove/delete on the
deployed page.

## Software review — publisher status and why titles stay open

Active. Goal: the Software review publisher row shows the publisher's current
decision, and under an approved publisher each still-open title says why it
was not covered, with an operator override.
Scope: `software_review.py` (new `attach_publisher_status`), the queue view,
`software_decisions.html`, `_software_review_row.html`,
`_software_review_publisher_actions.html`. No schema, reconcile, or decision
semantics change. Decisions: status comes from stored publisher-level
decisions (global first, narrower scopes counted); hold reasons measured from
live installs — concern signals (by design D9), installs whose publisher text
differs from the approved one, installs with no publisher; none of these means
the prompt is waiting on the next reconcile. Override = "Approve N open
titles" through the existing bulk endpoint (title-level global approvals);
Investigate/Reject publisher stay available to change the decision. Matching
publisher variants automatically was declined (no alias table); alternative
design is open in `TODO.md`. Production measure 2026-10-22: 196 of 15,240 open
prompts sit under a globally approved publisher — 92 concern, 91 name
variant, 13 blank publisher.

Checkpoint: implemented. Validation: `manage.py check`
clean; ruff check clean on changed Python (both files' format drift predates
this change); `test_software_review.py` + review-context tests 17 pass (2 new);
templates load and render with sample groups; hold query read-only against
production: index scan, 14 ms for 2 titles. Not validated: the ORM decision
lookup and full page render against PostgreSQL. Committed and pushed with user
approval (deploys; no migrations). Next action: check the deployed review page.

## Software title coverage — prompts describe the uncovered installs

Complete (deployment check pending). Goal: a decision covers an install when that install's own effective
decision (title, then publisher; device, client, global) approves it, and an
undecided-software prompt (`whitelist_suggestion`, `rare_recent`) describes
only the installs no decision covers. Today one uncovered install opens a
title-wide prompt reported with whole-fleet counts (e.g. Microsoft Store: 1 of
3,917 installs has a blank publisher). Per-install exposure
(`v_device_software_exposure`) is already correct; the defect is the
title-level facts in `ingest/software_reconcile.py` and every reader of them.
Scope: shared per-install coverage SQL in `shared/`; reconcile facts and
prompt details (uncovered counts, publishers, first seen; rare decided on the
uncovered count; concern-under-publisher-approval keeps D9); readers updated
consistently: Issues page (context line, sort), Software review (counts,
grouping publisher, rare device targets, rare-limit preview), human labels,
home dashboard software card, software overview. Strictness is unchanged: an
install with a blank or different publisher string never inherits a publisher
approval. Publisher aliases are backlogged (`TODO.md`), not in scope.
Decisions to promote: ADR for the coverage rule.

Checkpoint: prompt fix implemented locally (ADR-0039 Proposed). Done:
`shared/software_coverage.py`; reconcile facts/prompts; Issues context and
sort; Software review rows, grouping, rare targets, rare-limit preview, row
note ("Already decided on N of M"); human labels; home card counts the
prompts. Validation: ingest reconcile tests (4 new) and Operations suite pass
except failures that also fail on clean HEAD (ingest operator_job_queue
test; 4 condition-policy tests; domain-mapping guard, where my two pushed
constants are now exempted). Production probe: per-title coverage live
takes 4.5 s; 126 titles partly decided. Open decision for the user: the
software overview's title status needs a persisted per-title coverage
table written by the reconcile (migration) or must derive from the open
findings. Measured: every title with uncovered installs has an open prompt
(15,149; 0 missed; 92 extra are rare-with-concern or awaiting closure), so
the overview can derive from the findings without a table (user: "ok for
now"). Committed and pushed with user approval. Next action: verify the next
reconcile rewrites prompts (e.g. Microsoft Store).
Overview (`/software/`, Products tab) now reads the same per-title status
(`software_review.TITLE_STATUS*`: rejected finding > open prompt >
investigate decision > decided), no table. Production timing: counts 0.74 s
warm, filter 0.32 s (old wrong query 83 ms); index declined as not worth a
migration. Committed and pushed with user approval.

## Software review — filter by publisher status

Complete (browser check pending). Goal: filter Software review by the publisher's publisher-wide
decision (Approved / Investigating / Rejected / No publisher-wide decision).
Scope: `software_review.filter_by_publisher_status` (reuses
`publisher_decisions`, the same source as the publisher row), the queue view
(filter applied after grouping, before sorting, paging and CSV), and the
filter bar in `software_decisions.html`. Client or computer decisions are not
publisher-wide and count as "none". The Issues-page variant was declined as
too heavy. Revised per user: Publisher status is its own column in both views
(`stamp_publisher_status` on every group before sort/filter/page, sortable via
`GROUP_COLUMNS`/`SORT_COLUMNS`, in the CSV); decision detail moved out of the
Publisher cell; filters live in a header row that submits the server form
(`_software_review_filter_cell.html`); sort headers are plain text with
`data-sort-href` so labels are selectable. Merge review: each Computer's source
records sit in their own bordered panel ("Computer N of M").
Microsoft finding (production, 2026-10-22): 23 open non-approved titles under
the approved "Microsoft Corporation" each have 1-11 installs with a blank,
Russian-localised, or unresolved publisher string; coverage requires every
install to match, so they stay open. Rule change awaits a user decision.

Checkpoint: implemented locally. Validation: 53 targeted tests pass (new
publisher-status column, sort, and template tests); templates compile; JS
syntax checks; Ruff total and format drift unchanged;
`manage.py check` clean. Not validated: against production data or in a
browser. Committed and pushed with user approval. Next action: redesign title
coverage (see Microsoft finding) as its own blueprint.

Follow-up in the same pending commit (user feedback on Client mappings):
"Likely client" moved off the list onto the candidate page, counted from all
live records (`_candidate_client_overlap`) instead of the 25-device sample,
and preselected under Map to existing; header text is selectable again (a
text selection does not trigger a sort). Production 2026-10-22 17:24 UTC:
0337 applied 16:54, but no source has collected since 14:36, so the resolver
has not run on the new code and "Rise NYC" is still open.

## Sortable and filterable tables

Complete (browser check pending). Goal: every table sorts and filters from its column headers.
Scope: shared script/CSS in `templates/base.html` applies to every table with
a header row unless marked `data-no-sort`; paginated tables are marked
`data-server-table` and skipped (browser-side work would only see one page);
tables with rowspans or interleaved group rows are skipped automatically;
pages with their own sort scripts (`home.html`, `org_index.html`) opt out.
Existing `data-sortable` remains a forced opt-in. Decisions: sort uses
`data-sort-value` when present, else the cell's first line; ISO dates compare
as text, numbers numerically, blanks last (fixes dates collapsing to their
year). Filters are case-insensitive substring per column. Deferred: server-side
header sort/filter for paginated lists (`TODO.md`).

Checkpoint: implemented locally. Validation: Node syntax check of the
script; comparison logic tested in Node (ISO dates, thousands separators,
"5 open", blanks last, natural text); every template compiles;
`test_table_controls.py` plus related tests, 110 pass. Not validated: DOM
behaviour in a browser (npm registry blocked by TLS inspection, so no jsdom).
`software_decisions.html` also carries another agent's uncommitted edits;
only the two `data-server-table` lines were committed there. Committed
and pushed with user approval. Next action: check client-mappings in a
browser after deploy, then move this section out.

## Client mappings — unattached evidence columns

Complete (deployment check pending). Goal: replace the misleading "Records" column (`seen_count`, which
counts resolver passes, not records) on Client mappings › unattached with live
evidence an operator can act on without opening the candidate.

Scope: `client_mappings` view and template; candidate detail header drops the
"seen N×" figure. No schema or resolver change; `seen_count` stays stored.
Decisions: per source group, show whether the source still reports it
(historical `source_refs` remain visible, marked "no longer reported");
"Source records" counts active records in still-reported groups (matched on
`platform_group_id`, the resolver's own attachment key, scoped by source), with
"N linked" for those already matched to a Computer — production showed records
in unattached groups are mostly unlinked, so a Computer count read ~0; "Likely
client" is the client owning most linked Computers (evidence), else a clearly
labelled similar-name suggestion. Reads use
`v_entity_observation_admin_metadata` (raw observation table is revoked).
Candidates are keyed by name, so a group renamed at the source sits under two
candidates; the candidate with the newest `source_refs` entry owns the group
and older names show "→ new name" with no live evidence. Candidate last-seen
is one resolver-stamped date for the whole name, so per-group state is shown
on the source badges.

Extended (user-approved): ADR-0040 (Proposed) — the resolver moves a renamed
unattached group off other open candidates and closes an emptied one as
`renamed` (`_release_renamed_group`); migration 0337 adds the choice (no SQL).
On deploy this also closes existing stale candidates such as "Rise NYC" on the
next resolver pass. Issues queue: `client_name_conflict` rows now name their
own source and name instead of the same peer list on every row. Remaining
follow-ups are in `TODO.md`.

Checkpoint: implemented locally. Validation: `manage.py check` and
`makemigrations --check` clean; `sqlmigrate 0337` is a no-op; Ruff repo total
unchanged (116); views.py format drift unchanged (58 hunks); operations tests
(evidence, coverage, findings queue) 88 pass; ingest rename and
drift-contract tests 6 pass. Production read-only check (2026-10-22, as
`operations_app`, rolled back): both evidence queries run under the app role;
Rise NYC's 3 groups resolve as renamed to Rize NYC; 464 active records sit in
open candidates' groups, 79 linked. Not validated: the resolver UPDATE path
against PostgreSQL; `test_resolver_maintenance.py` cannot load without DB
settings. Committed and pushed with user approval (deploys and applies
0337). Next action: verify the deployed page and that the resolver closes
"Rise NYC" as renamed, then move this section out of the active blueprint.

## Client setup visibility and Inventory › Clients coverage

Complete (deployment check pending). Goal: make unmapped source clients (open client candidates) and
per-client source coverage visible, and return operators to where they started
after resolving a candidate or mapping decision.

Scope: `inventory_clients` view/template (Computers, coverage by source, fixed
name-difference count from `findings`, sortable, "N new" and Client mappings
links); dashboard Clients card "N new" link; candidate detail and actions plus
`client_mapping_decide` honour a same-host `next` (Referer fallback). No schema
or resolver changes. Decisions: undecided ("review") mappings are not counted
anywhere (ADR-0025: a decision only changes name-difference reporting); the
proposed "Mapping issues" column is omitted (0 open). Production facts
(2026-10-22, read-only): 33 open candidates, 124 open `client_name_conflict`
in `findings`, 0 in `admin_findings`.

Checkpoint: implemented locally. Validation: Ruff unchanged (84 existing),
format clean, `manage.py check` clean, templates compile, 91 targeted tests
pass (new `test_return_to.py`). Not validated: page rendering against a
database (no local Docker). Reused the existing `_safe_next` rather than a new
redirect helper. Next action: check the deployed pages; then move this
section out of the active blueprint.

## PLAN-015 — One-time source-record identity reconciliation

Active. Build the read-only preview only: counterfactually match every current,
attached identity-signal record using today's policies while excluding its own
evidence. Do not run it against production or implement reattachment, merges,
or derived refresh. The tool must report proposed destinations, rules,
candidate/blocker traces, and a digest without writing database state.

Scope: `ingest/identity/matching.py`, a new ingest operator module, and
focused tests. PLAN-004 retains ongoing identifier-change rechecks; PLAN-012
and PLAN-014 retain their existing scopes. Existing uncommitted work belongs
to other tasks and must be preserved.

Current checkpoint: local implementation and focused validation passed (15
PostgreSQL tests, compile, Ruff, registry, and whitespace checks). An authorized
production read-only hostname/client footprint query found 131 one-peer records
and 40 multi-peer records. Its guard-aware follow-up reduced the one-peer set
to 110 while retaining 40 multi-peer review cases; neither query made changes.
All 40 ambiguous records are covered by an open `duplicate_device_records` or
`identity_conflict` Finding (possibly shared across records). Next action:
review the 110 candidates before any reattachment proposal.

# PLAN-004 corrective repair — restricted observation reads

## Goal and scope

Restore the affected Computer UI paths without restoring the Operations
application's direct access to restricted observation payloads. Production
tracebacks on 2026-10-21 confirm that global search and Computer detail read
`entity_observation_current` directly after migration 0117 revoked that
access. The History tab and Hudu-archive finding action contain the same
unsafe read pattern.

Extend the existing reviewed, tenant-filtered, security-barrier metadata
projection with only the scalar identifiers required by those callers. Move
the four user-facing reads to it and add focused regression coverage. Do not
grant the application role the raw table or payload JSON. This repair is
independent of PLAN-012's population design and must preserve PLAN-013's
authentication work.

## Status, validation, and checkpoint

Implementation authorized 2026-10-21. Migration 0334 extends
`v_entity_observation_admin_metadata`; Computer name provenance, global
search, History, and Hudu-archive eligibility now use it. The raw table
remains denied to runtime readers; the two remaining references in `views.py`
are intentional guarded updates.

`ruff check` passed for the migration and focused tests; Python compilation,
registry validation, and `git diff --check` passed. Django/pytest are absent
from the workstation interpreter. Docker Compose could not run the focused
tests because its Operations container requires the unavailable local database
password; it created an empty local Compose network and volume only. No
production schema or application state has changed. Commit and deployment
push were approved on 2026-10-21. Next action: commit this repair, push it,
then verify the deployed endpoints and migration under the runtime role.

Follow-up authorized 2026-10-21: the Computer detail Source records query can
multiply a record when more than one presence row matches its source/type, and
the pending-cleanup banner falsely says there are no current records. Keep the
existing record/lifecycle architecture: select at most one presence row for
display and change the banner to say the Computer is marked for review while
directing the operator to its displayed source records. No lifecycle policy,
schema, or source data changes are authorized.

# PLAN-013 — Operations sign-in page

## Goal

Let any active Operations user sign in without Django admin staff status.
Permissions continue to come from groups (`viewer`, `operator`, `admin`).

## Scope

- `/login/`, `/logout/` (POST), and `/account/password/` change-password
  pages using Django's built-in auth views; no new dependency, model,
  migration, or permission change.
- `LOGIN_URL` points at `/login/`; header sign-in/sign-out links use the new
  pages. `/admin/login/` remains available for staff.
- Out of scope: SSO (Entra/OIDC), an Operations Users page, and the existing
  `is_staff` checks that gate editing on Finding types, Software policy,
  client mappings, Home system links, and Sources.

## Affected files

`config/settings/base.py`, `config/urls.py`, `templates/base.html`,
`templates/registration/login.html`,
`templates/registration/password_change_form.html`,
`templates/registration/password_change_done.html`,
`apps/core/tests/test_login.py`.

## Decisions

- Built-in `LoginView`/`LogoutView`/`PasswordChangeView`: the views run after
  `TenantMiddleware`, so the user lookup happens under the tenant GUC and RLS.
- Logout becomes a POST form. Django 5 rejects GET logout, so the previous
  header link to `admin:logout` returned 405.
- Staff status stays the gate for `/admin/` and for the existing `is_staff`
  edit checks; changing those is a separate authorization decision.

## Status

Completed and validated locally and in the deployed browser on 2026-10-26; implementation was committed and pushed on user approval (2026-10-21).

## Validation

- `pytest apps/core/tests/test_login.py`: 6 passed (sign-in render, POST-only
  sign-out, password change requires sign-in, header links, templates).
- Full `pytest apps`: 439 passed, 133 skipped, 4 failed; the same 4
  conditions/generic-admin failures occur on clean HEAD 3091a47.
- `manage.py check` clean; ruff check/format clean on new files. Pre-existing
  format drift in `config/urls.py` and `config/settings/base.py` left as is.
- User confirmed deployed browser sign-in, sign-out, password-change form
  access/fields, and post-logout authentication guard all passed. The password
  itself was not changed.

## Checkpoint

Completed. The deployed Operations container is healthy after migration
0352/0353 on deployment `b1d3772`. Browser verification confirmed sign-in,
authenticated password-change form access, sign-out, and the post-logout
password-page redirect to login. No password was changed. Follow-ups
(group-based edit checks, SSO decision, Users page) are in `operations/TODO.md`.

## Next action

No further action. Any future password-change transaction should be tested
only when a real account password change is intended.
## PLAN-016 — Admin read-only SQL explorer

Active. Add an Admin Data query page that uses transaction-level read-only
execution, forces tenant scope, and includes the guard-aware 110-candidate
identity query. No mutations, exports, deployment, or schema changes.

Current checkpoint: plan defined; inspect existing Admin Data routing and tests,
then implement focused UI and request coverage.

## PLAN-004 — Computer detail source-record regression

Active corrective repair. Production Computer detail requests fail because the
source-record query supplies three parameters for two placeholders. Scope is a
one-line parameter correction and targeted validation only; no deployment is
authorized. Current checkpoint: corrected the local query; 60 focused tests,
Python compilation, plan-registry validation, and whitespace checks passed.
Next action: request separate commit and deployment approval.

## Inventory navigation

Active focused UI change. Inventory no longer loads Client inventory on click;
it expands to explicit Clients and Computers links. Scope is the shared base
template only. Next action: run template/navigation regression checks.

## Ninja enrichment Job visibility

Active focused Jobs-catalog correction. Ninja enrichment remains a supporting
process of the one Ninja source, but it must be visible in Jobs with its own
schedule, status, and Run action. It is not a second configured source.
Scope: expose `ninja-enrichment` in the source-data Jobs group and describe
its locations, policies and patching scope, device exemptions, health, custom
fields, troubleshooting signals, and derived-state refresh. Next action: run
focused registry/UI checks; commit and deployment require separate approval.
## PLAN-012 — Search and Client inventory source evidence

Active (user authorized 2026-10-22). Extend the global search results with a
separate source-record population, retaining canonical Computers as a distinct
result type. In Client inventory, render each coverage source on its own line
and expose the current source-side client name(s) in parentheses. No matching,
attachment, schema, or source-data behavior changes. Validate focused
structural tests, Django check, lint, and whitespace. Current checkpoint:
implementation complete locally. Focused read and client-mapping tests (14),
template loading, Django checks, Python compilation, correctness/import lint,
and scoped whitespace validation pass. Full-file lint retains 85 known
pre-existing complexity/style findings in `views.py`. Next action: review the
source-record result copy and source-name presentation, then obtain separate
commit and push authorization if approved.

## PLAN-003 — Central work queue and finding state

**Status:** Active, design and implementation-readiness work. No runtime,
schema/data, commit or deployment action has started. Preserve the unrelated
dirty worktree.
**Goal/scope:** one grouped Issues queue, one authoritative entity/admin finding
store and one Covers/Requires contract, preserving history, subject distinctions,
permissions and tenant isolation. Candidate storage stays separate; coordinate
identity/applicability/shared-read work with PLAN-004/014/021/012.

**Current contract:** [PLAN-003 current design](docs/plans/PLAN-003-current-design.md).
Historical requirements: [checklist](docs/plans/PLAN-003-issues-page-design.md).
Detailed 71-type review, primary conversations/commits and aggregate production
evidence: [review report](docs/plans/PLAN-003-review-proposal.md). Those records
retain superseded proposals; use the current contract for implementation design.

**Checkpoint:** operator directions reconciled, including root-issue boundaries,
existing ADR-0040/0043 consolidation, software administrative versus Computer
work, recognized-OS applicability, Hudu lifecycle versus integration work,
page/subgroup selection, same-type bulk actions with mixed Pause/Resume, and
lightweight partial-eligibility handling. Latest accepted filter rule: OS and
Computer type apply to Computer-specific issues, not approval groups; the
partial software population proposal is withdrawn. No general row expansion.
Readiness presentation controls are approved for removal; older Readiness
controls do not remain in the implementation contract. Covered evidence and
execution guards remain.

**Verified limits:** tenant-1 production checks were aggregate, repeatable-read
and read-only; no evaluator/refresh/source action ran. No valid installation
task established among the 87 measured non-cleanup no-agent cases; two OS links
need separate consistency investigation. 140 Hudu assets map to 102 Hudu-only
Computers, each already owning a documentation_only lifecycle finding. An
integration-gap signal replaces zero of those cases without causal evidence.
Deferred consistency/retained-row cleanup is in operations/TODO.md, not authorized
implementation scope. No browser, application or migration acceptance claimed.

**Resolved 2026-10-29: count independent corrective actions (one per source group for client mapping); no "pending" label/count, freshness kept in details. Approved R0–R4 order is in the current design. Original item (2026-10-28):** Local dev shows the dashboard's 152
critical mapping conflicts combine 75 `unmatched_source_group` findings and
77 `client_unattached_group` admin findings; 75 of the latter overlap the same
source groups. Issues reports 75 unresolved and 75 pending for those same
75 entity findings; `pending` reflects `no_current_assessment`, not a separate
set of work. Resolve this once in the current design: define one source-group
issue identity/corrective-action count across the dashboard and Issues, and
make the status label/action meaning explicit. Keep stale resolver-row cleanup
under PLAN-004 as a dependency, not as another PLAN-003 issue. See the
[current design](docs/plans/PLAN-003-current-design.md#resolution-item-client-mapping-counts-and-status).

### R1 — additive expansion and dormant tenant guard (released 0.131.0, `302a2f2`)

Approved joint order step R1 (current design). Baseline `1176034`; R0 record:
[R0 baseline](docs/records/PLAN-003-004-R0-baseline-2026-10-29.md). Everything is
additive and unused: no runtime code calls it, old readers/writers are unchanged.

- **`0362_findings_tenant_id_unique`** (non-atomic): `CREATE UNIQUE INDEX
  CONCURRENTLY uq_findings_tenant_id ON findings (tenant_id, id)` so composite
  FKs can reference findings without blocking writers.
- **`0363_common_findings_expansion`** (raw SQL, no Django model state change):
  - `findings`: `subject_ref jsonb NOT NULL DEFAULT '{}'`, `condition_namespace`
    (`entity`/`admin`, default `entity`), nullable `condition_identity` and
    `episode_key` with a partial unique active-episode index. `subject_id` stays
    NOT NULL and active-key uniqueness is unchanged until M2–M4.
  - `finding_types.allowed_subject_kinds text[] NULL` (unseeded, not enforced).
  - Empty tables: tenant-scoped `finding_legacy_refs` and `finding_relationships`
    (composite tenant FKs, forced RLS, runtime roles SELECT only); global
    `finding_action_registry`, `finding_relationship_rules` and
    `finding_relationship_rule_actions` (runtime roles SELECT only). Registered in
    `change_history_registry`; configuration tables are `covered`.
  - Composite `(tenant_id, finding_id)` FKs on `finding_state` and
    `source_action_requests`, added `NOT VALID` (new rows enforced; validation
    is an M2 preflight).
  - Dormant tenant guard: `tenant_guard_key`, `acquire_tenant_guard(tenant,
    'shared'|'exclusive')` (session-tenant check, refuses shared→exclusive
    upgrade), `tenant_guard_mode` and `assert_tenant_guard`, using a namespace
    disjoint from Jobs keys. EXECUTE only for runtime roles that will need it.
- **Tests:** a PostgreSQL integration test in the repo convention (testcontainers)
  covering legacy inserts without new columns, composite FK/RLS/DML denial, and
  guard modes across two sessions (shared/shared overlap, exclusive blocks,
  upgrade refused, wrong tenant refused). Then the fresh-database stack: migrate
  to head, `makemigrations --check`, `manage.py check`, sign-in and pages.
- **Out of R1:** data backfill, admin-row copy, triggers/projector, protected
  mutation procedures, contract version (all M2–M4), queue/UI changes (R3).
- **Release:** commit needs approval; push deploys and auto-applies both
  migrations, so it needs separate approval.
- **Checkpoint (2026-10-29):** released in 0.131.0 (`302a2f2`) and verified in production; [deployment record](docs/records/PLAN-003-R1-deployment-2026-10-29.md) includes an ~11-minute startup stall. Files:
  `apps/core/migrations/0362_findings_tenant_id_unique.py`,
  `0363_common_findings_expansion.py`, `apps/core/tests/test_migration_0363_postgres.py`.
  `0363` refuses to run if a failed concurrent build left the 0362 index invalid.
  The action registry and relationship rules stay unseeded until M3.
- **Validation:** `test_migration_0363_postgres.py` (9) and the existing 0306
  change-history tests pass on PostgreSQL 16 (19 total). Throwaway fresh-database
  stack: SQL to `118`, Django to `0363`, `makemigrations --check` and
  `manage.py check` clean; sign-in and main pages 200; rollback to `0361` and
  reapply succeed; ORM create/update/delete as `operations_app` unchanged.
  Ruff clean on the new files. Not run: full test suite, production-size timing
  of the `findings` ALTER (brief exclusive lock while columns are added).

### R2 — M2–M4 coordinated cutover (released 0.132.3, 2026-10-29)

Goal: one findings ledger with protected, tenant-guarded writers and one
relationship mechanism, shipped as a single release in a drained maintenance
window. Readers keep today's populations (entity-only and admin-only adapters);
the unified queue is R3. Contract version 4 is published only after exact-set
assertions pass. Source: technical design §§3–5 and §7; consumer ledger.

**Branch rule:** all R2 work lives on branch `plan003-r2`. Any push of `master`
deploys and auto-migrates, so no R2 migration may land on `master` until the
whole artifact is approved for release.

| WP | Scope | Main files |
| --- | --- | --- |
| 1 Preflight | Read-only SQL: admin/entity key collisions per namespace, subject shapes per type, assessments/participants by `row_kind`, `finding_state`/`source_action_requests` tenant agreement (validates the R1 NOT VALID FKs), grants by role on graph tables | new `ops` preflight SQL + test |
| 2 M2 conversion | Allow `subject_id` NULL only for validated structured subjects; normalize admin `subject_ref` per §3 table; copy every admin row (field map per §3) with `condition_namespace='admin'`, legacy refs, preserved IDs/versions/history; backfill `condition_identity` from agreeing assessments or the frozen hash; active uniqueness becomes (tenant, namespace, key); validate the R1 FKs | migration + frozen-hash helper + tests |
| 3 M3 protected graph | `SECURITY DEFINER` mutation functions for findings, assessments, participants, type/rule config and relationships (owner: no-login `NOBYPASSRLS` role); each asserts the exclusive tenant guard and caller contract; triggers assert, never acquire; revoke direct runtime DML; namespace-aware `compute/refresh/touch_finding_state`; relationship projector with cycle rejection; seed action registry and rules from `finding_types.covered_by` and exact Job dependency closures | migration(s) + tests |
| 4 Writers | Convert every producer and action path in the ledger (ingest: conditions, evaluator, cmdb/patch/platform/windows-servicing/software-reconcile findings, identity findings/resolver/client resolver, requirement state, source actions, notifications; Operations: `conditions/live.py`, finding actions/views handlers, finding types admin) to take the guard at the outer transaction and call the protected functions | ingest + Operations modules |
| 5 Readers | Entity-only adapter (`condition_namespace='entity'`) for every `Finding.objects` call site; `admin_findings` becomes a read-only compatibility view over admin rows; `v_issue_findings` and `v_condition_assessment_current` rebuilt on one ledger with unchanged populations | `models.py`, views, adapters, migration |
| 6 M4 + admission | Exact-set assertions (both adapters, home/domain counters, queue rows, CSV, disjointness and union conservation) then `finding_contract_version()` = 4; Operations entrypoint, ingest main and Jobs worker refuse to start or write on another version | migration, `entrypoint.sh`, `ingest/main.py`, `jobs_worker.py` |
| 7 Rehearsal + window | PostgreSQL role/trigger/concurrency tests; full rehearsal on an isolated copy of production (needs authorization) with timings, rollback and conservation; written drain/abort procedure (stop ingest/Jobs/notifier/source actions before migrating) | tests, runbook, record |

Order: WP1 → WP2 → WP3 (each with tests) → WP4/WP5 in parallel → WP6 → WP7.

**Checkpoint:** WP1 done on `plan003-r2` (`378ef03`): production preflight results in
`operations/docs/records/PLAN-003-R2-preflight/` on that branch. No ID/key collisions; 18 admin subject shapes across 15 types;
the 4+4 "orphaned" admin assessments/participants belong to entity findings and M2 deletes them (user decision); ~618,000
entity rows, so whole-table work is timed in rehearsal. WP2 done (`5befc9eb`): migration
`0364` copies admin rows with normalized subjects and `legacy_ref`, deletes the
mislabelled rows, namespace-qualifies active-key uniqueness and adds/validates
tenant FKs; rehearsed on a scratch dev copy (2 s for 9,750 + 107 rows) and a
synthetic fixture of all 18 production shapes; rollback and reapply verified.
Implementation choice: `condition_identity` stays NULL (identity remains derived
from tenant, namespace, type and key; stored only when a later conversion changes
an input), so M2 does not rehash ~618,000 rows. WP3 done: `0365` (`7922e465`)
adds the contract generation (3; M4 publishes 4) and statement/row triggers on
findings, assessments and participants requiring the session tenant, exclusive
tenant guard, matching contract and same-tenant rows, and makes state
namespace-aware (0 entity state differences; admin rows get state). `0366`
(`230fec99`) seeds the action registry and 16 covers rules from `covered_by`; state
reads the rules (0 differences over 9,870 findings), `covered_by` edits sync the
rules, and `finding_relationships` stays empty until R3 reads it.
**Enforcement decision (fact-driven):** production ingest logs in as `ninja`, a
superuser with BYPASSRLS, so revoked privileges and RLS cannot constrain it; the
technical design's alternative, trigger assertions, is used because triggers bind
superusers too. Hardening ingest to a non-superuser login is backlog work.
WP4–WP6 implemented on the branch: `0367` (`6703bac3`) turns `admin_findings` into a
read-only view over admin rows (legacy table retained) and rebuilds
`v_issue_findings` on one ledger with values identical to the pre-conversion
population; `0368` asserts the converted ledger and publishes contract 4.
`ded134d6`/`cf614121` convert every ingest producer and Operations write path to
take the exclusive guard and declare contract 4 (shared admin upsert, namespace
conflict target and filters; the repeatable-read evaluator holds the guard for its
session before its snapshot), add startup admission (ingest/Jobs wait for the
contract; Operations refuses to serve on mismatch), and update source-contract
tests. Scratch rehearsal through `0368`: all seven producers run under enforcement;
unit suites show only the failures already present on base `93a2dd0` (ingest 6,
Operations 8). Rule used: entity writers filter namespace only for the three types
present in both namespaces; single-namespace types are pinned by type.
Local functional testing done (`d5f1c964`, `d977fbed`): guard unit tests (ingest 6,
Operations 20) and single-row request checks on the scratch copy (entity and admin
acknowledge succeed; an unguarded write is refused; contract check reports 4).
Scratch databases and temporary worktrees removed.
User decision (2026-10-29): skip the production-copy rehearsal; migration time,
real-volume rollback and first evaluator duration stay unmeasured. Window runbook
on the branch (`operations/docs/records/PLAN-003-R2-window-runbook.md`): backup,
drain ingest/Jobs, push, watch, verify, abort via `migrate operations 0363` then the
previous release. Master unchanged since `93a2dd0`, so no renumbering needed.
**Released 2026-10-29:** 0.132.0 (`2f050393`), 0.132.1 (`f761e23f`, 0368 check
narrowed to active findings after it aborted on 441,718 historical closed findings),
0.132.2 (`3b456c86`, admin upsert parameter casts), 0.132.3 (`ac12e064`, Jobs
dependency closure casts). First production evaluator run ~24 min. Operations down ~15 min
(18:23–18:38 EDT). Counts identical to pre-window; contract 4 live.
[Deployment record](docs/records/PLAN-003-R2-deployment-2026-10-29.md).
Evaluator and platform-health runs confirmed on 0.132.3; admin findings refresh.
R2 complete. **WP5 gap fixed in 0.133.1 (`d3b988e7`, 2026-10-30):** R2 had not
narrowed the readers, so home, client-page and coverage-summary counts included the
admin rows. `Finding.objects` is now entity-only (`all_namespaces` and the base
manager see both); raw SQL readers in views, the conditions reader and four ingest
lookups filter the entity namespace; `0369` changes model state only. In production:
`0369` applied, containers healthy, 39,412 active entity and 555 admin findings.
PLAN-030 landed in 0.133.0. Next: R3 (unified queue/counts) on branch `plan003-r3`. Evaluator timing
and all volume/lock measurements belong to the WP7 rehearsal, not the workstation
(`AGENTS.md`, "Local development machine limits"); the local full-evaluator runs
done on 2026-10-29 were a mistake and are not repeated.
No concurrent index builds at startup (R1 lesson); the window drains ingest.

### R3 — unified queue and counts (released 0.134.0, `4673dc1`, 2026-10-30)

Code `1239106` on `plan003-r3`; pushed to origin and a-m-rose (no migrations).
`apps/core/issue_selection.py` is the one selection: entity+admin findings and
pending `EntityCandidate`s, `action_key` dedup (entity `unmatched_source_group` +
admin `client_unattached_group` per source group; admin record represents),
covered children excluded and reachable via `?related=<id>`. `findings_queue`
rebuilt on it (old view's entity/admin row hydration extracted to
`_entity_issue_rows`/`_admin_issue_rows`); `_issues_rows.html` renders rows
beneath the open header. Readiness removed (notice for legacy `attention`/
`response`/`covered`); Open/Paused/Resolved; views severity/type/flat (session);
highest-severity default path; per-group page/sort in session; scoped "select all"
(cap 5,000) via `scope_query`; Pause/Resume span kinds/namespaces; remediation
one kind; Review `?return=` back link; home Critical mapping count/link share
`mapping_scope()`. Removed: column text filters, Online/Confidence filters.
**Validation:** Operations suite = baseline (8 pre-existing failures, same set);
new `test_issues_queue.py` + PostgreSQL `test_issue_selection_postgres.py` (20 pass);
scratch-DB page smoke (all views/filters/CSV/bulk) 0.1–0.4 s locally; `check`,
`makemigrations --check` clean; release governance check passed on a clean worktree.
**0.134.1** (code `72441ae`, release `ae0dcd1`, pushed to both remotes): nav
Issues badge = `issue_selection.count(Scope(status="open"))`, cached 60 s per
process (`context_processors._nav_issues_count`); registered remediation runs on
the selected rows of its registered types, skips and reports the rest, and the
confirmation states eligible/ineligible counts (`confirmIssueAction`). Redeployed;
all three containers healthy (status only). Suite: the
8 baseline failures plus `test_migration_0309/0318_postgres` (missing SQL
functions in the harness), which fail identically on `4673dc1`.
**Not done / follow-up:** client-page per-domain counts still read raw findings
(not a mapping count; no design line requires them on the selection); production
latency unmeasured. **Deployed (0.134.0):** Portainer redeployed Operations, ingest and the
Jobs worker; all healthy (container status only; no authenticated page check, and
reading container logs was not permitted in this session).

**Decisions needed during R2:** authorization for a production database copy for
rehearsal (WP7) and the maintenance window time. External saved-query consumers
appear retired (`metabase_ro` dropped in `0359`); confirm none remain.

**Affected files:** current design, checklist/report, this handoff and root
router/registry; TODO carries separately gated findings. VERSION/CHANGELOG are
unchanged because this is design-only, with no application release.

**Technical package revised after review (2026-10-27):**
[technical design](docs/plans/PLAN-003-technical-design.md),
[consumer/alertability ledger](docs/plans/PLAN-003-consumer-ledger.md) and
[Proposed ADR-0046](docs/decisions/0046-unified-findings-and-relationships.md).
Baseline 80557f6 plus preserved dirty worktree. Audit covers 36 runtime Python
reference files, 13 live database functions and related views/FKs/history;
catalog snapshot was read-only/repeatable-read under tenant 1 at 18:08 UTC.
All 71 current/proposed alertability flags are recorded. User approved turning
off alertability for the inventory/lifecycle-review meaning of unenrolled in
M5; storage conversion preserves current flags. User also approved Readiness
control removal while retaining technical guards. Common storage/identity/state,
six planned migration stages, guarded
cutover/rollback and acceptance criteria are specified. No migration files,
runtime edits, evaluator/source actions or release changes made.

**Second-pass review checkpoint:** [R1–R4](docs/plans/PLAN-003-technical-review.md)
are revised: named namespace-specific read adapters and exact-set assertions;
registered relationship action keys; tenant lock function before row locks with
trigger assertion; exact writer contract generations with database stale-caller
rejection; M2–M4 in one drained artifact. No runtime or migration enforcement
was implemented. Migration numbers are assigned after rebase; occupied 0354 is
preserved.

**Approved decisions:** remove Readiness presentation controls while retaining
technical guards; M5 sets `device_unenrolled` alertability false for its
inventory/lifecycle-review meaning. **Implementation handoff:** the consumer
ledger classifies direct ORM callsites, runtime processes, registered actions
and relationship effects. Implement the versioned database writer/lock boundary
and namespace adapters from the reviewed technical package. Verify PostgreSQL
role/RLS and concurrency behavior before migration approval/execution. All-
tenant preflight, external-consumer audit and isolated recovery rehearsal remain
release gates.
Before execution/release require actual code/migrations, all-tenant preflight,
external saved-query audit, authorized isolated recovery rehearsal and runtime
RLS/action/browser/performance acceptance. No validation result is invented.
Recommend a fresh session before implementation; verify Git/files on resumption.

**Validation:** registry, shared governance and scoped whitespace checks pass;
warnings are root BLUEPRINT length and docs/current-state.md age. No application
tests apply to these doc-only changes. Historical W7-W9 details below are not
current execution approval or proof that the redesigned page is implemented.

**Prior W7-W9 implementation scope:** platform Jobs finding evaluation, Issues read projection, Admin
Health reveal links, and finding-ledger/type housekeeping. No identity
matching, candidate withdrawal, canonical data repair, or direct production
writes. New migrations 0352-0353 apply through an approved deployment push.

**Decisions:** W7 matches the prerequisite run for timeouts and prerequisite
job key for repeated/scheduled failures. Covered dependency rows keep their
history, reason, and parent key, and Admin Health exposes their run links.
Only the overlapping `operator.jobs` queue signal is retired;
software-specific queues remain. W8 uses a `security_invoker` union view with
RLS and explicit runtime DML revokes; storage and existing action surfaces
remain separate. W9 closes only exact same-type/key legacy entity duplicates
when a matching active admin finding exists, preserving the admin finding ID
and closure reason. Historical type rows remain retained.

**Checkpoint:** W7 implemented in `ingest/platform_findings.py`; W8 view/model
and Issues taxonomy counts added in migration 0352; W9 duplicate closure is
migration 0353. Candidate dispositions confirmed: `device_long_offline` is
historical, `multi_av_conflict` disabled, and withdrawn-source findings were
retired by migration 0316. `device_stale_data` still has an active evaluator.
Identity-related dormant candidates remain with PLAN-004. The remote-access
action requires permission and reason; Ninja presence only counts
`AgentDevice`.

**Validation:** Python syntax compilation, plan-registry validation (22
entries), and `git diff --check` pass. Django checks and database migration
execution were unavailable locally; tests were not run. Production behavior
is unverified and awaits normal approval/deployment.

**Prior execution gate:** the previous checkpoint requested origin-push
approval for automatic deployment and migrations 0352-0353. This is historical
context; the current next action is the design review above.

**Historical deployment incident (2026-10-26; not current live status):** Operations is restart-looping because
migration 0352 references nonexistent `operations.findings.resolved_at`;
entity findings store this timestamp as `closed_at`. Migration 0353 also tried
to write nonexistent `resolved_at` when closing the exact duplicate. Both SQL
references are corrected locally; 0352 exposes `closed_at` as read-model
`resolved_at`, and 0353 updates `closed_at`. The failed 0352 startup attempt
reported a PostgreSQL undefined-column error. Next: obtain approval to push the
corrected migrations, then verify migration application and container health.
After the migrations applied and the container became healthy, `/` returned
500 because the client patching rollup sent `{current_computer_sql()}` as
literal SQL. The query now uses an f-string locally. Python compilation and
`git diff --check` pass; this code-only follow-up has no schema change.

## PLAN-023 — Software installations layout repair

**Status:** Complete locally (2026-10-27). **Goal:** make installation filters compact and
aligned, and prevent long paths from expanding the page.
**Scope/files:** `templates/software_installations.html`, this checkpoint and
the root registry/router only. Preserve query parameters, multi-selection,
CSV, sorting and pagination; no view, schema or dependency changes.
**Steps:** add a responsive filter grid with expandable searchable selections;
bound table columns with Install path last and full paths in hover tooltips; validate existing
tests, template loading, browser layout/interaction with synthetic data,
Django checks, registry and whitespace.
**Decision:** page-scoped styles and native disclosure controls keep the change
isolated and keyboard accessible. Preserve all pre-existing dirty work.
**Checkpoint/validation:** implemented the responsive grid and compact searchable
multi-select disclosures; constrained the table and path column. Four existing
installation tests pass; Django system check and template rendering pass.
Headless Edge checks at 1440/1024/768/390px pass for page overflow, equal filter
widths, path position/tooltip, selection preservation, submission values,
Escape and outside-click dismissal. Synthetic data only; no live validation.
Registry, governance and whitespace checks pass; governance notes the existing
stale current-state document. Dockerfile already copies the edited template.
**Release checkpoint:** user approved commit and push on 2026-10-27. Both
remotes match HEAD before release; deployed read-only migration checks show no
pending Django migrations and ingest versions 001–118 applied. Release 0.129.2
adds no migrations. The runbook's manual-redeploy instruction conflicts with
AGENTS.md; follow AGENTS.md and rely on the push-triggered deployment only.
**Published:** `80557f6` (0.129.2) committed and pushed successfully to origin,
then a-m-rose on 2026-10-27. Unrelated local work remains uncommitted.
**Next action:** verify Portainer deployment and the live page when authorized.
The deployment outcome and live UI remain unverified; no manual redeploy ran.

**Read-only follow-up (2026-10-27):** user asked why installation names are
lowercase. Confirmed `ingest/inventory/software.py` normalizes the source
program name with `name.lower()` into `canonical_name`; `software_installations`
uses that key directly for the Program label and Product option labels.
The layout release did not change this data path. A proper display-name repair
needs a separately preserved source label while retaining canonical keys for
matching/links; display-label availability has not yet been established.
No application edits are authorized by this diagnostic question or made here.
Recommend a fresh session before implementing that independent follow-up;
verify Git and the checkpoint first and preserve the unrelated dirty worktree.

## PLAN-021 — Generic entity candidate lifecycle reconciliation

**Status:** Complete; cross-service checkpoint is in root [BLUEPRINT.md](../BLUEPRINT.md).
The reviewed production population has 77 linked candidates whose proposed
entity class conflicts with the authoritative link. Local implementation adds
audited withdrawal for inactive unlinked proposals and linked class conflicts,
class-safe attachment, reactivation for explicitly active unlinked evidence,
and queue/history visibility. Attached links/history and rejected decisions
remain intact.

**Checkpoint:** migration 0355 adds the withdrawn status and versioned
`sync_entity_candidates_v2` function. Ingest waits for the new function before
calling it, and the old three-column function remains a wrapper, so startup
and rollback do not depend on which service finishes its migration first.
Projector withdrawals have explicit event reasons; rejected
and attached states stay untouched; matching-class links attach; inactive
unlinked candidates withdraw; active unlinked withdrawals reopen. The focused
candidate/admin run produced 24 passes with one unrelated existing admin test
excluded; the passing set includes five isolated PostgreSQL lifecycle/security
tests. Django system check,
migration autodetection, targeted Ruff, plan registry, Python compilation,
formatting, and whitespace validation pass. The excluded test expects missing
`ConditionPolicyActivationForm`. Commit `6add50f` was pushed to `origin` and
then `a-m-rose`. Migration 0355 and Operations health were verified. On
2026-10-27 the bounded production projector completed one changed batch with
669 withdrawals (592 inactive-unlinked, 77 linked-class conflicts). Read-only
tenant-scoped checks confirmed matching withdrawal events, no inactive
unlinked actionable candidates, no active withdrawn unlinked candidates, and
no linked class mismatches among pending/observed-only candidates. Sixteen
attached-class mismatches remain preserved in history. See the root
[checkpoint](../BLUEPRINT.md), [plan record](docs/plans/PLAN-021-entity-candidate-lifecycle.md),
and [registry](../docs/records/PLAN_REGISTRY.md). No further PLAN-021 action
remains.
## PLAN-004 — Identity and source-record maintenance review

**Active, review only.** Full review scope, confirmed gaps, user requirements,
ownership and acceptance gates: [handoff](docs/plans/PLAN-004-source-record-review.md).
PLAN-003 owns shared finding storage and queue presentation; PLAN-004 owns
matching, source-record maintenance and detection. Initial production/code
review is complete; fleet impact and all-source contracts remain pending.
**Next:** resume in a fresh session, verify deployed/Git state, then complete
the producer/consumer/state matrix and aggregate review before implementation.

**R4 blocked on a decision (2026-10-30, after R3 release 0.134.0).** Final design
§3/§7.2 has intake take the shared tenant guard in every observation-write
transaction. R2's writers take the exclusive guard via `db.findings_transaction`
(resolver, client resolver, cmdb, patch, platform, Windows servicing, software
reconcile) and the evaluator holds it for its session (~24 min first production
run). Shared-mode intake would wait behind those, stalling collection. Options:
(a) shorten exclusive holds to bounded publication batches before Stage A intake;
(b) admit subjects outside the intake transaction (Jobs worker reading new/changed
observations), a design amendment; (c) intake without the guard plus a trigger
that advances the generation. Also unresolved: §7.2 requires representative
concurrent-ingest load measurement, which the workstation rule forbids; needs an
authorized environment. Stage B handoff needs a drained window and the
reassessment operation needs separate authorization. No R4 code written.

**R4 decisions (user, 2026-10-30):** (1) Option (c): intake writes observations
without the tenant guard; a database trigger records each change and advances
the generation (chosen as fastest for incoming data). This amends final design
§3/§7.2 and ADR-0049 — record the amendment there before Stage A code. (2) §7.2
concurrent-ingest load measurement is waived; watch ingest timings after release
and record the waiver in the design. (3) Stage B drained window: any time when
ready; drain, apply, notify the user after. (4) The one-time reassessment runs in
the same drained window right after Stage B; report results. Each still uses the
normal release check, migration pre-checks and backups.

### R4 implementation (started 2026-10-30, branch `plan003-r3`, base `7a8b67b`)

**Status:** Stage A code `d0f5826`, release 0.135.0. Commits/pushes, the Stage B window and the
reassessment are authorized (user, 2026-10-30). Testing: only what is needed to
continue safely, no heavy workstation/dev runs; final testing after the plan.
**Amendments recorded:** design §2.1/§3/§7.2 and ADR-0049 (R4-1 unguarded
intake + trigger/deferred generation; R4-2 load waiver).
**Production facts (read-only, 2026-10-30):** at `0369`; ingest connects as
superuser `ninja` (enforcement must be triggers, not grants); 42,271 current
observations, 34,557 with `device_id`, 34,557 device links, 0 device-link
divergences; 1,409 `asset` links (no projection); PostgreSQL 16.14.
**Stage A (code written):** `0370_source_record_subjects` (subjects, generation,
lookup keys, monitored queue `source_record.assessment`, current assessments,
admission + deferred generation triggers, backfill, four non-alertable native
types, replay-safe recovery row); `ingest/source_records.py` (job
`source-record-assess`, every 5 min, 200-row batches under exclusive guard +
generation share lock); Issues rendering and `inventory/source-records/<uuid>/`.
Decisions: name keys compare only within the mapped client; documentation and
group roles take no identity keys; >200-member buckets enqueue only their case
key; attached invalid serials belong to `placeholder_serial`, pending candidates
own their identity work; `source_record_policy_incomplete` registered but not
emitted (no production type is unclassified) — TODO.
**Next:** model-state check, Stage A release, then Stage C, then Stage B window.
