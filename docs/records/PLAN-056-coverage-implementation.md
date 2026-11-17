# PLAN-056 — Coverage lifecycle join implementation

## Scope and authority — 2026-11-11

The user approved the proposed Coverage join correction and focused synthetic
PostgreSQL tests. Implementation is local and uncommitted, based on HEAD
`ca00938a`. Existing Home/Issues/Software/cache, migration and test changes are
preserved. This slice introduces no migration, dependency, shared view, grant,
cache, configuration or public-interface change. Commit, push, deployment and
external validation remain separately gated. Other proposed fixes are unapproved.

## Change and reasoning

`operations/apps/core/views.py:fleet_coverage` now uses the diagnosed correlated
`LEFT JOIN LATERAL` for its initial Hudu lifecycle lookup. Both tenant and
observation predicates remain inside the lookup; `OFFSET 0` keeps lifecycle
policy evaluation scoped to the requested observation. The authoritative
security-barrier lifecycle view, outer population, projection, ownership joins
and later page phases are unchanged. See the
[recovery comparison](PLAN-056-recovery-path-comparison.md) for retained actual
plans and earlier current-tenant parity evidence. This is an access-path
correction under existing contracts, not a new architecture decision.

The Operations Dockerfile already copies `operations/apps/` into `/app/apps/`.
No packaging or Compose change is needed for this existing runtime file.
Reversion scope is only the join change; preserve the earlier edits in views.py.

## Actual validation

- Two new PostgreSQL tests pass in a disposable PostgreSQL 16 testcontainer,
  using only synthetic records and the existing migration 0158 lifecycle view
  SQL, including its security barrier and grants. The actual page SQL is
  extracted and compared with the original join as full six-field row multisets.
  Expected outputs also cover archived/default-unmatched policy, absent lifecycle
  rows, duplicate multiplicities, an enabled priority override, a disabled rule,
  and tenant visibility under `operations_app` with RLS on synthetic outer inputs.
- Existing `test_coverage.py`: 24 pass, three fail. All three failures reproduce
  with the unchanged HEAD `fleet_coverage` loaded in memory, without replacing
  workspace files. One assertion expects the obsolete Hudu evidence view and
  grouping; two fixtures supply shorter Computer tuples than the reader expects.
  The same failures occur with the corrected join. Existing tests were not edited;
  follow-up scope is recorded in `operations/TODO.md`.
- Django `manage.py check`, Python compilation of both changed Python files,
  and Ruff lint/format checks for the new test module pass. Workstation commands
  use the existing `.venv` and repository root on `PYTHONPATH`; the first pytest
  attempt could not collect until that shared-module import path was supplied.
- Registry validation, whitespace review, handoff-size and local-link checks are
  recorded in the active handoff after final validation.
- Testcontainer cleanup completed; only the preexisting local development
  containers remain. No local fleet processing, performance benchmark, remote
  execution, Job, migration, release, commit or push was performed.

## Limits and next action

These tests exercise the actual lifecycle view and query against minimal outer
table fixtures. They do not certify all deployed Hudu/security views, ordinary
user masking, production RLS policies, complete page behavior or latency.
Coverage end-to-end and cold/repeat acceptance remain open. The retained slow
original must not be replayed without bounds.

Review this isolated slice for commit separately from the preserved worktree.
Before release/push approval, inspect actual pending migrations and selected
release contents. Any external response validation needs a concrete bounded
protocol and approval. PLAN-056 remains active; the relationship-history guard
and resource interaction work are outside this implementation approval.
