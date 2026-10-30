# PLAN-004 — Per-record status and contact repair

## Status and goal

Deployed and verified 2026-10-28 in 0.130.1. Computer source-record rows
must show each record's reported status and contact time. The shared reader
also serves merge review. The broader PLAN-004 review remains outside this
repair; the [registry](../../../docs/records/PLAN_REGISTRY.md#plan-004--computer-identity-history-and-naming)
owns lifecycle status. Repair `a0a2c53` and release `c7628b9` are on both remotes.

## Scope and files

- Add migration `0361_source_record_reported_contact.py` to append one guarded,
  typed contact timestamp to the existing restricted metadata view.
- Update `apps/core/views.py` to join that view by tenant and observation ID
  instead of reading platform-level presence for each record.
- Add focused PostgreSQL and template regression tests. Existing templates
  already accept per-record status/contact in the reader's tuple contract.
- Update this checkpoint, the review handoff, root routing, and registry.

No matching, finding, lifecycle, attachment, source cleanup, production-data,
release or deployment beyond this approved repair is authorized. Preserve unrelated edits.

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
Tests use synthetic data only. Live browser behavior and existing dev-stack
migration application remain unverified. Production applied 0361; all three
application services are healthy, deployed file hashes match `c7628b9`, Django
checks pass, and runtime metadata access and tenant isolation remain enforced.
See the [deployment record](../records/PLAN-004-source-record-status-deployment-2026-10-28.md).
Migration rollback
retains the additive field; the previous application reader remains compatible.

The oversized module BLUEPRINT remains outside this repair; the registry links
this scoped checkpoint.

Next: resume the broader PLAN-004 review; any browser acceptance remains separate.
