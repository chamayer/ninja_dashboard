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

Complete for prompts (deployment check pending); overview pending. Goal: a decision covers an install when that install's own effective
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
reconcile rewrites prompts (e.g. Microsoft Store), then the overview change.

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
