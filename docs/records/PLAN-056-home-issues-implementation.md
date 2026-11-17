# PLAN-056 — Home Issues query simplification

## Scope and authority — 2026-11-11

The user approved review/completion of the inherited Home Issues compact-query
changes and focused tests. HEAD remains `ca00938a`; other working changes and
the three earlier local fixes are preserved. This slice adopts the reviewed
changes in `operations/apps/core/issue_selection.py` and extends the focused
Issues PostgreSQL tests. No cache, view, migration, index, dependency or public
interface change is included. Runtime, middleware, Software and cache changes
elsewhere remain outside this slice's review and release scope.

## Reviewed change and contract

The existing local candidate needed no further behavioral correction after
source review and expanded validation. Clarifying comments were added. Compared
with HEAD, compact Home items omit unused covered-by arrays and non-shared text
action keys. Ordinary Issues queries retain their full item shape and ranking.
Compact selection still passes individual non-shared findings/candidates through
separately and ranks the two shared source-group finding types by their existing
action identity, status, admin preference, severity and ID.

Home totals group by type/category/status without severity buckets or unused
distinct client/subject sets. Only open attention branches compute those distinct
sets and highest severity. Critical counts still filter before choosing shared
representatives; mapping counts retain their own type-filtered representative
population. Non-shared critical mapping rows reuse `critical_actions`.
Covered representatives are excluded after ranking, preserving the existing
contract. Paused/resolved behavior, candidate populations, taxonomy categories,
attention sorting/limits and links remain unchanged.

Home deliberately counts recorded client associations. The ordinary Issues
selector also performs current ownership checks, so comparing its `client_id`
column directly would silently change Home's existing meaning. The independent
test reference uses ordinary queue selections for action membership, then reads
recorded associations for Home's client cardinalities. No new ownership or
privacy contract is adopted; this is covered by explicit synthetic cases.

The Operations Dockerfile already copies `operations/apps/`; no packaging or
Compose change is required. Reversion scope is the reviewed issue-selection
hunks, preserving all unrelated work. No new architectural decision is needed.

## Actual validation

- **21 PostgreSQL checks pass:** 13 existing plus eight new cases, using one
  disposable PostgreSQL 16 container with small synthetic fixtures. No fleet
  processing, performance benchmark or production execution.
- Six new combinations vary whether a shared admin representative is covered
  and whether mapping scope includes none, one or both shared types. The full
  Home summary and ordered attention dictionaries are compared with independently
  scoped ordinary Issues queries, at attention limits 0, 2 and 20.
- Fixtures include mixed severities across shared siblings, separate open/paused
  representatives, repeated clients/subjects, all severity levels, covered and
  resolved findings, acknowledged findings, pending versus observed-only
  candidates, and recorded associations without current ownership.
- Additional cases verify zero totals/categories for an empty population and
  unchanged output with other-tenant findings/candidates under a restricted role
  and synthetic tenant RLS. Links and affected-count text are part of the full
  dictionary comparison. The fixture is not a full deployed RLS certification.
- Existing focused Home request/template composition check passes (one check).
  It runs against the current mixed worktree; it does not approve its cache or
  other inherited changes for release.
- Django system check and Python compilation pass. Test-file Ruff lint passes;
  runtime lint reports only the two preexisting `_filtered_sql` complexity
  findings (`PLR0912`/`PLR0915`), reproduced against HEAD. Runtime and inherited
  test additions have existing formatting differences; only the newly added
  test range was formatted to avoid unrelated churn. No new lint finding.
- Final registry, whitespace, local-link and handoff-size checks are recorded in
  the active handoff. Testcontainer cleanup leaves the preexisting dev services.

## Limits and next action

The retained three-second Home Issues timeout and non-ANALYZE plan motivated
this candidate; the actual execution cost distribution is still unmeasured.
Smaller projections and less grouping do not establish response latency.
No cache-miss, cold/repeat, full-page or production performance claim is made.
The ordinary Home goal and checklist acceptance gates remain open.

Review this fourth logical slice separately before commit approval. Selected
release contents and actual pending migrations need review before push approval;
external validation needs a bounded protocol and approval. PLAN-056 remains
active; resource interaction stays deferred. No commit, push or deployment.
