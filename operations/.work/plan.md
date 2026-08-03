# Active Operations implementation plan

Track: **Cross-service Ninja generic cutover and native availability slice**

**Status:** local candidate validated and approved for commit and combined
production/mirror push; coordinated by root `.work/plan.md`.

## Goal and scope

Complete the Operations portion of the approved root implementation slice:

- source session reboot/boot state from exact active generic Ninja detail
  observations rather than `ninja_core.device_snapshots`;
- source Software overview fleet-wide aggregates from a compact tenant-scoped
  materialized title model rather than grouping the full installation-current
  table on every request;
- preserve existing effective-view columns, tenant behavior, decisions,
  current consumers, and rollback relations.

Out of scope: canonical identity changes, Agent Compliance, legacy history
deletion, unrelated Software detail queries, Metabase improvements, deployment,
and production-data changes.

## Affected files

- `apps/core/migrations/0100_generic_ninja_and_software_read_models.py`
- `apps/core/views.py`
- focused migration and view tests
- root `VERSION`, `CHANGELOG.md`, and root/Operations plans

## Decisions and steps

1. Recreate `device_session_current` and `v_device` with their public shapes,
   indexes, grants, and owner unchanged. Select reboot/boot evidence from the
   exact Ninja source instance, namespace, scope, and projection version;
   break exact observed-time ties deterministically in favor of the direct RMM
   agent record.
2. Add `software_title_current` at tenant/title grain with active installation,
   device/client, publisher, and first/last-observed aggregates. Give it a
   concurrent-refresh key and the existing trusted read-role grants.
3. Rebuild `v_software_safety` over that compact title model without changing
   its output contract, then update only Software overview fleet-wide queries.
4. Refresh title then safety once per completed software ingest batch.
5. Validate migration state/order, PostgreSQL behavior, tenant scoping,
   focused requests, Django checks, Ruff/format, Docker packaging, and diffs.

## Current checkpoint and next gate

The prior Track B plan is complete in Git history. Root checkpoint and dirty
tree were reconciled at `45110f7`; unrelated local changes are preserved. The
Operations 0100 migration, compact software-title model, device-session generic
reader, software overview queries, and refresh path are implemented.

Validation passed in the rebuilt Operations image (27 tests, 2 opt-in skips,
Django system check, and no migration drift) and in disposable PostgreSQL 16.
The migration preserved the public view shapes and exercised direct-agent
tie precedence. A real Software overview request smoke caught and corrected a
column-alias defect; the rebuilt image then returned the expected aggregate
without an HTTP 500. Production read-only preflight confirmed the measured
session changes are attributable to higher-fidelity direct-agent selection and
withdrawal of stale evidence, not lifecycle transitions.

**Next action:** follow the root plan's approved push/deployment sequence, then
verify migration 0100, the Software request surface, service health, and the
zero-HTTP-500/worker-timeout observation window.
