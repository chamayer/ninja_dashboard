# PLAN-022 — Legacy data and code cleanup

**Completed 2026-10-28.**

Registered and approved for immediate execution by the user on 2026-10-26
("write up a cleanup plan to be executed immediately"). Absorbs PLAN-006
(legacy agent-compliance retirement) and the F09 decision of PLAN-019.
Production drops happen only through reviewed migrations shipped by an
approved push, after the exports below are verified. Push approval must
name the drops.

## Goal

Remove legacy tables, views and code that no current workflow reads, after
exporting their data, so the database and code carry only current
authorities.

## Evidence (2026-10-26, read-only)

[Inventory queries and results](../records/PLAN-022-legacy-cleanup/):
PLAN-017 Phase 3 transport, read-only, rolled back.

| Item | Size | Last written | Current readers |
| --- | --- | --- | --- |
| Database `ninja` | **62.4 GB** | | |
| `ninja_core.device_snapshots` | 14.1 GB | 2026-08-03 | Two one-off tools only (`backfill_ninja_daily_rollup.py`, `restore_ninja_historical_evidence.py`) |
| `ninja_core.device_health_snapshots` | 7.3 GB | 2026-08-03 | `restore_ninja_historical_evidence.py` only |
| `ninja_agent_compliance` schema (21 tables, 30 views) | 12.8 GB | 2026-10-06 | Bridge Jobs, retired legacy bridges whose schedules are disabled (last run requested 2026-10-07; `AGENT_COMPLIANCE_ENABLED=true` remains in the host env file); `parity_check` job; `ninja_inventory` views |
| `ninja_inventory` schema (7 empty materialized views and their views) | 0.04 GB | never refreshed | `ingest/inventory/refresh.py`, which nothing calls |
| `operations.source_record_seen_daily`, `ninja_device_seen_daily_shadow` | 0.11 GB | daily (Ninja) | None in the repository |

Jobs rows naming the four removed Jobs (L9): history in `operator_job_runs`
62, `job_requests` 25, `job_schedule_events` 78, `job_recovery_assessments` 4,
`job_definition_versions` 33; configuration in `job_schedules` 2,
`job_recovery_policies` 9, `job_recovery_policy_authorities` 2. **Decided
(user, 2026-10-26): keep runs, requests and recovery assessments as audit;
remove the recovery configuration.** Migration
`0351_retired_job_configuration` deletes the recovery policies and approvals.
The first version also deleted the two disabled schedules and their 78
schedule events; production refused it because `job_schedule_events` is
append-only (`reject_jobs_history_mutation`, 0183), which stopped Operations
from starting after 0.129.0 (2026-10-26 21:07 UTC). Fixed in 0.129.1: the
schedules and events stay. The pre-deploy checks had covered triggers on the
dropped tables but not on the Jobs tables `0351` edits.

Activity counters cover only the time since the last restart, so they are
supporting evidence; the authority is the code search and the last-write
times. No Metabase container runs on the host; `metabase_ro` holds `SELECT`
on two `operations` relations and one each in `ninja_activities` and
`ninja_patches`, none of them in this cleanup.

## Decisions

- **F09 (user, 2026-10-26): no daily presence for any source.** Presence over
  time becomes part of the ADR 0045 significant-change trail (PLAN-019
  Step 4). Supersedes ADR 0007's provisional daily-presence decision and
  ADR 0010's daily active-device rollup.
- Every dropped table is exported first with `pg_dump -Fc` to
  `/amr-ch-01_data/ninja-dashboard/backups/legacy-2026-10-26/` on the host,
  and the archive's table of contents is verified. Same-disk archive: it
  protects against a wrong drop, not disk loss.
- Precedent: SQL migration `115` (export, then `DROP TABLE` on the SQL
  track). Tables owned by `ninja` drop on the SQL track; `operations`
  objects drop in a Django migration.
- ADR 0010's prohibition on deleting legacy snapshots is lifted by this plan,
  recorded as an amendment.
- Restore rehearsal waived by the user (2026-10-26). Archive verification is
  the table-of-contents check (data present for every dropped table) and
  SHA-256 hashes.

## Wave A — done 2026-10-26

| Step | Change | Files | Status |
| --- | --- | --- | --- |
| A1 | Stop writing Ninja daily presence; remove the writer, its hook, the uncalled `_write_ninja_observations_legacy` and the backfill tool; migration `0350` drops the shadow view and `source_record_seen_daily` | `ingest/core/devices.py`, `ingest/observations.py`, `ingest/source_observations.py`, `ingest/backfill_ninja_daily_rollup.py`, tests, `0350` | deployed |
| A2 | Drop `ninja_core.device_snapshots` and `device_health_snapshots`; remove `restore_ninja_historical_evidence.py` | SQL migration `117`, tool and its tests, `docs/operations.md` | deployed |
| A3 | Retire agent compliance: remove the bridge package, its four Jobs (`agent-compliance`, `-evaluate`, `-review-digest`, `parity-check`), the `legacy_bridge` mechanism, every `AGENT_COMPLIANCE_*` setting (notifications now read only `NOTIFY_*`; production has notifications off, and four old delivery values in the host env file must be renamed to `NOTIFY_*` before notifications are switched on), the HTTP action routes (now `410`), the `_agent_compliance` raw key (now `_collector`); SQL migration `118` drops `ninja_inventory` and `ninja_agent_compliance`, refusing if anything outside depends on them | `ingest/agent_compliance/`, `ingest/parity_check.py`, `ingest/inventory/refresh.py`, `ingest/main.py`, `ingest/config.py`, `ingest/notifications.py`, `ingest/operator_job_queue.py`, connectors, `shared/jobs_registry.py`, `operations/apps/core/views.py`, `.env.example`, tests, `118` | deployed |
| A4 | Export every table A1–A3 drop, plus one full backup without the legacy rows, to `/amr-ch-01_data/ninja-dashboard/backups/operations/legacy-2026-10-26/`; verify table of contents and hashes | Host only | done 2026-10-26 19:51 UTC: 4.6 GB; daily presence 1, snapshots 2, agent compliance 21 tables of data; full dump 279 tables of data and no legacy rows; SHA-256 in `MANIFEST.txt` |
| A5 | Three separately approved pushes (below); verify each on production | Push 1 `a2d7cbe` (`0349`), push 2 `cd98853` (code), push 3 `1b087ce` (0.129.0, drops), fix `4e13fa0` (0.129.1, `0351`) | done 2026-10-26 |

## Deploy order (after independent review, 2026-10-26)

The review found that ingest and the Jobs worker start without waiting for
Operations' Django migrations, so new code can meet the schema before `0349`
exists, and that a code rollback after the drops needs the data restored
(old code's compliance HTTP routes and manually requested Jobs still query
the dropped schemas).

1. **Push 1 — migration `0349` only.** Additive column with a default;
   current code ignores it. Verify it is applied before push 2.
2. **Push 2 — the code changes.** No drops. Smoke gate: SQL migrations
   finished (not only `/healthz`, which answers before they run), Jobs
   worker heartbeat ready, a Ninja collection and a source collection
   succeed, and the Jobs, Sources, Health and Notifications pages load.
   Rollback: revert and redeploy; no data involved.
3. **Copy the archive off-host and re-verify its hashes** before push 3.
4. **Push 3 — `0350`, `0351`, `117`, `118`.** Verify the database shrank by
   about 34 GB. Rollback from here needs the archive restored as well as a
   code revert.

Each push needs its own approval naming its migrations. The host `.env`
stays unchanged through the rollback window. Before notifications are
switched on, copy the delivery values to `NOTIFY_*`, verify, then remove the
`AGENT_COMPLIANCE_*` keys (backlog).

Residual risk, accepted by the user: the restore rehearsal was waived, so
the archive's table of contents and hashes show it is complete and intact,
not that it restores.

## Wave B — 2026-10-28

Measured read-only (L17–L21; the 2026-10-28 run sends SQL straight to
`psql` inside the same read-only, rolled-back wrapper, because the shared
helper now refuses Python sent as command text). The user approved B1–B3 on
2026-10-28 and closed the Metabase rollback window.

| Step | Change | Evidence | Status |
| --- | --- | --- | --- |
| B1 | Drop `operations.parity_report` (the agent-compliance cutover gate; no writes since 2026-10-07, 0.5 MB) and remove `legacy_job_key`, the "Previous schedule" fallback on the Sources and Jobs pages (all 10 reference feeds have completed under source-refresh; last legacy run 2026-10-08). The old runs stay in `operator_job_runs`. Migration `0358` | L17, L18; deployed L22, L23 | deployed 2026-10-28 |
| B2 | Drop the `metabase_ro` role: NOLOGIN, no members, owns nothing, and only this database depends on it (269 relation grants, 6 default privileges, 5 schema grants). Migration `0359` runs `DROP OWNED` then `DROP ROLE`; a test rejects the role in any later migration. ADR 0005 amended | L20; deployed L22, L23 | deployed 2026-10-28 |
| B3 | Review the 8 Metabase-era ingest views for purpose and replacement. Result: keep all eight. Patch warnings, reboot and activity-failure trends, MANUAL age and Ninja device health are not shown in Operations, so these are backlog gaps. The parity audit is corrected | [review](../records/PLAN-022-legacy-cleanup/metabase-view-capability-review.md), L21 | done |
| B4 | Hand off items that are live data or redesigns, not cleanup (below) | | done |

`parity_report` is not exported (user, 2026-10-28): it held only legacy-versus-Operations
comparison counts for a cutover that is complete.

### Handed off (2026-10-28)

- `ninja_core` staging tables (`devices` and the rest) and the `*_shadow`
  compatibility views, which are still read → PLAN-007.
- `ninja_core.run_log` and `operations.run_log` → PLAN-005.
- `ninja_activities.activities` retention (7.0 GB, 774k rows, live) → root
  backlog.
- The SQL migration track and `ninja_core.schema_migrations` → root backlog.
- Root `TODO.md` historical sections → root backlog (its header already
  defers them). `inventory-scripts/` stays: it is local, git-ignored and
  referenced by ADR 0015. `archive/` retention → root backlog.

### Outcome (2026-10-28)

B1 and B2 shipped in 0.130.0 (`912ee58`, records `f28b59e`). Production
applied `0358` and `0359` at 21:27 UTC (L23). Read-only check (L22):
`parity_report` is gone, no `metabase_ro` role, no source carries
`legacy_job_key`, and no change-history registry row remains. Operations,
the Jobs worker and Postgres report healthy. PLAN-022 is complete.

## Outcome (2026-10-26)

All of Wave A is deployed. Production after 0.129.1: database **28 GB** (was
62.4 GB); the snapshot tables, both legacy schemas and daily presence are
gone; retired Jobs keep 62 runs, 2 disabled schedules and 78 schedule events,
with no recovery policies or approvals. **Incident:** 0.129.0's first `0351`
was refused by the append-only schedule-events trigger, so Operations could
not start from 21:07:38 to about 21:12:25 UTC; ingest and the Jobs worker
stayed up, and the migration rolled back cleanly. Fixed by 0.129.1. Lesson:
before a migration edits rows, check every trigger on the tables it touches.

## Validation so far (2026-10-26)

Images: ingest (also the Jobs worker) and Operations build with the
workstation CA override; inside them the ingest modules import, the
registry validates with 33 Jobs, SQL migrations `117`/`118` are present,
Django `check` is clean and the latest migrations are `0349`–`0351`.
Production read-only (L14–L16): no routine, trigger, event trigger,
policy or other catalog dependency outside the dropped objects references
them. Off-host copy: `archive/plan022-legacy-2026-10-26/` on the operator
workstation (git-ignored), hashes re-verified after copy.

Ingest suite: 519 passed, 5 failed (the same 5 pre-existing failures as
before this work). Operations suite: 556 passed, 4 failed (condition catalog
and admin form, in files this plan does not touch). Jobs registry tests 17
passed; drop-migration Postgres test 4 passed; Django `check` clean, no
missing migrations; `ruff` unchanged from HEAD on every changed file.

## Validation

Ingest and Operations suites (no new failures), Django `check` and
`makemigrations --check`, migration SQL applied on disposable Postgres,
archive table-of-contents check, and after deploy a read-only size check.
