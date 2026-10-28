# PLAN-004 — Per-record status and contact repair

## Status and goal

Complete locally, approved and validated 2026-10-28. Computer source-record rows
must show each record's reported status and contact time. The shared reader
also serves merge review. The broader PLAN-004 review remains outside this
repair; the [registry](../../../docs/records/PLAN_REGISTRY.md#plan-004--computer-identity-history-and-naming)
owns lifecycle status. The user subsequently approved this scoped commit.

## Scope and files

- Add migration `0361_source_record_reported_contact.py` to append one guarded,
  typed contact timestamp to the existing restricted metadata view.
- Update `apps/core/views.py` to join that view by tenant and observation ID
  instead of reading platform-level presence for each record.
- Add focused PostgreSQL and template regression tests. Existing templates
  already accept per-record status/contact in the reader's tuple contract.
- Update this checkpoint, the review handoff, root routing, and registry.

No matching, finding, lifecycle, attachment, source cleanup, production-data,
release, push or deployment change is authorized. Preserve unrelated edits.

## Decisions and steps

1. Preserve the metadata view's tenant filter, security barrier, restricted-layout
   masking, SELECT-only grants, and explicit runtime DML revocations.
2. Read status from existing `reported_online`; append
   `reported_last_contact_at` from the record's canonical `last_seen_at` value.
   Accept valid timezone-bearing ISO timestamps; missing, invalid, infinite,
   timezone-free and year-one sentinel values yield NULL. Never substitute
   collection time. `Last updated` keeps its collection timestamp.
3. Keep tuple shape and template lifecycle precedence. Use the same observation
   identity for status and contact, including withdrawn records.
4. Validate contrasting sessions on one Computer, missing/invalid contact,
   restricted records, tenant isolation, runtime privileges and rendering.
5. Application rollback restores the previous reader; the additive view field
   can remain. No historical migration is edited and no stored data is rewritten.

These enforce the existing source-evidence and restricted-reader decisions;
no new architectural or attachment policy is adopted.

## Validation and checkpoint

Inspected current files, Git diffs/status, module instructions, metadata-view
migrations, shared reader and templates. `0361` is unoccupied. A repository
virtual environment has Django, pytest, Ruff, psycopg and testcontainers.
Migration 0361 appends the guarded timestamp and preserves view permissions.
The shared reader now joins metadata by tenant/observation ID and keeps the
existing tuple shape. Templates require no changes. Dockerfiles already copy
all module migrations and runtime files.

Validation: 39 focused tests pass in an isolated staged snapshot, including 20
disposable PostgreSQL/runtime-role and rendered-template cases. The broader dirty
worktree passed 41. The privilege case verifies removal of injected runtime DML
grants. Django system
checks, migration graph (0361 is the sole Operations head), scoped Ruff/format,
fatal view lint, registry validation and whole-worktree whitespace checks pass.
The staged registry also passes the workspace's currently untracked validator.
Tests use synthetic data only. Live browser behavior, existing dev-stack migration
application and production deployment were not performed. Migration rollback
retains the additive field; the previous application reader remains compatible.

The existing module BLUEPRINT is over 75 KB and contains unrelated active work;
rewriting it is outside this scoped repair. The registry links this compact
checkpoint. Broader review documents and root routing remain separate work.

Next: obtain separate push/deployment approval explicitly including migration
0361, then validate deployment. Resume the broader review separately.
