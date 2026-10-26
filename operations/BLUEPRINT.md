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

Extended (user-approved): ADR-0038 (Proposed) — the resolver moves a renamed
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

Implemented and validated locally; committed and pushed on user approval (2026-10-21). Deployed-stack sign-in not yet verified.

## Validation

- `pytest apps/core/tests/test_login.py`: 6 passed (sign-in render, POST-only
  sign-out, password change requires sign-in, header links, templates).
- Full `pytest apps`: 439 passed, 133 skipped, 4 failed; the same 4
  conditions/generic-admin failures occur on clean HEAD 3091a47.
- `manage.py check` clean; ruff check/format clean on new files. Pre-existing
  format drift in `config/urls.py` and `config/settings/base.py` left as is.
- Not validated: a real database sign-in (local settings use the SQLite
  skeleton) and the deployed stack.

## Checkpoint

Committed. Follow-ups (group-based edit checks, SSO decision, Users page)
are in `operations/TODO.md`.

## Next action

Verify sign-in, sign-out, and password change on the deployed stack, then mark PLAN-013 complete.

## PLAN-003 — Central work queue and finding state (W7-W9)

**Status:** Implementation complete locally (2026-10-26); deployment push pending separate approval.
**Goal:** complete W7-W9 while retaining separate entity and admin finding
storage. PLAN-004 identity work is excluded.

**Scope:** platform Jobs finding evaluation, Issues read projection, Admin
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

**Next action:** request separate origin-push approval. That push automatically
deploys and applies migrations 0352-0353.

**Deployment incident (2026-10-26):** Operations is restart-looping because
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
