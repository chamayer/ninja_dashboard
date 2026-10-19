# Jobs observability and maintenance cadence (2026-10-19)

## Status

Deployed and verified 2026-10-19 (`15b6cdb`, hotfix `17f7e13`); two follow-ups open (below).

## Goal

Job logs are visible and redacted, a failing job leaves no raw traceback,
the resolver reports what its maintenance work did, the hourly maintenance
inside the resolver really runs at most hourly, and disabled schedules stop
reporting as failures.

## Confirmed causes

- `ingest/jobs_child.py` never configures logging (since `e0bc520`,
  2026-09-29): INFO from every job is discarded; it re-raises, so a raw
  traceback reaches inherited stderr.
- `ingest/logging_utils.py` adds redaction to the root logger; Python does not
  run ancestor logger filters for records from child loggers, so module
  logger output is not redacted in main, worker or child.
- Roaming refresh and shadow naming are throttled in process memory; each
  job is a new process, so both run on every resolver run (~30/day).
- 0244 (`5ae4890`) retired the resolver and four other schedules; the
  terminal-outcome trigger (0227) later overwrote their outcome
  (`stalled`, `cancelled`, `completed`), and `schedule_failure` health
  (0259) reports disabled schedules.

## Scope and decisions

- Redaction on handlers: a formatter that redacts the whole formatted output,
  exception text included, installed on every root handler.
- `jobs_child`: logging to stderr (stdout stays the JSON result protocol);
  failure logs a sanitized exception, prints the redacted error JSON and
  exits nonzero without re-raising.
- Resolver telemetry in the Job result: counts, durations and whether each
  maintenance component ran; no names or raw evidence.
- Migration 0323: tenant-scoped `maintenance_cadence` with atomic
  `claim_maintenance` / `complete_maintenance`; terminal outcomes no longer
  written to disabled schedules; the four 0244-managed schedules repaired to
  `retired`; `schedule_failure` health only for enabled schedules.
- The resolver stays source-triggered; no independent schedule is restored.

## Validation

Logging tests (module-logger redaction, exception text, child failure
protocol), migration 0323 test on production column types (claim atomicity
and interval, trigger on enabled vs disabled, repair, health), resolver
telemetry and cadence tests, focused suites, `git diff --check`. Local commit;
push needs separate approval.

## Checkpoint and next action

2026-10-19: built and committed locally (not pushed). `logging_utils`
redacts the whole formatted output on every root handler; `jobs_child` logs
to stderr (force), reports a redacted error and exits 1 without re-raising,
and `db.init` failures now also produce a result line; the resolver Job
returns aggregate telemetry (observations, promotions, merges, roaming and
shadow naming: ran, seconds, counts; total seconds); migration 0323 adds
`maintenance_cadence` with `claim_maintenance` / `complete_maintenance`,
writes terminal outcomes to enabled schedules only, repairs the four
0244-managed schedules to `retired` (no change history: `last_outcome` is
not a recorded column), and measures `schedule_failure` for enabled
schedules only (the production health function matched 0259 before the
change). Review correction (amended): the cadence functions refuse a missing or mismatched session tenant and component keys over 64 characters; retired schedules are left out of required_disabled while a required schedule switched off is still reported. Validation: new tests 11 ingest + 7 migration 0323 passed; full
suites ingest 11 and Operations 4 failures, the same baseline; Django check
and `makemigrations --check` clean; lint clean; `git diff --check` clean.
Pushed and deployed (`0bdff25`, `15b6cdb`) at 16:55 UTC. Incident: every
resolver run failed from 16:55 to 17:12 — psycopg sent the seconds as double
precision and `complete_maintenance(bigint, text, numeric)` was not found;
the resolution transaction rolled back. Only one run fell in the window (a
manual trigger). Fixed in `17f7e13` (explicit casts; a PostgreSQL test runs
the resolver's own calls and fails on the old code), pushed with the user's
`60d33cd` and deployed 17:12:40. Verified: 0323 applied, services healthy,
the four 0244 schedules `retired`, no `schedule_failure`; run 1 completed
with telemetry (roaming 7 records in 43.3 s, shadow pass 10.5 s, renames
unchanged), run 2 completed with both components skipped (`ran: false`),
job logs visible in the worker log. Open: health still reports six older
replaced schedules as `required_disabled` (agent-observations,
documentation-observations, patches, source-actions, source-demand,
source-demand-recovery; pre-existing, not marked retired); container logs
have no rotation (default json-file). Next: decide those two; collect paced
shadow measurements for the ADR-0034 activation review.

---

# Schedule retirement authority (2026-10-19)

## Status

Active (user approved, "finish it").

## Scope and decisions

- Migration 0324: `jobs_disable_retired_tenant_schedules_v1` (called on every
  scheduler poll) retires every tenant schedule the catalog no longer
  declares: disabled, no next due, `last_outcome = 'retired'`; it changes a
  row only when that state differs (idempotent every minute); an already
  retired row keeps its reason, a newly retired one gets "Retired — no
  longer declared in the Jobs catalog."
- Explicit repair, tenant 1 and scope `tenant:1`, keeping their replacement
  reasons: `patches`, `agent-observations`, `documentation-observations`
  (0263, per-binding source refreshes), `source-demand`,
  `source-demand-recovery` (0266), and the ten reference-data schedules of
  0265 (`intel-nvd` … `intel-endoflife`, per-binding source refreshes; all
  bindings ran in the last 24 h).
- `source-actions` is not retired: capability `pending_work` (enabled while a
  source action is pending), so idle is not "required disabled"; Operations
  capability maps treat it as available for manual runs.

## Validation

Migration 0324 test on production types through the real call
(idempotent second pass returns 0 and adds no history; reason rules; declared
schedules untouched; health: retired absent, a declared required schedule
switched off present, enabled failure present); `_schedule_enabled` and
registry tests; focused suites; local commit, push on approval.

## Checkpoint and next action

2026-10-19: built and committed locally (not pushed): migration 0324, registry
capability `pending_work` for `source-actions` with an explicit pending-work
query map in `operator_job_queue`, Operations capability maps. Production
check before deploy: the only enabled undeclared schedules are the 16
per-binding `source-refresh` schedules (scope `source-binding:…`, excluded);
the undeclared `tenant:1` rows are exactly the 15 repaired plus the 4 already
retired, so the rule's first poll after deploy changes nothing. Validation:
0324 test 3 passed (idempotent second and third pass, no added history,
reason rules, declared and binding schedules untouched, health), pending-work
tests 4 passed; full suites ingest 11 and Operations 4 failures (baseline);
Django checks clean; no new lint findings. Next: push approval; after deploy,
health shows no `required_disabled` for the six, and `source-actions` stays
declared and idle. Then the ADR-0034 activation review.

---

# How a Computer is named — ADR-0034 proposal (2026-10-19)

## Status

ADR-0034 accepted 2026-10-19 (user). Step 1 deployed (`afc9cbe`, migration
0322, verified 2026-10-19). Paused until the Jobs fix above lands; then
correctly paced shadow measurements and the activation review (step 2).

## Goal

Identity owns Computer naming: one on-demand normalization function, record
names as identity evidence, name kinds as data, one explainable naming
function with provenance and a database-enforced single writer, audited
operator rename, identity findings keyed by Computers, and label drift
surfaced. Hostname leaves the generic attribute engine (ADR-0010).

## Fixed decisions (user, 2026-10-19)

- LogMeIn names are editable labels; ScreenConnect reports the real hostname.
- Rethinking ADR-0010/0012 is allowed; the generic engine need not own names.
- Earlier reviews: rank-stale disagreement shown (History, not an issue);
  exact historical-name match precedence with the loose and 15-character
  uniqueness guards; labels may match by name (recorded, reversible); no
  universal "(…)" stripping; explicit storage contract; activation order
  matching before naming; roaming by names needs 5+ names (3 would catch 24
  real renames).
- Re-review (A–F plus refinements): prefer the longer OS name over its
  15-character cut; order `silent_os` before `stable_os`; identity findings
  keyed by Computer IDs with an in-place rekey; normalization on demand (no
  columns, trigger or backfill on `entity_observation_current`); immediate
  scoped recomputation plus a full set-based reconciliation each resolver
  cycle (no queue); guard trigger tied to a dedicated no-login writer role
  (not a session setting); label drift last and optional; query-plan check for
  the historical-name tier; time the complete shadow reconciliation; show the
  10 retired Hudu-driven renames at activation review.

## Affected files

- `operations/docs/decisions/0034-how-a-computer-is-named.md` (accepted).
- Step 1: `operations/apps/core/migrations/0322_*`, its migration test,
  `ingest/evaluator.py` (unclassified producer) and its test.

## Step 1 (deployed)

Scope: `record_name_forms()` (SQL, on demand); `source_name_kinds` (global,
covered by change history, seeded per ADR section 2); roaming `basis`
('serials' / 'names', name condition limited to agent records with no usable
serial and no VM UUID in 90 days — neutral for current matching); shadow
`computer_names(uuid[])` with every rule of section 5 including the
15-character preference; a shadow full-fleet reconciliation that compares and
writes nothing; `source_name_kind_unclassified()` with its admin finding type
(policy `conditions-registry-7`) and evaluator producer. No change to
matching, to Computer names or to `entity_observation_current`.

Validation: migration test on production column types running every
operation (forms parity cases, kinds, roaming including the 3-name rename and
VM UUID guards, every naming rule, unclassified function); evaluator producer
test; full suites; then, before activation, the production timing of the
shadow reconciliation and the historical-name query plan. Commit locally;
no push without the separate locking/backfill review.

## Checkpoint and next action

2026-10-19: step 1 pushed (`68172df`, `afc9cbe`) and deployed: 0322 applied,
services healthy, policy `conditions-registry-7`, roaming 5 serial + 2 name
records, no unclassified-name finding. Deployed shadow function: 14.9 s, 39
live renames (17 reporting OS incl. 16 active 15-character expansions and
`cp-re01 → donnarullo`, 3 silent OS, 12 withdrawn OS, 7 labels) and 2
retired. The resolver run's own log lines are invisible (Jobs child logging,
see the Jobs plan above).

Activation review (read-only, 2026-10-19 18:42 UTC; production shadow): 40
live renames and 2 retired. Seven renames would give a Computer a name another
live Computer in the client already holds (lab220-34/21/22 from duplicate
Hudu assets on ctxdesktop065/068 and citrixapp45; utaw-82-mgt03 → utaw-82-mgt;
cp-re01 → donnarullo, a split LogMeIn record; 2march2016vm_retired;
citrixapp36 → citrixappmcs, a clone fragment kept active by a roaming
record). Proposed before activation: a name-collision guard (keep the name,
raise identity review) as an ADR-0034 amendment. gld1: a powered-off VM and
an archived Hudu asset both marked retired (#65189); no record reports
"gld1". Shadow passes 17:13 and 18:20 matched except citrixapp36 (12 → 13
withdrawn-OS renames); a third pass is being captured.

Name-collision guard (user approved 2026-10-19, building): automatic naming
never gives a Computer a name key another live Computer in the client holds
(live = not retired, not merged, pending cleanup included); compared
set-wise against current names and every name proposed in the same pass;
a collision ends only by source cleanup, a real merge or an explicit
name-collision confirmation (not by "confirmed separate"); `kept_collision` keeps the rejected
name, rule, record and conflicting Computer IDs; the hourly shadow pass
stores collisions in `computer_name_collisions` and identity findings raise a
review-only `computer_name_collision` issue per group keyed by sorted
Computer IDs (no Merge or Confirm-separate; the server refuses both),
resolving when the collision is gone. No uniqueness constraint. Acceptance:
exactly 33 live and 2 retired renames; seven collisions kept and visible.
Built and committed locally (not pushed): migration 0325 (guard in
`computer_names`, extended evidence columns, `computer_name_shadow` outcome
`collision`, `computer_name_collisions` + `refresh_computer_name_collisions`),
resolver shadow pass refreshes collisions, identity findings raise one
review-only issue per collision group keyed by sorted Computer IDs, ADR-0034
section 5a. Review correction (amended): own finding type
`computer_name_collision` (policy `conditions-registry-8`) without actions;
`identity_separate` no longer bypasses the guard; explicit
`name_collision_confirmed`. Validation: 0325 test 9 passed (key comparison,
pending cleanup live, retired and other client not, set-wise two-way, scoped
call equals the pass, confirmed separate does not permit, only an explicit
confirmation for that name does, a real merge ends it, operator confirmation,
type and policy registration, tenant-scoped refresh), action tests 3 passed,
ingest collision and maintenance tests 8 passed; full suites at baseline (11
ingest, 4 Operations); Django checks and lint clean. Production read-only
acceptance with the new body: 33 live and 2 retired renames, exactly the 7
expected collisions, 15.3 s.

Decisions for the activation review (user, 2026-10-19): keep labels as
reported after conservative normalization (no global stripping of
"retired", "do not boot" and similar); review the three Citrix/Hudu renames
individually (repair the association or set an operator name; no
Citrix-specific rule); keep Ninja `vm.host` and `network.device` as labels;
keep 30 days, evaluated per record; resolve `gld1` manually before
record-name matching. Order after the Jobs fix: correctly paced shadow
measurements, activation review, the history index as a separate reviewed
`CREATE INDEX CONCURRENTLY` migration, finding re-key and record-name
matching, verify matching, then the naming writer; label drift last.

---

# Computer identity and platform change history (2026-10-16)

## Status

Complete (2026-10-19): workstreams 1–9 shipped through migration 0321
(`6a098bc`) and verified in production; per-table `enforce_action` is in the
backlog. Durable rules:
`docs/decisions/0032-computer-identity-matching-and-merge.md` and
`docs/decisions/0033-every-platform-change-is-recorded.md` (both Accepted
2026-10-16). The sections below record the plan as it was executed, starting
from the lifecycle prerequisite (workstream 6, `725f8ae`, migration 0305).
Replaces the 2026-10-15 version of this plan, whose review-only name matching
was withdrawn after measurement. Absorbs central-work-queue W6 and the
duplicate-record part of W9 (root plan). Figures are read-only production
measurements from 2026-10-15 and 2026-10-16.

## Goal

Every source record belongs to the right Computer, splits heal, wrong merges
can be undone, and every change the platform or an operator makes is recorded
and visible on one full timeline per entity.

## Fixed decisions (user, 2026-10-16)

- An exact name match in the same client attaches automatically. Only a hard
  conflict (usable serial or VM UUID) blocks it. Domain was dropped after
  measurement: sources report it in different forms (3,377 single-serial
  Computers would have conflicted).
- Existing same-name Computers merge automatically only on a shared serial or
  VM UUID; name-only groups get `duplicate_device_records`. A new record
  matching several name-only candidates attaches to the most recently active
  non-conflicting one with that finding; no new Computer (user, after the
  2026-10-16 review).
- Prefer a merged Computer with a recorded reason over a split or duplicate.
  Merges keep the absorbed Computer as a tombstone with a "merged into"
  pointer and are reversible; they extend the existing `_merge_devices`.
- No hold for incomplete records: a record attaches by name at once, and the
  re-check merges when a serial or VM UUID arrives.
- History covers every change made by an automated process or an operator;
  source-reported changes are already recorded. History is stored with its
  entity, grouped by action, and shown on a full timeline that includes
  related entities; a record's history shows on every Computer it was part of.
- The Computer Activity tab becomes History.
- Withdrawn from the 2026-10-15 plan: the automatic allowlist (serial, VM
  UUID, source identity only), review-only name matching, the identity-review
  finding for weak matches, the historical review of the 754 moves (measured:
  every move followed a tombstone of the old Computer, 423 by
  `reconcile_ninja_vmware_guest_duplicates` on 2026-09-10 and 4 by operator
  merges; none shown wrong), and "no new event store for Activity".

## Open decisions

- Decided 2026-10-16 (ADR-0032): name variants, hard conflicts, same-name
  merges, empty Computers, Ninja BIOS serial, same-source records (the
  2026-07-13 rule, MAC supporting only), withdrawn records as history plus the
  Hudu-only / stopped-VM finding, retired Computers shown in search, Computers
  card links for active / retired / needs review.
- Decided 2026-10-16: automatic retirement only when nothing lists the
  machine (ADR-0032 "Retirement"); cleanup findings for what is still listed.
  Silent agents use the single offline setting already shipped (D1, W4/W5);
  monitoring/network records count like agents.
- Decided 2026-10-16: ADR-0032 and ADR-0033 accepted.
- Decided 2026-10-16: Hudu duplicates = two or more current same-name assets
  in a client without differing serials; archived beside current = replaced,
  not a duplicate.
- Decided 2026-10-16: Hudu documentation is required. Add a Hudu
  `cmdb.asset` requirement to the requirement profiles (presence already holds
  5,056 Hudu rows, so `missing_required_platform` can evaluate it); code
  change: an archived Hudu asset does not satisfy the requirement. About 262
  running Computers have no Hudu asset today.
- Coverage-registry exemptions (queues, heartbeats, locks, dirty flags):
  presented for approval before enforcement.
- Decided 2026-10-16: `audit_log` is replaced (rows carried into per-entity
  history, table read-only and kept); history scope A out / B exempt / C
  recorded incl. finding detail changes; readiness and servicing exempt.
- Decided 2026-10-16: `cve_match` changes are recorded on the product
  timeline.

## Workstreams

### 1. Measurements before building
- Daily change rate per Operations table (history volume).
- Measured 2026-10-16: 91 empty Computers (no active records), all
  `pending_cleanup`.
- Measured and decided 2026-10-16: withdrawn records are history, linked to
  a same-source re-registration (1,477 of 2,542 open withdrawn findings).
- Lifecycle oscillation: diagnosed and fixed (workstream 6).
- History scope: list every table the platform or an operator changes,
  including any outside the `operations` schema, with its recorded-column
  allowlist, secret and restricted columns, and tenant or global scope
  (ADR-0033 "Security and scope of history").
- Dry-run lists for remediation (workstream 5).

Workstream 1 results (2026-10-16, read-only): Postgres has no statistics
reset date, so rates come from counter snapshots. The heaviest writers
rewrite rows without changing meaning (`findings` about 8,000 updates per
evaluator burst, `job_schedules` run bookkeeping, `devices` cache
re-stamps), so the trigger records only allowlisted columns and skips
no-op updates. Finding details are mostly stable; volatile ones change at
most daily. All 155 `operations` tables are classified (78 covered); Django's
auth tables live in `operations`, so one schema is the whole scope. Every
connection logs in as one role with no `application_name`, so ingest and
Operations now set `ingest` / `operations` to name the implicit writer.
`cve_match` is rebuilt by delete and re-insert and records its real
differences from the matcher.

### 2. Change history foundation (ADR-0033) — built 2026-10-16
- Migration 0306: `change_actions`, `begin_change`, `record_change` trigger,
  registry with 155 rows, 78 `<table>_change_history` tables,
  `record_cve_match_changes`, `change_history_unclassified()` and its admin
  finding type (policy `conditions-registry-2`); evaluator producer
  `_evaluate_change_history_registry`. Tests: `test_migration_0306_postgres.py`
  (production types, runtime roles, secrets, RLS, enforcement, cve_match).
  The old lifecycle Postgres test harness repaired (production findings index,
  `evaluator_config`).
- Action table and `operations.begin_change(...)`; trigger function that
  writes per-entity history and rejects changes without an action; coverage
  registry and its test; append-only grants.
- First covered tables: `devices`, `entity_source_links` (action reference on
  its existing history), the merge relation.

### 3. Identity inputs and matching (ADR-0032) — built 2026-10-16
- Done: Ninja BIOS serial unless a placeholder (`_ninja_serial`); matcher
  rewrite (`resolve_match`: live candidates, empty ones as fallback, serial and
  VM UUID from active records, name variants, hard conflicts, most recently
  active choice); promotion matches every machine group in turn (no "kept
  separate" Computers; MAC no longer proof); migration 0307 policy data and
  constraint, recorded as one explicit action. Tests:
  `test_identity_matching_postgres.py` (10), `test_migration_0307_postgres.py`.
- Remaining here: the link evidence (matching rule and compared values on
  links) moves with workstream 4's merge relation.
- Incident 2026-10-16: 0306's finding-type insert omitted NOT NULL columns and
  crash-looped Operations; fixed in `e29ed42`, test now runs the RunPython step.
- Ninja BIOS serial first (`ingest/source_observations.py:320`,
  `ingest/core/devices.py:196`).
- Name normalization: 15-character prefix rule and separator-insensitive
  comparison.
- LogMeIn `last_seen_at` is mapped from `hostStateChangeDate`
  (`ingest/connectors/logmein.py:123`), the last online/offline change, not a
  last-seen time; map it to a correctly named field and keep `is_online` as
  the liveness signal. Measured: 627 online hosts carry a state change older
  than 7 days; 503 hosts are offline for more than 7 days.
- `ingest/identity/matching.py`: live-Computer counting; serial matched
  against active records' current values, not `canonical_serial`; hard
  conflicts from `blocking_signal_keys` (`serial`, `vm_uuid`);
  same-source records no longer block.
- `ingest/identity/resolver.py`: every record through matching (no
  `_promote_entry_groups` shortcut); step 5 merge of conflict-free same-name
  Computers.
- Validated link writer for every link change, including
  `sync_entity_source_links_from_observations`, `ingest/source_events.py`
  withdrawal updates and `entity_candidate_decisions.py`; pre-rule rows marked
  by migration.

### 4. Re-check, merge and split — 4a built 2026-10-16
- 4a done: migration 0308 (`computer_merges`, `merge_computers`,
  `split_computer_merge`, merge-relation guard); operator merge pages call the
  shared function; resolver `merge_proven_splits` merges Computers proven one
  machine (same serial or VM UUID from agent/VM records; never a Computer
  holding two machines, never two live installs of one source, never on a
  documentation serial). Production dry run 2026-10-16: 26 merges reviewed
  (6 excluded by those guards: Delfasco two machines, two clone pairs, two
  Hudu-only serials, one renamed pair online in both).
- 4b built 2026-10-16 (uncommitted until 4a's first merges are verified):
  migration 0309 (`two_machines_on_one_computer`, policy
  `conditions-registry-3` reactivating `duplicate_device_records`, reworded
  types, decision dimensions `identity_separate` / `identity_excluded_records`,
  `split_computer_records`, `confirm_computers_separate`, old-keyed
  `duplicate_platform_record` rows closed with a reason);
  `ingest/identity/findings.py` (two machines with a proposed split; name-only
  groups, with proven-different pairs listed); `shared_serial` from active
  records with measured assessments; `duplicate_platform_record` per Computer
  (Hudu: same layout and name, no differing serials); matcher and automatic
  merges respect operator decisions; Issues actions Merge these Computers,
  Confirm separate machines, Split as proposed (`identity_actions.py`).
  Production dry run (read-only): 9 two-machine Computers (8 by serial, 1 by
  name), 31 name-only groups (92 Computers, before the 26 automatic merges).
- Re-check when a record's serial or VM UUID first appears or changes.
- Merge relation and one merge operation for automatic and operator merges,
  extended from `views.py` `_merge_devices` (findings, participants and
  software move to the survivor, tombstone gains a "merged into" pointer);
  split action; reconcile with the existing merge-candidate queue (53 open);
  stored name and serial projected from active records.
- Findings: Computer split, two machines on one Computer, ambiguous name,
  incomplete source record (24 hours), empty Computer; existing
  `identity_conflict` and `duplicate_platform_record` kept.

### 5. Retirement, evidence and remediation
- 4b shipped as `b9937b9` (0309 applied 2026-10-16 23:14; JIT off for
  `compute_finding_state`, policy registry-3, 92 old duplicate rows closed).
  Its merge-signature fix lets the automatic merges run on the next resolver.
- 5a built: `ingest/computer_listing.py` states drive lifecycle and findings;
  migration 0310 (lifecycles `documentation` / `stopped` as mapping rows,
  `archived_but_reporting`, policy registry-4). Measured states (read-only,
  2026-10-16): 152 retire, 66 documentation only, 127 stopped VM only,
  104 archived but still listed, 42 archived but reporting, 656 silent.
- 5a `a58587e`, 5b `ae410df` (0311 "Still in use" / `in_use_confirmed`), 5c
  `81dd85b` (0312 Hudu requirement) pushed and applied 2026-10-16 23:28–23:34.
- 5d (retire `device_source_record_withdrawn`) waits for the first evaluator
  run after 5a–5c: pre-run check (`scratchpad verify_withdrawn.sql`) found 334
  open withdrawals of required sources on 77 Computers covered by nothing.
- Workstream 7 done locally: search over every record (`f572141`), Computers
  card links, name projection with vm.guest ineligible (`8387d51`, 0313;
  dry run 154 renames, 23 labels kept).
- Workstream 9 done locally: History tab (`ba11885`, 0314
  `computer_history`; `3e6fe91` adds audit_log rows).
- Found and fixed (`2dbfcf2`, 0315): merges left source links on the
  tombstone; relationship projection failed every batch since the first
  automatic merges. Remediation moves the 18 links, retires 28 edges.
- Workstream 8 remaining: move audit_log writers (lifecycle transitions,
  `views._audit`) to explicit change actions, then `enforce_action` and
  make `audit_log` read-only.
- 26 Computers whose record serial is stored on another Computer; 13
  complementary same-name groups (36 Computers); 30 conflict-free same-name
  live groups (20 share one serial, 10 have no serial at all); 2 two-machine
  Computers to split (GF-12/GF-32, DEL-PC01/DEL-LT1); 91 empty Computers.
- Each dry-run list reviewed before the merges run.

### 6. Lifecycle oscillation fix (shipped 2026-10-16 as `725f8ae`; deployment verified)
- Cause: `_sync_source_withdrawal_lifecycle` forced `active` whenever a record
  was listed, and `_sync_lifecycle_status` reverted it in the same run (two
  opposite `audit_log` rows per run, ~1,050 Computers).
- Fix: `ingest/evaluator.py` applies the contact policy inside the withdrawal
  step (shared `_load_lifecycle_evidence`, `_device_lifecycle_target`); one
  transition at most. Test:
  `ingest/tests/test_evaluator_lifecycle_single_transition_postgres.py` (fails
  on the old code, passes on the fix).
- Cleanup (user: delete, no need to keep): migration 0305 removes 485,220
  opposite-pair rows, merges 286 two-step transitions, records one
  `audit_log.cleanup` row. Test: `test_migration_0305_postgres.py` (runs as
  the forced-RLS owner). Production dry run matched the counts.
- After deploy: verify no new same-run pairs and count residue written by the
  old ingest code between migration and ingest restart.
- Known pre-existing failure: `ingest/tests/test_evaluator_lifecycle_postgres.py`
  fails on unmodified HEAD (its hand schema lacks `evaluator_config` and the
  condition-policy tables the lifecycle findings now require).

### 7. Carried from the 2026-10-15 plan (approved, to re-verify against ADR-0032)
- Withdrawn-record finding correction (`ingest/evaluator.py` ~1691) — see
  open decision.
- Duplicate-agent cardinality per source and type: SentinelOne `agent.edr`
  (14 Computers with two agents on one serial, both reporting; the other 2 of
  the 16 are the two-machine Computers above), ScreenConnect `agent.remote_access` (9), Ninja `agent.rmm`
  (3); Hudu `cmdb.asset` (225 Computers) not enabled until measured.
- Ninja `vm.guest` ineligible for hostname selection; dry run of the 181
  substantive name changes before projection.
- Search over structured identity data (current and historical), each
  Computer once with what matched.

### 8. History coverage rollout (ADR-0033)
- Findings and admin findings, clients and mappings, policies and
  configuration, software decisions, users and permissions, projected values.

### 9. History page
- Rename Activity to History; full timeline across all records ever attached,
  related entities, merged Computers; period marking; grouping by action;
  filters by origin; keyset paging. Today it reads only the first Ninja
  record (`views.py` `device_detail`).

## Validation

- Resolver tests per matching step and hard conflict; merge, split and
  re-check tests; finding tests including placeholder and Ninja-field
  exclusions.
- History trigger, registry and timeline tests; migration tests on production
  column types.
- Dry-run reports reviewed before remediation; request smoke checks for
  History; Django checks, ruff, `git diff --check`.

## Rollout order

1 measurements → 2 history foundation → 3 matching → 4 re-check, merge,
split → 5 remediation → 6 lifecycle fix → 7 carried items → 8 history
coverage → 9 History page. Each step is its own commit; migrations reviewed
before each push.

## Checkpoint and next action

2026-10-18: workstreams shipped through 0320. 0317 (`74dda37`) fixed the
44-hour source-refresh outage caused by 0315 leaving moved links' history open;
0318 (`b255b6d`) ignores roaming image agents and split the Citrix merge;
0319 (`430ead9`) moved writes from audit_log into the change history.
Follow-up review direction: no new class for listing-only Computers and no
broader automatic merge rule. Unknown OS now raises one `os_unknown_coverage`
finding instead of skipping requirements (0320, `b87c9d9`). Name-only
duplicate groups stay manual (operator). Pre-existing test failures remain the
same (11 ingest, 4 Operations); `human_labels.py` had ruff-format drift
before this work. Next: verify the 0320 deploy and the finding count.

2026-10-16 19:20 UTC: shipped `c4ed359`, `e29ed42`, `0b7af48`, `a44a834`
(0306–0308 applied). Waiting for the first resolver run after 0308 to verify
the automatic merges (about 26 expected); then commit and push 4b (0309), then
workstream 5. Pre-existing test failures (same on HEAD): 11 ingest, 4
Operations (condition catalog counts, admin form import).

Earlier: ADR-0032 and ADR-0033 accepted (design commit `e778ef1`);
lifecycle fix and migration 0305 pushed as `725f8ae` (deployment
unverified). External review the same day: split semantics narrowed, history
security and scope rules added, cleanup states given named finding types,
documentation state reconciled, name-only merges now go to a finding (user
decision) — all uncommitted. Deployment of 0305 verified 2026-10-16 18:03:
485,220 removed, 286 merged, 4,707 lifecycle rows left, first evaluator run
after deploy wrote 0 opposite pairs. Next: workstream 1 measurements, then
the history foundation.

---

# Admin Health intervention experience (2026-10-12)

## Status

Release `7b11501` is deployed through normal GitOps. The change refactors the existing Admin Health page into the administrator
intervention list without creating a second diagnostics product, changing the
Admin navigation, or introducing another health authority.

## Goal, scope, and fixed decisions

- Keep the deployed Admin navigation: Overview, Data, Sources, Jobs, Health,
  and Settings.
- Preserve all existing health evidence, history, technical detail, and
  controls. The normal presentation becomes plain-language; technical
  condition/policy/run data remains available in expandable detail.
- Admin Overview remains the short cross-system summary. Admin Health becomes
  the detailed intervention list. Sources, Jobs, Data, Issues, and entity
  pages remain their existing authorities.
- Reuse the current `AdminFinding`, source-health, Jobs, and service-health
  projections. Do not add a diagnostics store, schema migration, or a new
  primary page.
- Give each Health item a human summary, impact, recommended next action, and
  direct links to the exact related Source, Job/run, Issues, or settings view
  where the current facts and controls live.
- Close the accepted Patching reporting-parity gap with two client-filtered
  fully-patched percentage breakdowns: device type and operating system. They
  use the existing patching population and fully-patched definition; no new
  dashboard, reporting model, or Metabase calculation is introduced.

## Affected files and validation

- `apps/core/views.py`: normalize presentation metadata for existing Health
  findings and cross-system attention records; add Patching client breakdown
  read data from the existing posture authority.
- `templates/findings_admin_health.html`: replace the raw technical table with
  the intervention list and retained expandable technical evidence.
- Existing Patching view/template and focused tests for client posture
  breakdowns.
- Focused Admin Health/Overview view tests, Django checks, focused lint, and
  `git diff --check`.

## Checkpoint and validation

The deployed navigation and current code were revalidated. Sources owns
collection details and controls; Jobs/Job detail owns run, dependency,
recovery, and technical evidence; Issues and device detail provide
operator/source context. Admin Health now gives every existing `AdminFinding`
a plain-language title, impact, recommended action, and direct contextual
links, while retaining the condition key, policy assessment, and raw evidence
under expandable technical details.

The Patching client view now supplies the two audited missing views: fully
patched percentages by device type and operating system, with direct device
drill-through. The definition is shared with the temporary Metabase bootstrap
contract in `shared/patch_compliance.py`, so the two surfaces cannot silently
use different missing-patch status/category rules.

Validated locally: focused Jobs/findings tests (65 passed), Django system
checks, template loading, focused lint, Dockerfile packaging review, and diff
hygiene. No schema migration was included. Commit `7b11501` is pushed to
`origin` and `a-m-rose`; normal GitOps deployed it, and protected Patching and
Admin Health routes return their expected authentication redirect rather than
an error. The separate Metabase retirement release removes its retired Jobs
capability without changing Operations data models or navigation.

---

# Jobs execution stabilization (2026-10-09)

## Status

**Historical (2026-10-15)** — not active, not verified complete. Code landed
in `6a37b3c` (migration 0277); the post-rollout live checks below were not
confirmed here and are carried to the root plan (J1).
Original status: In progress — complete the remaining live Jobs recovery and remove stale work
that can no longer run under the accepted Jobs model. The Metabase reporting
parity audit below is paused at the user's direction while Jobs is completed.

## Goal, scope, and fixed decisions

- A worker replacement is not a Job or source failure. Interrupted safe work
  must recover through its reviewed recovery policy; ordinary later schedule
  ticks must not be represented as a completed retry until they actually run.
- The legacy queued `metabase-bootstrap` Run must be cancelled: bootstrap is
  manual-only and it must never consume normal Jobs capacity.
- Investigate workflow-admission failures from before the current worker
  incarnation and verify that current definition snapshots and later workflow
  admissions are healthy before considering the framework complete.
- Do not use direct row updates, manual deployment, or manual Portainer
  actions. Use only restricted Jobs APIs for any required live transition.

## Current checkpoint and next action

The retry-lineage correction is deployed in `417d56b`: a Retry now preserves
the immutable old Run and uses the current registered definition when its Job
key and scope still match. The obsolete queued `metabase-bootstrap` Run was
cancelled through the restricted Jobs API; it had never started and caused no
Metabase effect.

Live evidence on 2026-10-11 identified the remaining execution defect.
Normal source collection finishes in minutes, but the worker restarted every
time one contained child lost its durable claim, interrupting unrelated
source Runs. The routine classifier also attempted an estate-wide first pass
(585,138 installations across 4,759 devices) under one 90-minute Run; its
existing device slicing was bypassed by broad intelligence targets. Historical
full classifier Runs had the same unbounded shape.

The pending implementation isolates an ownership-lost child rather than
restarting the supervisor; it keeps that Run contained while other claimed
Jobs continue. It selects 25 complete device scopes per classifier Run,
stores target and full-rebuild cursors durably, and requests exactly one
coalesced continuation only after a batch commits. Migration `0277` adds the
cursor state with tenant/RLS enforcement. Focused slicing, worker, registry,
and topology checks passed (20); Django checks, lint, compilation, and diff
hygiene passed. Next: commit/push, verify `0277` applied through GitOps, then
inspect worker restarts, active Run durations, queue drain, and the first
completed classifier batches with the read-only host helper.

---

# Metabase-to-Operations reporting parity audit (2026-10-09)

## Status

Complete — live card-level reporting parity is documented for Patching, Agent
Compliance, and Inventory. The resulting implementation/retirement decisions
remain deliberately separate from this read-only audit.

## Goal, scope, and fixed decisions

The audit proves where every live dashboard card is visibly available in
Operations. It does not recreate Metabase card-for-card, change data models,
or remove any dashboard while the evidence is incomplete.

- Classify every card as **Displayed**, **Consolidated**, **Missing**, or
  **Retire**; record its precise Operations destination where one exists.
- Audit domains in order: Patching, Agent Compliance, then Inventory.
- Patching goes first because it remains an active operator-facing collection
  and Operations now has dedicated overview, evidence, trend, and activity
  pages to verify.
- Agent Compliance is second because it is legacy and disabled; the audit
  establishes what must remain visible before its final retirement.
- Inventory is last because all five live dashboards are already archived;
  confirm that retirement rather than rebuilding it.
- Treat data, execution, and Issue state as Operations authorities. Do not
  add a parallel reporting calculation merely to imitate a legacy card.

## Checklist

- [ ] **Patching:** Ninja Command Center, Client Patch Review, Patch Evidence,
  Device Detail, Device Work Queue, Patch Trends, and Activity Search; include
  archived overall/device-status/utilities cards as explicit retirements.
- [ ] **Agent Compliance:** Command Center, Devices, Org Review, Source
  Health, Debug, Today, Review, Health, Customers, Device Drilldown, Alerts,
  and Setup.
- [ ] **Inventory:** Overview, Devices, Identity Review, Serial Quality, and
  Source Records (all currently archived).
- [ ] Produce a decision-ready matrix: live card, operator intent, exact
  Operations page/URL, classification, and required follow-up.
- [ ] Propose the smallest cohesive Operations refinements only for confirmed
  Missing or insufficiently Consolidated cards.
- [ ] Update the parity audit and retirement decision records after the owner
  accepts the conclusions; implementation requires a separate approved scope.

## Affected files and validation

- `operations/docs/metabase-parity-audit.md` and a new compact card-level
  matrix if needed; no product code in this audit phase.
- Validate against the live Metabase API (dashboard/card metadata only) and
  current Operations routes/templates. Never export dashboard query text,
  credentials, or customer data.

## Current checkpoint and result

Live metadata inspection on 2026-10-12 found seven active Patching dashboards
(89 cards), 12 active Agent Compliance dashboards (69 cards), and five
archived Inventory dashboards (24 named cards). The live card names—not the
older bootstrap enumeration—are the audit authority. The card-level matrix is
now in `operations/docs/metabase-parity-audit.md`, with an operator intent,
exact Operations route, and Displayed/Consolidated/Missing/Retire outcome for
every card.

Patching has one bounded native gap: client-filtered fully-patched percentage
breakdowns by device type and operating system. Patch Evidence, Patch Trends,
and Activity Search are now native Operations surfaces. Agent Compliance has
no recommended replacement build: its useful questions are already
consolidated into coverage, issues, mappings, sources, and configuration; its
legacy delivery/debug cards are retirement candidates. Inventory remains
retired under root ADR-0005. The audit changed no runtime behavior, dashboard,
or production data.

---

# Jobs catalog consolidation (2026-10-09)

## Status

**Historical (2026-10-15)** — not active, not verified complete. Related code
landed in `4411b8a` (0274) and `9fb33bd`; the Jobs-health check after rollout
and the contained-data-claims report are carried to the root plan (J2).
Original status: In progress — consolidate the Jobs control plane around one registry and
validate the deployed scheduler, worker, and active Runs without a manual
deployment.

## Goal, scope, and fixed decisions

The Jobs registry is the only definition authority. A configured source is a
scoped target of the one `source-refresh` Job, never another Job definition.
Runs are factual execution history, and Issues are the existing actionable
exception mechanism. Health is derived from those facts; it is not a separate
catalog or page-owned status model.

- Remove worker and scheduler key catalogs that duplicate the registry.
- Remove the checked JSON inventory as an input/authority; retain focused
  discovery only as a guard against unregistered execution paths.
- Keep source bindings as source-specific configuration and show `Refresh
  <source>` as the scoped execution of `source-refresh`.
- Do not add a migration, alter production data, or manually deploy. Tenant 1
  remains the intentionally current boundary.

## Affected files and validation

- `shared/jobs_registry.py`, `ingest/operator_job_queue.py`, and
  `ingest/main.py`: remove competing execution/schedule key lists.
- `operations/apps/core/views.py`: consume registry definitions directly for
  labels; preserve the existing one-row-per-configured-source presentation.
- Jobs registry/inventory tests and ADR-0027: prove one catalog and document
  the actual model.
- Run focused registry, worker, inventory, and Operations Jobs tests plus
  Django checks and diff hygiene. After an approved commit/push, verify
  deployed scheduler/worker heartbeats, migration state, active Runs, and
  recent worker errors through the read-only helper.

## Current checkpoint

Confirmed duplicate authorities: `EXECUTABLE_JOB_KEYS` in the worker,
`SCHEDULED_OPERATOR_JOB_KEYS` in the scheduler, and `jobs_inventory.json`.
The current source-row projection already produces one operator-facing
`Refresh Hudu`/`Refresh Ninja` row from a binding-scoped `source-refresh` Run;
it must be retained rather than replaced by a second generic row. Next:
remove the duplicate lists and replace inventory equality with registry-backed
execution-path discovery.

The worker and scheduler key lists have been removed, and the static inventory
has been deleted. Jobs detail labels now come straight from registry definitions;
source bindings still project as one visible `Refresh <source>` scoped Run.
Focused registry, discovery, and Jobs UI tests passed (22); Django checks,
Python compilation, and diff hygiene passed. Next: commit and push the
non-migration change, then use the read-only host helper to verify the deployed
scheduler and worker and inspect current Jobs execution evidence.

The deployed catalog consolidation is live (`ed1a02d`): scheduler and worker
are current and no Run created after rollout failed or stalled. Live health
also exposed four obsolete enabled tenant schedules for Jobs that now start
only from prerequisites. This is a catalog-lifecycle defect, not a valid
operator warning, and can create duplicate admission. A forward-only `0274`
migration now provides a restricted reconciliation API; the scheduler disables
only undeclared tenant schedules. Focused checks passed (23) plus Django
checks and diff hygiene. Next: commit/push `0274`, wait for automatic rollout,
then confirm those schedules no longer affect Jobs health and inspect remaining
contained data claims through the restricted diagnostics API.

`0274` is live and correctly disabled the four obsolete schedules. Admin Health
was still counting disabled historical schedules as current, so the final
read-model correction limits its revision warning to enabled schedules. Focused
Jobs checks passed (19) plus Django checks and diff hygiene. Next: commit/push
this display-only correction, verify Jobs health after automatic rollout, and
report any remaining contained data claims as a separate safety condition.

---

# Source-to-analysis workflow scope correction (2026-10-09)

## Status

Complete — declared source-to-tenant follow-up is now admitted and coalesced
without falsely failing completed source collection.

## Goal and fixed decisions

Source refreshes are scoped to a configured source binding. Analysis and
matching Jobs process tenant-wide data. A source refresh must be able to
publish a declared tenant-wide follow-up without making the collection result
look failed.

- A source-refresh successor is explicitly tenant-scoped in the registry;
  its later transitive successors inherit that tenant scope.
- The dependency API permits this one declared source-binding-to-tenant
  transition, while retaining exact same-scope enforcement for inherited
  edges. It never permits an undeclared cross-scope dependency.
- A coalesced tenant-wide successor receives every relevant source revision,
  so collection is complete and analysis runs once after its inputs are ready.

## Scope and validation

- Update the immutable workflow definition metadata and admission scope
  calculation.
- Add a forward-only migration that validates the declared tenant transition.
- Add registry/migration coverage, run focused Jobs tests and standard Django
  checks, then commit and push for the automatic rollout. No manual deployment
  or direct production queue mutation.

## Current checkpoint and validation

Production worker logs confirmed `Jobs revision dependency context is invalid`
from source refresh completion. The active source-binding root attempted to
attach to a coalesced tenant-wide successor; the existing API only permitted
inherited same-scope edges.

The source-refresh registry successors now explicitly use tenant scope. The
new migration permits only that declared transition, checks the dependent is
in the tenant scope, and leaves inherited edges exact-scope-only. Focused
registry, worker, and migration tests passed (19); Django system checks,
compilation, focused lint, and diff hygiene passed. `migrate --plan` could not
complete locally because the workstation's SQLite migration history is far
behind PostgreSQL and its console cannot render an older migration label.
Next: commit and push, then let GitOps apply the forward-only migration and
verify new source completions do not fail workflow admission.

---

# Jobs operator-status correction (2026-10-09)

## Status

Complete — the Jobs list now communicates only operator-relevant status and
does not mislabel service restarts as source failures.

## Goal and fixed decisions

The Jobs list describes the current state and required action for an operator.
It must not expose healthy Scheduler/Worker noise or internal recovery terms.

- Scheduler/Worker are silent while healthy. A processing-service failure is
  shown only when it prevents Jobs from starting, in plain language with its
  diagnostic link.
- Old saved schedule definitions and protected-claim recovery are administrator
  diagnostics, not top-of-page operator alerts. Keep them in Jobs settings.
- A worker restart that interrupts a handler is recorded as a durable failed
  run, but rendered as “Will retry automatically” when its scheduled source
  refresh can safely be requested again. It is not presented as a Hudu,
  LogMeIn, or source failure and does not inflate the action-required count.
- The technical error remains in run history; the list shows only the
  operator-facing explanation and an optional immediate refresh action.

## Scope and validation

- Normalize interrupted-run presentation centrally for both registered Jobs
  and source-refresh rows.
- Hide the normal Job system strip; render a plain-language service warning
  only when Jobs cannot be processed.
- Update focused Jobs tests and validate the live Jobs page after GitOps.

## Current checkpoint and validation

The healthy Scheduler/Worker strip is gone. A service warning appears only
when either required runtime is absent, with a direct link to its diagnostic.
Saved-definition and protected-claim details remain in administrator settings.
The durable run keeps its actual failed status in history, while the Jobs list
recognizes a worker-restart interruption as “Will retry automatically” with a
plain-language explanation and no action-required count.

Validation passed: focused Jobs and Dashboard tests (21), Django checks,
Python compilation, focused Ruff undefined/unused-symbol checks, and diff
hygiene. Next: commit and push, then verify the live Jobs page after GitOps.

---

# Completed Jobs execution view (2026-10-08)

## Status

Complete — every enabled source refresh is restored to Jobs as a scoped
execution row while Sources remains the configuration authority.

## Goal and fixed decisions

Jobs must show all current execution, including each scoped source refresh.
Moving source schedules and source-specific evidence to Sources did not justify
hiding those executions from Jobs.

- Sources owns source configuration, cadence, evidence, and source history.
- Jobs owns the complete execution overview: current state, latest result,
  waiting/running/failed visibility, stop/retry/refresh actions, and filtering.
- A source refresh row is a scoped execution of the registered `source-refresh`
  Job, not a second Job definition or duplicated schedule authority.
- Source rows use the same lifecycle language and table as registered Jobs.
- Legacy source-run results may provide the previous result until that source
  has a native source-refresh result; they never create a second lifecycle.

## Scope and validation

- Add one shared source-execution projection for the Jobs view using source
  bindings and durable Jobs runs.
- Insert source rows into the existing `Refresh Source Data` group and include
  them in search, status, summary, and safe actions.
- Keep source-management links routed to Sources.
- Update focused Jobs tests; run Dashboard/Jobs tests, Django checks,
  compilation, focused Ruff undefined/unused checks, and diff hygiene.
- Commit and push under the user’s live-preview authorization. GitOps owns the
  deployment; do not trigger Portainer manually.

## Current checkpoint and validation

Jobs now combines its 13 operator Job definitions with every enabled source
binding in the existing Refresh Source Data group. Source rows show current
lifecycle, latest result, cadence, previous terminal result while active,
direct source evidence, and safe refresh/cancel/retry controls. They participate
in search, status filters, counts, and bulk cancellation. Sources remains the
only place to change source schedules or inspect source-specific evidence.

Validation passed: focused Jobs and Dashboard tests (20), Django checks,
Python compilation, focused Ruff undefined/unused-symbol checks, and diff
hygiene. Next: commit and push; verify the automatic rollout and both live
Dashboard and Jobs pages without manually invoking Portainer.

---

# Completed Operations ecosystem Dashboard (2026-10-08)

## Status

Complete — the Dashboard is a full operator briefing built from the existing
Issues, domain, client, source, and Jobs authorities.

## Goal and fixed decisions

The main Dashboard answers: “What is happening across MSP Operations, and
where should I go next?” It summarizes the managed estate, actionable Issues,
operating outcomes, client priorities, recent movement, and the reliability of
the underlying data and processing.

- Issues remains the only operator action queue.
- Attention is grouped by root concern/type and shows affected clients and
  subjects; repeated per-device or per-agent findings must not fill the list.
- Patching, Security & coverage, Software, and Inventory are the four visible
  operating areas. Each shows one outcome, actionable Issue volume, affected
  clients, freshness, and a direct drill-through.
- The client portfolio remains on the page and links directly into each
  client/area; no extra preview click is required.
- A compact 24-hour movement section explains what changed.
- Data-source and Jobs reliability is compact supporting context. Service
  instances and technical diagnostics remain under Admin.
- Every displayed count comes from an existing authoritative model or read
  projection; no confidence score or parallel health state is introduced.

## Scope and affected files

- `apps/core/views.py`: grouped attention, area summaries, movement, and
  compact data/processing context.
- `templates/home.html`: full ecosystem information hierarchy and direct
  drill-throughs.
- `apps/core/tests/test_dashboard.py`: enforce the operator briefing contract.
- No schema, migration, queue, schedule, or execution-policy change.

## Steps and validation

1. Reuse and expose the existing domain summaries.
2. Aggregate current Issues by root type with affected-client/subject counts.
3. Add bounded 24-hour opened/resolved/activity totals.
4. Add compact configured-source and Jobs status without diagnostic noise.
5. Rework the template and focused tests.
6. Run focused tests, Django checks, template loading, compilation, and diff
   hygiene; then commit and push under the user’s live-preview authorization.

## Current checkpoint and validation

The page now presents five ecosystem KPIs, grouped root concerns, four
operating-area summaries, the sortable client portfolio, 24-hour movement,
and compact data/processing reliability. Repeated per-computer agent findings
are grouped by Issue type with affected-subject and client counts. Portfolio-
wide software findings remain in global totals without inventing client
attribution. Exact concern links include both their policy-owned Type and Issue
filters. Technical runtime and schedule details remain in Admin.

Validation passed: focused Dashboard and Jobs tests (20), Django checks,
Python compilation, focused Ruff undefined/unused-symbol checks, and diff
hygiene. Next: commit and push the completed operator Dashboard; GitOps owns
the live rollout.

---

# Prior completed operator-surface work (2026-10-08)

## Status

Complete — Admin boundaries, actionable Jobs attention, and the simplified
operator Dashboard are implemented as one coherent surface model.

## Goal and fixed decisions

Jobs lists registered Jobs and their execution state. Sources owns every
individual source's collection schedule, run history, and refresh control. A
source refresh is a scoped execution of one mechanism, not a separate Job.
Disabled notification Jobs remain visible as disabled configuration, and real
failed Jobs remain visible for recovery.
Services reports only live Scheduler and Worker runtimes; historical deployment
instances belong to history, not current health.
Because Services has no independent controls or operator workflow, its health
signal belongs on Jobs and its old URL must remain safe for bookmarks.

## Scope, affected areas, and validation

- Remove per-binding source rows from Jobs; do not invent or backfill generic
  source-run history.
- Retain a compact collection summary and link to Sources as the authority.
- Ensure Jobs counts and filters describe only configured Jobs and their runs.
- Collapse Services to current runtime health and use operator-readable health
  messages; do not surface historical runtime rows as live failures.
- Repair the Admin overview's AuditLog aggregation failure.
- Remove Services from Admin navigation, redirect its legacy route to Jobs,
  and add a compact Jobs system-health strip with direct diagnostic links.
- Make Admin → Data use every enabled source binding, not the five-platform
  aggregate used for high-level health roll-ups.
- Validate focused Jobs tests, Django checks, template loading, compilation,
  and diff hygiene.

## Current checkpoint

The Jobs page had appended one pseudo-Job per source binding. That made the
generic source-refresh transition read as “Not run yet” even where legacy
source data had been collected and downstream analysis completed. Jobs now
shows only its 13 configured Jobs and a compact current-source summary linked
to Sources. The Admin overview failure was also corrected: AuditLog uses
`audit_id`, not `id`, when grouping recent administrator activity. Focused
Jobs/Dashboard tests, Django checks, template loading, compilation, and diff
hygiene pass.
Services now displays one aggregate row for each current Scheduler and Worker
rather than obsolete runtime instances.
Services is now folded into Jobs and `/admin/services/` redirects safely. The
Jobs status strip shows Scheduler/Worker state and routes specific schedule or
recovery attention to its diagnostic section. Admin → Data lists every enabled
source binding. The Dashboard has three distinct entry metrics (Estate, Issues,
Data status), one actionable attention list, and the client map; the ambiguous
change/activity briefing was removed. Focused Jobs/Dashboard tests, Django
checks, template loading, compilation, and diff hygiene pass.

## Dashboard data snapshot expansion (2026-10-08)

## Status

Complete — the Dashboard ordering regression from the snapshot expansion is
corrected and the compact,
operator-readable snapshot of collection, reporting, data freshness, and
matching quality. Issue links remain the only action destination.

## Scope and decision

Use existing source-health, device, and Issue projections. Do not introduce a
parallel data-health score or a new review queue. Each card must show a useful
positive population/coverage measure alongside the Issue count that needs
attention; sources and device pages remain evidence surfaces only.

## Current checkpoint

The four-card snapshot now shows source collection health and current record
volume, device reporting and stale-computer data, and client/Computer matching
coverage. Each supporting measure drills through to its exact Issues scope;
no new action queue or health score was introduced. The matching card used
`clients_connected` before it was assigned, producing a Dashboard 500. The
value is now calculated before the snapshot. Focused Dashboard tests, Django
checks, template loading, and diff hygiene pass.

## Data-quality Issues unification (2026-10-08)

## Status

Complete — Issues is the single operator action queue for data quality;
Sources, Computers, and Jobs provide evidence or controls without becoming
parallel queues.

## Goal and fixed decisions

An operator-facing data-status summary on the main Dashboard may link only to
verified Issue-producing conditions. Sources and Computers remain evidence and
control surfaces; they do not become separate action queues.

- A failed or overdue configured source is a root `source_failure` Issue for
  that exact source binding, not a vague platform-health message.
- Coverage, freshness, matching, and derived-status conditions affected by an
  open root source problem are dependency-blocked and do not create or retain
  a competing actionable Issue. The root Issue records the affected scope and
  the suppression reason.
- A source recovery releases that block; dependent conditions are re-evaluated
  from current evidence and become Issues only if the condition remains true.
- Independent evidence is never suppressed: a device with another current
  source, or a condition unrelated to the failed source, remains actionable.
- Existing Finding and condition-assessment contracts are the enforcement
  mechanism. No second data-health model or parallel review list is allowed.

## Scope and validation

Audit the source-refresh lifecycle against source-failure emission, condition
assessments, coverage/freshness/matching evaluators, Issue filters, and
Dashboard links. Extend the source-bound evaluator and dependency evidence as
needed; preserve tenant/RLS scope and immutable source-run history. Validate
root Issue emission, downstream suppression, independent-condition visibility,
recovery/re-evaluation, Dashboard drill-through, focused evaluator/condition
tests, Django checks, and diff hygiene.

## Current checkpoint

Implemented: source collection health now reads the binding-scoped durable
`source-refresh` lifecycle and publishes the root `source_failure` condition
as `source_failure:binding:<id>`. The coverage evaluator no longer skips an
unhealthy platform. It keeps evaluating the affected requirement and records a
blocked collection signal with the root condition key, while client-scoped
source bindings block only their own client. The Dashboard has a compact Data
status section whose cards open exact Issue scopes; source failures render in
Issues as collection problems instead of as record-matching work.

Validation passed: focused source-health, evaluator override, and
condition-safety tests (47); Dashboard, Sources, and Issues view tests (77);
`manage.py check`; template loading; compilation; and diff hygiene. The
broader conditions test suite has two pre-existing stale assertions expecting
54 profile definitions while the checked-in profile contains 61; that mismatch
is outside this change and is recorded for follow-up rather than masking it.

## Source-driven collection

Cross-service implementation is active in the root [source-driven collection
plan](../../.work/plan.md). Operations owns the migration-backed source
schedule/publication read/control surfaces and clear Jobs/Sources presentation;
ingest and shared registry changes are tracked in that root plan.

Checkpoint: source-refresh is now a binding-scoped Jobs definition with
source-owned schedule data and source-specific controls on Sources. Reference
feeds are also source bindings and the Sources page groups the complete
inventory. Pending: expose source-refresh activity consistently from Jobs and
validate the migration contract on the stack.

## Jobs grouping 500 correction (2026-10-08)

## Status

Complete — the rendered row now preserves its registry-owned group metadata.

## Scope and decision

The registry has complete group assignments and the catalog carries them. The
page row must preserve that same metadata before grouping; no fallback or
template inference is appropriate because it could hide an invalid registry
contract.

## Completion evidence

Focused registry and Jobs-page coverage (19 tests), Django checks, focused
Ruff, and `git diff --check` pass. Next: commit and push the single wiring
correction, then verify the deployed Jobs URL.

## Operator Jobs grouping (2026-10-08)

## Status

Complete — the Jobs list is organized by registry-owned, plain-language
purpose without creating a second workflow, lifecycle, or governance model.

## Scope and decision

The registry owns each visible Job's operator group, so the view does not
infer purpose from schedules, resource claims, or current state. The Jobs page
will retain one set of columns, filters, status summaries, and controls; it
will add simple, always-expanded group headings in this order:

1. Refresh Source Data
2. Refresh Software Data
3. Refresh Security Data
4. Match Records
5. Analyze Source Information
6. Maintain Operations
7. Send Notifications

Groups explain why an operator would recognize a Job. They do not represent
execution capacity, safety locks, dependency order, or a separate workflow.

## Completion evidence

Focused registry and Jobs-page coverage (19 tests), focused Ruff, Django
checks, and `git diff --check` pass. Next: commit and push the scoped
presentation change under the existing authorization.

## CMDB finding eligibility (2026-10-08)

## Status

Complete — client-level CMDB evaluation now rejects unresolved source scope
before grouping or writing a finding.

## Goal, scope, and decision

Keep source evidence, client matching, and derived findings in their existing
roles. A CMDB evaluator may create a client finding only from evidence with a
resolved client. Evidence without one remains available to the matching path;
it is not silently discarded, and matching is not made a hard job dependency
because it can require an operator decision.

- Scope: `ingest/cmdb_findings.py`, focused contract coverage, and this plan.
- No schema change, Hudu-specific exception, queue change, or production data
  intervention.
- Enforce the invariant in each client-level query, before grouping/upsert,
  so `findings.subject_id` is never passed a null client identifier.

## Completion evidence

Focused CMDB condition-safety coverage (40 tests), Python compilation, focused
Ruff, Django checks, and `git diff --check` pass. The pre-existing import-order
diagnostic in `ingest/cmdb_findings.py` remains outside this narrow change.
Next: commit and push the single corrective change under the existing
authorization; automatic GitOps will roll it out.

## Software-update concurrency contract (2026-10-07)

## Status

**Historical (2026-10-15)** — not active, not verified complete. Later work
(`f1fae45`, `577d611` inventory rebuild, `d058249` classifier removal) may
have overtaken it; whether the writer-only contract exists is carried to the
root plan (J3).
Original status: In progress — replace the conservative whole-run software catalog/inventory
claims with a writer-only contract, while retaining durable execution safety.

## Jobs current-status clarity (2026-10-07)

In progress — name the occupied capacity and its running Job(s) directly on
the waiting row, and move a previous terminal result out of current status.
This is a presentation of the existing durable state, not a second queue.

## Goal and scope

Make normal software-status updates coexist with inventory and intelligence
refreshes without allowing stale derived findings or overlapping writes. Keep
one operator-facing Job; do not turn classifier phases into separate Jobs.

- Define resource claims as exclusive publishing ownership, not read access.
  The classifier owns derived software findings and its reconciliation marker;
  inventory and intelligence refreshes retain ownership of their respective
  source domains.
- Make incremental classification bounded and revision-safe: select a stable
  input scope, publish only results still matching that scope, and leave
  changed inputs for the existing targeted follow-up mechanism.
- Ensure repeated schedule ticks coalesce behind an active equivalent run,
  rather than accumulating duplicate work.
- Raise the reviewed Data processing pool from one to two only after the
  writer-only contract has coverage. Do not change production data or queues
  directly; existing immutable active/queued runs drain under their recorded
  definition.

## Affected areas and validation

- `shared/jobs_registry.py`, `ingest/software_findings.py`, the Jobs admission
  contract/migration if needed, focused registry/classifier/queue tests, and
  ADR-0026 because this refines its resource-ownership rule.
- Validate registry snapshots, classifier stale-input and batch behavior,
  coalescing, Django migration discovery/checks, focused Ruff, and diff
  hygiene. Use read-only live evidence only after an approved deployment.

## Current checkpoint and next action

The current running incremental classifier holds `global:software-catalog` and
`tenant:software-inventory` for its full run. It blocks five catalog/inventory
writers and consumes the only Data processing slot. The registry and dispatcher
correctly distinguish capacity from resource claims, but their policy does not
distinguish read access from publishing ownership. Next: trace classifier
publication/marker semantics and implement the revised writer-only contract
without weakening exact-state reconciliation.

Implemented in the working tree: future classifier definitions claim only
`tenant:{tenant_id}:software-findings`; catalog and inventory writers retain
their own locks. Migration 0262 seeds that new capacity-one domain lock and
raises only Data processing to two. Incremental classification now takes a
complete 250-device routine slice while consuming all explicit intelligence
targets, so ordinary change backlogs yield between coalesced runs without
splitting a device's findings. The exact-state marker still refuses to mark an
input changed after selection; a later run retains and reconciles it. Focused
static lint/import checks, compilation, Django checks, migration discovery,
and diff hygiene pass. The focused ingest test could not collect without the
required local Ninja/Postgres environment values. Next: add direct slice
coverage, review the new migration against the Jobs resource constraint, then
commit/push only with the requested deployment authorization.

## Admin overview ownership and snapshot (2026-10-07)

## Status

Complete — the overview builds one health context with one owner per
condition, and Jobs records the actual reason active work cannot start. This
corrects presentation and durable wait evidence without altering source data.

## Scope and decisions

- Build the page context once inside the existing tenant-scoped request
  transaction, so all rendered Jobs values come from the same computed health
  result. Request authentication has already queried PostgreSQL, so it cannot
  safely change transaction isolation inside the view.
- Sources owns `source_failure`: it is evidence that a source collection is
  failed or overdue, including the resulting coverage skip. It must not also
  count as an independent System check.
- Jobs owns Jobs diagnostics; Services owns scheduler/worker liveness; System
  checks contains only remaining platform-health conditions.
- "Recent administrator activity" means user-initiated audit activity. Omit
  automatic lifecycle transitions that carry no operator decision or useful
  summary.

## Affected files and validation

- `apps/core/views.py`, the Admin overview template and focused Jobs/Admin
  tests, plus this continuity plan. No migration or production data change.
- Run focused Jobs/Admin tests, Django checks, focused Ruff, template loading,
  `git diff --check`, then use a read-only rollout check to prove the rendered
  overview returns one coherent Jobs count and no duplicate source-failure
  System conditions.

## Current checkpoint

Live evidence showed one overview with conflicting Jobs counts and four
`source_failure` platform findings duplicated beside stale-source conditions.
The current active state is three running Jobs, eight capacity waits, and six
prerequisite waits. Focused Jobs/Admin tests (20), Django checks, focused
Ruff, template loading, and `git diff --check` passed before rollout. Commit
`aedbfe6` was pushed to `origin` and `a-m-rose`, but its isolation command
caused a 500 because request authentication had already queried PostgreSQL.
The forward correction removes that invalid command while retaining the shared
computed context, `running_runs`/`ready_runs` consistency, source-failure
ownership, and meaningful activity. Next: validate, push, and confirm the
authenticated overview renders successfully.

Live diagnosis then showed that all eleven waiting runs have valid blockers:
six require upstream output revisions and five conflict with data currently
held by the one running software-classification update. The latter retained a
stale `capacity` category after dispatch found their domain locks unavailable.
Forward migration 0261 will make the dispatcher record `resource` whenever a
domain lock, rather than an execution pool, blocks promotion. The overview
will also group identical user audit actions with a count. Next: validate the
new dispatcher truth rule and concise activity presentation, then deploy and
verify the five runs say another update is finishing first.

The normal Jobs list will not offer Cancel for automatic waiting or Ready
work: those runs are expected to advance automatically and cancelling them
commonly causes their scheduler or dependency request to recreate them. Its
Action column will offer Request stop only for a running Job, Retry for a
failed Job, and Run now only when no active automatic run exists. Cancel
remains an intentional technical control on the individual run detail page.

## Completion evidence

Commit `c1b9f10` was pushed to `origin` and `a-m-rose`. Focused Jobs and
migration tests (12), Django checks, migration discovery, focused Ruff, and
`git diff --check` pass. Read-only rollout validation confirmed migration 0261
is applied and reclassified the five previously stale capacity waits as
resource waits. The live worker now has one processing Job running, five
resource waits, five real processing-capacity waits, and two remaining
upstream-data waits. Schedule cards render a parsed next timestamp and time
until it is due; repeated user actions are grouped.

## Unified Jobs contract (2026-10-07)

## Status

Complete — one lifecycle contract over existing durable records now drives
operator presentation, diagnostics, and health. No second Job, health, queue,
or workflow model was added.

## Goal and fixed design

Five responsibilities use one durable run/schedule/claim/dependency contract:
Data supplies revisions and fixed domain locks; Control defines schedules,
capacity, timeouts, and recovery policy; Execution writes durable state;
Health assesses current behavior against Control expectations; Administration
shows plain-language status and submits audited, safe actions.

- A queued run is Ready only when it has no durable wait category and is within
  the database-enforced Ready bound. Dependency, protected-data, and capacity
  waits remain queued physically but have separate operator lifecycle meaning.
- Extend the existing restricted Jobs diagnostics and health-measurement APIs;
  do not add a parallel summary API. Every consumer uses the same lifecycle
  classification and health thresholds.
- Human-facing status uses `Status`, a named blocking update, and the next
  outcome. Internal terms such as claims, pools, lanes, and protected work are
  administrator detail only.
- Health counts current threshold breaches only. Historic terminal rows and
  ordinary Issues never affect platform health.

## Implementation order

1. Audit and centralize lifecycle classification in the existing Jobs SQL
   contract, with migration-backed compatibility for existing history.
2. Make dispatcher transitions, recovery, diagnostics, and health measurements
   use that contract; prove Ready cannot exceed its bound and blocked work does
   not starve compatible work.
3. Move Jobs, Activity, Admin Health, and the overview to the shared result;
   render named blockers and safe next actions.
4. Reconcile definition drift and contained claims through existing Control and
   recovery policy, then verify live scheduler/worker progress without direct
   queue manipulation.

## Validation and checkpoint

Use focused SQL/migration contention tests, registry/worker tests, Jobs and
Health request/template tests, Django checks, and a read-only live audit of
Ready, Waiting reasons, claims, schedules, and evaluator outcomes. Current
live evidence: raw queued counts are mislabeled Ready; four schedules use old
definitions; contained claims require recovery; and the evaluator failure is
fixed in pushed commit `8861ab9` but awaits automatic rollout.

Implemented in the working tree: `jobs_current_lifecycle_v1` derives current
Ready, Waiting, and Running meanings directly from existing run status and
wait category, with no new table. The existing restricted diagnostics and
health-measurement APIs now call that contract; neither reports physical
queued rows as Ready, and the evaluator no longer recalculates lifecycle data
in Python. Jobs, Activity, Services, and the Admin overview use the same
operator labels and plain-language wait explanations. Focused contract, Jobs,
dispatch, registry, and worker tests (67 total), Django checks, focused lint,
migration discovery, and `git diff --check` pass. Next: commit and push this
forward migration, then use read-only rollout evidence to verify its database
application, current Ready/Waiting counts, scheduler/worker progress, and
health evaluator recovery.

Rollout evidence found a policy-registration gap rather than a capacity-rule
failure: two stalled source runs hold the two external-data slots, although
their handlers have approved replay-safe authorities. Their historical
definition digests were not registered in `job_recovery_policies`, so the
existing reconciler correctly refused to release them. Forward migration 0260
registers only a stalled run that still has a contained claim and an existing
replay-safe authority; the existing worker then performs the audited release.
It does not release unreviewed work or alter run history. Next: validate and
deploy 0260, then prove those claims release and compatible waiting work can
start.

## Completion evidence

- Pushed `113c546` (shared lifecycle contract), `012a2af` (active-lifecycle
  clarification), and `af94b64` (approved interrupted-revision recovery) to
  `origin` and the required `a-m-rose` mirror.
- Local validation: 68 focused Jobs, migration, worker, registry, and
  condition-contract tests pass; `manage.py check`, migration discovery,
  focused Ruff, and `git diff --check` pass.
- Read-only rollout validation: Operations migration 0259 and 0260 are
  applied; Operations, ingest, and Jobs worker are healthy; the scheduler is
  producing due schedules; the two approved contained source runs released;
  three Jobs are running under ordinary capacity claims; the remaining active
  runs report Waiting for capacity or prerequisite data; the latest
  platform-health evaluation completed; and `/admin/jobs/` returns an
  authentication redirect, not a server error.

## Parameter-safe tenant context (2026-10-07)

## Status

Complete in the working tree — all discovered parameterized tenant-context
paths now use PostgreSQL's parameter-safe `set_config(..., TRUE)` form.

## Scope and validation

- Correct the evaluator and all discovered Django/ingest runtime call sites;
  preserve transaction-local RLS semantics and tenant isolation.
- Add a regression assertion for the evaluator. Run focused condition/Jobs
  tests, Django checks, compilation/lint, and `git diff --check`.
- No migration or direct production queue/data manipulation. Validation:
 39 ingest condition tests, 4 focused Jobs tests, Django checks, focused lint,
 compilation, and `git diff --check` pass. After push, automatic deployment
 must prove the evaluator completes.

## Admin overview health hierarchy (2026-10-07)

## Status

Complete in the working tree — System checks now includes only the dedicated
`platform_health` category. Identity/matching rows stay in Issues and cannot
make Operations appear unhealthy.

## Scope and decisions

- Calculate one overall Admin state from existing tenant-scoped source health,
  Jobs diagnostics, service check-ins, and platform-health findings:
  **Healthy**, **Needs attention**, or **Unavailable**.
- Start the overview with that state and four compact KPIs: Jobs needing
  attention, Sources needing attention, Services, and Admin Health. Each KPI
  links to its existing authoritative detail page; no second status model or
  duplicate work queue is introduced.
- Put a prioritized, bounded "Needs attention" list below the KPIs, followed
  by a concise platform summary and recent administrator activity. The page
  is a starting point for action, not a history feed or technical diagnostics.
- Keep "stale" and other Job lifecycle evidence on Jobs. The overview only
  reports an affected Jobs area and links to it.
- Do not count Jobs-specific platform findings again under Admin Health.
  Jobs owns those conditions; Admin Health shows only remaining system
  conditions. Open Issues remain contextual workload, not a platform-health
  KPI.

## Affected areas and validation

- `apps/core/views.py`, `templates/operations_admin_overview.html`, focused
  Admin overview tests, and this continuity plan. No schema change or runtime
  control is required.
- Run focused Admin/Jobs template tests, Django checks, targeted Ruff, and
  `git diff --check`.

## Completion evidence and next action

Implemented `_admin_health_snapshot()` as the shared source of the total
health state, count, domain split, and bounded root-cause list. Jobs owns its
diagnostic conditions, Sources owns stale/failed source conditions, Services
owns missing scheduler/worker check-ins, and System checks owns only dedicated
`platform_health` findings not already owned by Jobs. Identity/matching
`AdminFinding` rows remain in Issues and are deliberately excluded from health.
The overview visibly links any additional root causes beyond its five-row
action list. Admin Health starts with the total and the same four-domain split
before its full condition table. Focused Admin/Jobs tests pass (18), Django
checks pass, focused F/I Ruff passes, and `git diff --check` passes. No
migration or direct production data change is required. Next: push the
validated correction and confirm that the live health total excludes identity
and matching work.

## Admin navigation and surfaces (2026-10-07)

## Status

Complete — the Admin bar now has six clear administration
areas: Overview, Sources, Jobs, Services, Health, and Settings. Outstanding
operator action stays in Issues; Admin contains configuration, service health,
and focused technical administration only.

## Scope and decisions

- Keep the main navigation unchanged. The Admin context bar is the sole
  top-level administration map and contains only Overview, Sources, Jobs,
  Services, Health, and Settings.
- Jobs remains the operational catalogue and run-control page. Its existing
  configuration route becomes a focused configuration/diagnostics child page,
  not a peer in the global Admin bar.
- Add Services as a read-only service-health surface for the scheduler and
  workers. Service lifecycle remains deployment-owned; no start/stop controls
  are added. Link to Jobs diagnostics only for technical investigation.
- Sources is the connection/evidence-health page. Issues is the only queue for
  actionable matching or data-quality work; Sources must not recreate it.
- Health is platform health, not a duplicate Issues inbox. Settings groups
  existing policies and configuration pages; Django Admin remains an advanced
  escape hatch there rather than a global peer.
- Counts appear only for actionable operational work. No badge represents
  inventory volume, historical decisions, or a duplicate queue.
- Preserve existing routes as compatibility deep links, tenant/RLS enforcement,
  and audit-backed mutations. Do not introduce schema changes merely for
  navigation.

## Affected areas and validation

- `templates/base.html`, Admin overview and new Services/Settings templates,
  URL routes, and administrator views/tests.
- Run focused Admin/Jobs template and view tests, Django checks, targeted Ruff,
  template loading, and `git diff --check`. Review all changed routes for
  `require_admin` and existing tenant-aware data access.

## Completion evidence

Implemented the six-area Admin bar and a concise Admin overview. Added
administrator-only Services and Settings pages; Services reports scheduler and
worker check-ins without deployment lifecycle controls, while Settings groups
the existing policy, notification, presentation, and advanced pages. Jobs now
links to Job settings, where catalog, schedules, and capacity are primary and
raw records sit under Diagnostics. Health has a clear name. Removed the
obsolete duplicate Admin strips from focused deep-link pages and retained the
routes themselves. Focused Jobs, Issues, and coverage tests pass (77); Django
checks, targeted Ruff, template loading, and `git diff --check` pass. The
pending commit will contain no migration or production-operation change.

## Admin overview correction (2026-10-07)

## Status

Complete — replaced the link-launcher Admin overview with a compact
at-a-glance operational summary. Links remain follow-up actions, not the
page's primary content.

## Scope and decisions

- Use live, tenant-scoped source health, existing Jobs health diagnostics,
  runtime check-ins, and active platform-health findings. Do not create a
  second queue or duplicate the Jobs and Services detail pages.
- Put a plain-language status and timestamp beside each summary. Show the
  few sources that need attention rather than a long inventory.
- Keep action links contextual: Sources, Jobs, Services, Health, and Issues
  are destinations for investigation or work after the overview identifies a
  condition.

## Completion evidence

The overview now reads only the evidence it renders: tenant-scoped source
health, existing Jobs diagnostics and runtime check-ins, active platform-health
conditions, and the standard Issues count. It shows a timestamped four-area
status summary and an attention section with stale/failed source names, Jobs
and service health explanations, and a single handoff to Issues. Focused Jobs,
Issues, and coverage tests pass (77); Django checks, targeted Ruff, template
loading, and `git diff --check` pass.

## Jobs queue stabilization (2026-10-07)

## Status

**Historical (2026-10-15)** — not active, not verified complete. Later capacity
work (`76d5a20`, `d5be94c`) and the 2026-10-09 stabilization addressed the
same area; the conditional contained-claim recovery is carried to the root
plan (J4).
Original status: In progress — production diagnosis found 17 queued Jobs, no running Jobs, and
six contained resource claims from two interrupted source collectors. The
worker and scheduler have current heartbeats, but the idle worker cannot make
progress because capacity admission is not selecting runnable work.

## Verified cause and decisions

- `agent-observations` and `documentation-observations` were interrupted on
  2026-10-06 during a worker shutdown. Their external-data, emergency-child,
  and source-domain claims were safely contained. Their definition digests do
  not have reviewed replay-safe recovery policies, so automatic release is
  correctly refused.
- `jobs_dispatch_ready_v1` is called by the worker, but it promotes the
  highest-priority dependency-free waiting row without checking whether every
  declared pool and domain resource is available. Claiming immediately marks
  that row waiting again; the same old blocked rows then win promotion, which
  starves runnable control work.
- Correct the dispatcher in the database so Ready promotion uses the same
  atomic resource-availability test as claim admission and skips blocked rows.
  Keep contained claims protected until replay safety is proved and recorded.
- Review both source collectors before adding replay-safe policy. They read
  external sources and write convergent local observations, but the evidence
  must cover the full collector/projector path before it can release live
  contained claims automatically.

## Validation and next action

- Add a forward migration and focused database-contract tests proving blocked
  external work cannot starve runnable control work, plus replay-policy tests
  for each collector if certified.
- Verify automatic deployment and queue drain through read-only diagnostics;
  do not manually deploy or directly alter production claims.

## Implementation checkpoint

Implemented migration 0257, which replaces Ready-window promotion with a
resource-aware scan: it examines each eligible queued run at most once per
dispatch, checks every required capacity pool and domain lock under the same
advisory locks used by claim admission, and promotes only runnable work.
Migration 0258 adds reviewed replay-safe authorities for agent and
documentation observation collection. The registry now snapshots an explicit
recovery posture for all 38 definitions; only reviewed replay-safe definitions
are registered for automatic release. Focused migration/Jobs tests (8), Django
checks, `makemigrations --check`, registry validation, targeted Ruff, and
`git diff --check` pass. Pending rollout review: 0257 only replaces a
security-definer dispatch function; 0258 is idempotent authority data and does
not release claims itself. Worker startup performs the existing audited
recovery after both migrations are present.

## Single Issues inbox and object context (2026-10-07)

## Status

Complete — Issues is the single operator inbox. The same standard Finding
records remain visible on Computers, Software titles, and Clients; pending
source-record matches are represented in the inbox without pretending that a
source identity is a canonical entity.

## Scope and decisions

- An Issue is the only operator-facing actionable item. Object pages provide
  filtered views of that same Issue, never copies with their own state.
- Client matching conditions that concern a known client belong to the Issues
  model and link back to that client. Unattached source groups remain in the
  Issues inbox without inventing a client relationship.
- The record-resolution page remains a focused action surface reached from an
  Issue; it is not a competing navigation destination.
- Keep Sources for connection and mapping-policy configuration. Keep Admin for
  platform configuration and health, not outstanding data-quality work.
- Preserve subject scope, tenant/RLS enforcement, source evidence, and
  operator audit history. Do not convert platform-health findings to Issues.

## Affected areas and validation

- Findings emitter/read paths, candidate/mapping resolution routes, Client,
  Computer, and Software title contextual panels, and navigation counts.
- Add focused migration, queue, and page tests; run relevant pytest, Django
  checks, Ruff, template loading, and diff checks. Verify the deployed surface
  after the approved GitOps push without a manual Portainer deployment.

## Completion evidence

Existing Computer and Software title panels already read standard Findings.
Client source-name conflicts are stored in `admin_findings`, while source
matching has parallel candidate queues; this contradicts the single-inbox
rule. Next: map each open mapping/candidate state to one durable Finding
without duplicating its resolution data, then replace Admin navigation links.

Verified correction: current client-name differences have already been moved
to standard `operations.findings`; only legacy rows remain in
`admin_findings` and are retired by the resolver. Unattached client groups and
topology conflicts deliberately remain `admin_findings` because no single
canonical client is their subject, but the Issues page already reads them.
Generic `entity_candidates` uses `pending` only where an identity-authority
policy permits establishment; `observed_only` is evidence, not operator work.
Implemented: pending generic record matches are counted and rendered in the
existing Issues type group; unresolved client-group issues link directly to
their existing audited candidate-resolution page; the old Client, Entity, and
duplicate-Computer queue routes are compatibility redirects to their
respective Issues views. The Admin navigation no longer links to those queues;
its shortcuts lead to Issues. Client pages show pending records scoped to that
client; Computer and Software title contextual Finding panels already existed.
Focused Issues tests (59), Django checks, targeted Ruff, template loading, and
`git diff --check` pass. An unrelated generic-admin test still fails because
`ConditionPolicyActivationForm` is absent from `apps.core.admin`.

## Jobs administration (2026-10-07)

## Status

**Historical (2026-10-15)** — not active, not verified complete. No commit for
the durable schedule-override contract was found; carried to the root plan
(J5).
Original status: In progress — replace the diagnostic-first Job configuration page with an
 administrator-facing Jobs administration page. It will show each Job's start
 method, current schedule, next run, latest outcome, enablement, capacity, and
 safe controls. Services is a parallel administrator surface for the scheduler
 and workers, not a section inside Jobs. Timer schedules need durable
 administrator overrides; triggered and manual Jobs must say why they have no
 timer rather than appear unconfigured.

## Scope and decisions

- Preserve the scheduler registry as the default policy. Store an explicit
  per-schedule administrator override for pause/resume and cadence so restarts
  and reconciliation do not discard an approved change.
- A disabled capability remains disabled even if its schedule is resumed.
- Retain the restricted SQL boundary: the web application acts only through
  security-definer APIs and records each change in the existing audit log.
- Put read-only technical evidence behind a Diagnostics link; the default page
  is plain-language administration, not a JSON record browser.
- Add a parallel Services surface for Scheduler and Workers with current
  health, heartbeat, queue/capacity impact, and a direct link to diagnostics.
  Do not add unsafe start/stop controls: deployment owns service lifecycle;
  schedule pause/resume remains a Job administrator control.

## Validation and next action

- Add migration/API tests, focused administrator view tests, Django checks,
  and validate persisted overrides through the scheduler after deployment.
- Next: inspect current schedule table constraints and add the durable override
  contract before building the page.

## Jobs list schedule data correction (2026-10-07)

## Status

**Historical (2026-10-15)** — not active, not verified complete. The fix
landed in `f047eab`; the live-page confirmation is carried to the root plan
(J6).
Original status: In progress — the Jobs list used direct reads of the protected schedule table.
The Operations role correctly rejects those reads, but the page caught the
error broadly and erased both schedule and historical-run summaries, producing
false “Run manually” and “Not run yet” results. Use the existing restricted
Jobs diagnostics API for schedule state in both list and detail views.

## Scope and validation

- Preserve table access restrictions; do not add direct grants.
- Keep run and schedule failures independent so one unavailable data source
  cannot erase unrelated truthful status.
- Validate focused Jobs tests, Django checks, and the live operator surface
  after automated deployment.

## Checkpoint and next action

The deployed Operations container reproduced `permission denied for table
job_schedules` under the application role. The corrected views now use
`jobs_admin_diagnostics_v1`, which already has the approved restricted grant.
Focused tests (18), Django check, targeted Ruff, and `git diff --check` pass.
Next: commit/push and confirm the live page receives schedules.

## Hudu terminology (2026-10-06)

## Status

Complete — operator-facing terminology now names the current source as Hudu,
and the Jobs list/detail distinguish automatic, data-triggered, manual-only,
and disabled starts without exposing internal scheduler language.

## Scope and validation

- Update Job names, descriptions, live stage text, and the Jobs coverage
  inventory where they describe the Hudu source or its evaluation.
- Show `Status: …` with a status timestamp and compact result from the last
  completed run. Hide non-actionable technical progress copy and distinguish
  scheduled, data-triggered, manual-only, and disabled Jobs.
- Confirm focused registry and Jobs presentation tests still pass.

## Checkpoint and next action

The registry confirms that the current documentation collector is exclusively
Hudu. The Jobs list now shows `Status: …`, a status timestamp, current
activity, and—while work is active—the last completed outcome. Its schedule
column states the concrete trigger (for example, every hour, after Ninja
refresh, after Hudu refresh, or after vulnerability data refresh) rather than
generic scheduler language. It suppresses the non-actionable measurable-total
message. Focused registry/Jobs tests (18),
`manage.py check`, targeted Ruff import checks, and `git diff --check` passed.
Next: commit and push the reviewed operator-language correction.

## Contained-claim drain and prevention (2026-10-06)

## Status

Complete — the legacy run's four claims were released through the audited
contained-claim recovery API after confirming its worker had stopped. The
dispatcher immediately used the freed capacity for normal Jobs. The apparent
automatic-recovery gap was correctly refusing a newer, unapproved legacy
definition digest; permanently disabling legacy admission removes the source
of recurrence, while the existing replay-safe policy mechanism continues to
recover reviewed current handlers.

## Scope and validation

- Verify the contained run's immutable definition, recovery policy, worker
  reconciliation behavior, and absence of a live handler before releasing it.
- Preserve containment for any handler without explicit replay-safety evidence.
- Validate the live queue drains, recovery evidence is recorded, and focused
  Jobs tests pass. Do not manually deploy.

## Checkpoint and next action

The released run was `45c0b52c-afde-47d9-a764-94b6b2430539`; its originating
worker was recorded stopped. Its digest (`7b1d...`) did not match the only old
legacy replay-safe policy (`2aa2...`), so automated release was intentionally
refused. At recovery, the contained-claim count became zero and the dispatcher
started `intel-matcher`, `software-queue-drain`, and `patches`, each with a
current heartbeat and deadline. Remaining queue entries are ordinary capacity
or prerequisite waits, not stranded protection. No code change beyond the
already-pushed legacy admission shutdown is needed for this incident.

## Legacy Agent compliance shutdown (2026-10-06)

## Status

Complete — commit `26d87da` permanently disables automatic admission for every
legacy definition, and the live schedules were disabled with queued legacy
runs cancelled. The timed-out historical run's contained capacity claims were
intentionally left intact; releasing them remains a separate safety recovery
decision.

## Scope, decision, and validation

- Treat every definition classified by `legacy_job_definition_keys()` as
  retired for automatic scheduling, regardless of the legacy environment
  setting. Definitions and historical evidence remain available for audit.
- Disable the live legacy schedules and cancel only queued legacy runs; do not
  alter running work (none was present) or contained claims.
- Validate the schedule gate with focused tests, then verify live schedules and
  queued legacy runs after the approved GitOps push. No direct Portainer action.

## Checkpoint and next action

Live verification: both durable legacy schedules are disabled with no next due
time and the two queued legacy runs were cancelled. There are no queued or
running legacy Agent compliance runs. The first live transaction was rolled
back on a schema mismatch; a corrected, later transaction succeeded without
releasing contained claims. Focused registry tests (15) and `manage.py check`
passed; targeted Ruff identified only pre-existing style findings in
`operator_job_queue.py`. The commit is pushed to `origin/master` and
`a-m-rose/master` as `26d87da`. Next: if capacity remains blocked, conduct the
separate contained-claim recovery under explicit safety review.

## Status

**Historical (2026-10-15)** — not active, not verified complete. ADR-0027 is
accepted and later Jobs commits (`c1b9f10` and others) followed; its final
validation is carried to the root plan (J7).
Original status: Implementation in progress — ADR-0027 is accepted as the implementation-
independent product and execution model. The Jobs list, Job detail/history,
Job configuration, registry classification, and compatibility redirects are
implemented in the working tree; focused validation is in progress.

## Goal and scope

Replace piecemeal Jobs-page changes with one settled operator model before any
further implementation. The scope is the Jobs information architecture,
operator vocabulary, Job/run/dependency relationship, scheduling and
configuration boundary, capacity presentation, and completion criteria. The
existing durable execution, data-lock, and tenant/RLS contracts are preserved
unless a subsequent approved implementation identifies a concrete defect.

## Authority and decisions

- Design authority: `operations/docs/decisions/0027-jobs-operator-model.md`.
  `operations/docs/jobs-coverage-inventory.md` is a current-implementation
  audit used only to map existing entries into the design.
- ADR-0024 and ADR-0026 remain the execution-safety authorities. The new
  design replaces their operator presentation where they expose lanes,
  Operations/steps, Control plane, or internal wait terminology.
- The main operator surface is a concise Jobs list, with a focused per-Job
  detail/history route. Configuration is Admin > Job configuration. There are
  no artificial subject categories and no generic activity laundry list. Only
  administrator Jobs appear there; technical entries are classified as a Job,
  supporting process, System service, or Legacy entry. A Job is not split
  merely because its handler has multiple stages: Ninja remains one source
  Job, while independent feeds remain independent Jobs.
- ADR-0027 defines one Job -> Run -> Stage model, prerequisite relationships,
  lifecycle, coalescing, capacity, data safety, recovery, tenant safety, Jobs,
  Job detail, configuration, and completion criteria independently of current
  registry and UI structures.

## Implementation scope

- Replace Operation/category presentation with one row per actual Job.
- Centralize Latest status, attention, configuration, and waiting explanation.
- Add one Job-detail route with paginated history and prerequisite context.
- Fold safe bulk actions and explicit refresh controls into Jobs.
- Rename/move Control plane to Admin > Job configuration and expose System
  services through Health/diagnostics.
- Preserve existing URLs as redirects until all internal links move.
- Audit technical registry entries against the Job boundary and remove System
  services from the operator Job catalog without weakening their health
  evidence or execution controls.

## Implementation sequence

1. Define the implementation mapping from current registry entries to Jobs,
   Stages, and System services, with registry validation.
2. Build one shared status/view-model authority and focused tests.
3. Implement Jobs list, controls, refresh, and filtering.
4. Implement Job detail and paginated history.
5. Implement Job configuration/coverage and compatibility redirects.
6. Validate execution invariants, tenant/RLS behavior, templates, and links;
   then commit and push under the existing authorized Jobs workflow without
   invoking Portainer directly. In progress.

## Validation

- Compared current Jobs, Job activity, and control-plane templates and views
  with ADR-0024, ADR-0026, migrations 0255/0256, and the durable plan.
- Preserved unrelated modified templates and untracked diagnostic material.
- Design consistency review remains the next action; implementation validation
  will be defined only after approval.

## Checkpoint and next action

The 38 current registry entries are classified in the coverage inventory. The
boundary rule was rechecked against the Ninja source cycle: its shared source
snapshot and lock justify one Job with detailed stages, not an artificial
split. The working tree now presents one compact Job row per administrator
Job, a per-Job detail/history route, and Job configuration with coverage;
System services and legacy bridges are visible there rather than masquerading
as Jobs. The former Job activity URL redirects into the relevant Job detail,
and old status wording is not rendered. No migration is needed because the
current execution procedure already completes each Job Run independently and
uses durable prerequisite edges for follow-on Jobs.

Focused validation: `PYTHONPATH=.. ..\\.venv\\Scripts\\python.exe -m pytest
apps/core/tests/test_jobs_registry.py apps/core/tests/test_operator_jobs.py
apps/core/tests/test_findings_queue.py -q` passed (75); `PYTHONPATH=.. manage.py
check` passed; focused Ruff
import/undefined-name and format checks passed; `git diff --check` passed.
Next action: commit and push the reviewed implementation only under the
user's separate release authorization; do not invoke Portainer directly.

Follow-up (2026-10-06): clarified the Jobs toolbar after operator review.
`Refresh page` reloads only the displayed list, while `Choose data to refresh`
opens the scoped data-refresh action. Search, status, and the selectable page
refresh rate are grouped under `Find Jobs`.

---

# Admin navigation consistency

## Status

Complete — one operator-facing Admin sub-navigation now renders on every
Admin page, with no page-local duplicate strip.

## Goal and scope

The global Admin context bar in `templates/base.html` is the single navigation
authority. It must expose the same meaningful destinations on Overview,
Sources, mappings, reviews, Jobs, Health, and configuration pages. Remove the
older group-specific `_admin_tabs.html` includes that duplicate or contradict
the global bar. Preserve all URLs and page behavior.

## Validation

- Template compilation and focused navigation tests.
- Confirm all Admin views already provide `admin_group` / `admin_tab` context.

## Validation

`PYTHONPATH=.. python manage.py check` passed. Focused navigation coverage
tests passed: `apps/core/tests/test_coverage.py` (14 passed). `git diff
--check` passed.

---

# Client mapping identity rebuild

## Status

Complete — production data rebuild executed and validated on 2026-09-29.

## Goal

Remove every live source-group-to-client attachment produced by the legacy
compatibility projection, rerun the native resolver, reuse retained legacy
PowerShell aliases as explainable name mappings, and leave every unresolved or
ambiguous source group visible as a candidate and finding.

## Scope and decisions

- Live client-class source links and their observation-derived attachments;
  canonical clients, devices, raw/current evidence, aliases, audit records,
  and historical link evidence remain intact.
- A source link is a derived compatibility projection, not an operator mapping
  authority. Open history intervals are closed before detaching a live link.
- Retained PowerShell aliases are resolver input. They are not copied into
  source evidence or treated as a connector authority.
- The resolver runs only after every organization observation and its grouped
  records are detached, so no old attachment can short-circuit its name ladder.

## Steps

1. Measure active links, alias tiers, decisions, candidates, and grouped
   observations. Complete.
2. Detach live client links and observation assignments under an advisory lock;
   preserve history, reset stale candidate resolution state, then run resolver
   and derived link projection. Complete.
3. Compare reattached, unresolved, and ambiguous groups and their findings;
   correct presentation gaps if found. Complete for the data rebuild.

## Checkpoint

Production baseline: 320 active client source links, all with
`system.compatibility_backfill`; 320 active attached organization observations
and 18 unattached. Alias tiers: 4 manual, 42 seed, 5 alignment. Current mapping
decisions are 37 `legacy_alias` explicit decisions and no operator decisions.
This confirms the displayed unrelated names were inherited compatibility
attachments, not recorded operator choices.

Rebuild result: closed all 320 open client-link history intervals, removed the
320 live client link projections and their 320 dependent attribute-projection
cache rows, detached 320 organization and 18,303 grouped records, then ran the
native resolver. It attached 313 groups and derived 313 new live client links.
It reapplied 37 retained PowerShell-alias decisions against the new link IDs.
25 active groups remain unattached, represented by 15 open candidates and 18
open `client_unattached_group` findings (the difference is expected where
multiple source records normalize to the same candidate or have no usable
name). The earlier 37 legacy decisions remain as immutable orphaned audit
history; the replacement decisions reference current links.

## Next action

The requested rebuild is complete. Before any future intentional reset, make
this audited procedure a versioned operator job rather than repeating an
interactive production operation.

---

# Unified Jobs framework

## Status

**Historical (2026-10-15)** — not active, not verified complete. Later Jobs
plans and ADR-0026/0027 likely supersede this direction; carried to the root
plan for confirmation (J8).
Original status: **Corrective implementation in progress.** Live validation on 2026-09-30
found that an older stalled v1 run retained three `held` resource claims, and
the claim query stopped at a resource-blocked head-of-line row. This prevented
the worker from draining the durable queue and caused schedules whose retained
queued rows used an older immutable definition digest to be repeatedly
deferred. The v1 ledger, durable
schedules, resource-aware isolated workers, domain queue ownership, operator
surfaces, v0 cutover, and registered maintenance work are implemented. The
current slice activates completion dependencies and declared workflow graphs;
remaining work is a requirement-by-requirement audit and correction of any
dishonest handler outcomes, shutdown gaps, or health-surface gaps. ADR-0024's
detailed contract and migration companion remain the design authority.
Preserve unrelated untracked root `.work/probe_*` and bootstrap files.

On 2026-09-28 the user authorized autonomous completion of the Jobs work,
including needed corrections, commits, and pushes. Preserve the unrelated
client-mapping and root `.work` work. The user explicitly prohibited direct
Portainer deployment because deployment is automatic. The latest read-only
production check found the Ninja containers absent and stack 16 inactive, with
its recorded revision still at `a235d6f`; therefore migrations after that
revision and live behavior remain unverified. Do not invoke Portainer.

## Goal

Make every scheduled, automatic, operator-requested, and system-maintenance
operation governed by one Jobs framework. It must safely run independent work
in parallel, serialize conflicting work, expose truthful status and progress,
recover from failures and stalled execution, and explain exactly what an
operator can do next.

The framework is not a replacement for source evidence, findings, source
actions, or domain queues. It is the shared control-plane contract for the
execution of work that owns those domains.

## Confirmed baseline

- `operations.operator_job_runs` is a durable queue for many collection,
  evaluation, intelligence, notification, and maintenance jobs. It has lanes,
  stages, heartbeats, retry/cancel controls, and queue-health reporting.
- Software classification already proves the needed pattern: its three modes
  have a dedicated lane and a mode-supersession policy.
- The Jobs catalog and the durable queue were previously disconnected. Release
  `e6bc64b` corrected the catalog to read queue history first and to label the
  disabled Agent compliance bridge accurately.
- `operations.source_run_queue` is a separate source-demand domain queue. It
  immediately starts daemon threads, has independent lifecycle names, and is
  not visible in the common Job activity page.
- `operations.source_action_requests`, source queue recovery, run-log cleanup,
  platform-health evaluation, and the scheduler itself have no common run
  ledger or consistent operator surface.
- APScheduler schedules are in memory. After a restart their cadence starts
  again, and the UI cannot reliably state next due time, skipped cadence,
  dependency wait, or why work is unavailable.
- A fixed two-thread capacity semaphore and in-process execution mean a slow or
  stuck function can still occupy scarce capacity. Marking its row stalled does
  not stop the Python thread.

## Success criteria

1. Every background operation has exactly one registered definition and an
   unambiguous owner, technical key, plain-language name, description,
   eligibility rule, cadence/trigger, lane, resource/concurrency key,
   dependency policy, timeout, retry policy, progress contract, and run result
   contract.
2. Every invocation receives one durable Job run before work starts. This
   includes scheduler work, Jobs-page requests, targeted refreshes, source
   demand, source actions, and internal maintenance work.
3. The Jobs catalog, Job activity, Admin Health, and API read the same durable
   run and schedule state. `run_log` remains diagnostic evidence, not an
   alternative lifecycle authority.
4. A long, failed, or stalled job cannot silently block unrelated lanes. A
   timeout is detected, shown, contained, and tied to a safe recovery path.
5. Dependencies are explicit. A source refresh never races its required
   resolver/evaluator; a dependent run is shown as waiting rather than simply
   absent.
6. Operators see simple terms: **Queued**, **Running**, **Completed**,
   **Needs attention**, **Cancelled**, **Disabled**, or **Waiting for…**. The
   technical key, stage, correlation ID, raw error, and policy details remain
   available to administrators in the run detail.
7. Existing source data, findings, notification behavior, operator decisions,
   URLs, and retained run history survive the transition. No queue migration
   deletes history or invents successful work.

## Non-goals

- Do not merge source observations, source actions, findings, or audit history
  into one table.
- Do not expose raw internal failures or implementation terms as normal
  operator labels.
- Do not promise a percentage unless the producer supplies an honest total and
  completed count.
- Do not automatically retry external mutations, notifications, or a job whose
  handler is not explicitly idempotent.
- Do not retire Agent compliance or legacy parity schemas in this work. Their
  retirement remains a separately approved destructive transition.

## Architectural decisions to record before implementation

Create ADR-0024, **Unified Jobs execution contract**, before the first
migration. It must lock the following decisions.

### One registry, two consumers

Create a declarative registry in `shared/` so both images can import it:

- Django reads only presentation, permissions, eligibility, and request
  metadata.
- Ingest maps an approved executable handler to the same technical key.
- Registry metadata must not import Django or ingest implementation modules.
- A startup validation compares registry keys, handler keys, schedules, Jobs
  catalog entries, and database schedule rows. Any missing/duplicate key makes
  the service not ready and creates an Admin Health condition after recovery.

Each definition contains at least:

`key`, `display_name`, `technical_name`, `description`, `owner`, `kind`,
`lane`, `resource_keys`, `concurrency_scope`, `priority`, `schedule`,
`capability/enablement`, `request_schema`, `idempotency_scope`,
`supersession_policy`, `dependencies`, `timeout`, `retry_policy`,
`progress_contract`, `result_contract`, `permission`, and `handler_version`.

### One execution ledger, linked domain queues

Keep `operations.operator_job_runs` as the physical durable execution ledger
for compatibility; do not rename it during the first framework release. Add
the fields needed for the generic contract and refer to it as **Job run** in
the UI/API.

Source-demand and source-action rows remain their domain records because they
hold source/action-specific payload and audit semantics. Add a one-to-one or
explicit link to the Job run. This preserves source-specific query paths while
giving every execution one lifecycle, event journal, timeout, and activity
entry.

### Durable schedule state

The registry defines intended cadence; a tenant-scoped schedule-state table
persists `enabled`, `last_requested_at`, `next_due_at`, `last_outcome`, and
the configuration/definition revision. The scheduler becomes a lightweight
leader-elected request producer, not the executor. It creates coalesced Job
runs when due and records why a cadence was skipped or deferred.

### Isolated workers and controlled cancellation

Move execution out of the ingest HTTP/scheduler process into dedicated worker
processes using the same ingest image. A worker claims one Job run, launches a
bounded child execution, and records stage/heartbeat/result. The supervisor
can terminate a timed-out child after a documented grace period without
killing the scheduler or another lane.

Queued work can be cancelled. Running work receives a cooperative cancellation
request at declared safe checkpoints. A worker may force-stop only a handler
that is explicitly marked kill-safe; otherwise it becomes **Needs attention**
after timeout and its resource key remains protected until recovery is
verified. No current handler is presumed kill-safe without review.

### Resources, lanes, dependencies, and supersession

Lanes are capacity and operator-explanation boundaries, not a substitute for
locking. Every Job definition declares resource keys (for example
`db-write`, `ninja-api`, `source:<platform>`, `software-classifier`, or
`notifications`) and a concurrency scope (tenant, client, source, or fleet).
The claim query atomically respects both the lane capacity and held resource
keys.

Dependencies use durable prerequisite requests and material revisions, not
untracked threads. A dependent Job run is queued with a visible reason until
its prerequisite succeeds with the needed freshness/revision. Supersession is
declared per family: a broader run may cancel queued narrower work; it never
silently stops running work.

## Complete inventory and target treatment

| Family | Registered work | Target treatment |
| --- | --- | --- |
| Collection | `patches`, `agent-observations`, `documentation-observations`, source-demand Ninja/SentinelOne/ScreenConnect/LogMeIn/Hudu and future enabled sources | One collection contract per source scope. Source-demand payload remains in `source_run_queue`, linked to its Job run. Serialize the same source/client scope; allow independent sources within proven API/DB capacity. |
| Identity and evaluation | `resolver`, `platform-evaluate`, `patch-classify`, `parity-check` | Explicit dependency/freshness inputs. Resolver and evaluators become separately observable work; no evaluator bypasses the ledger. |
| Software | `software-enqueue-orgs`, `software-queue-drain`, `software-classify-only`, `software-classify-full`, `software-classify` | Retain the current dedicated Software lane and incremental/full/auto-intel supersession. Link inventory batches to the classifier revision they make eligible. |
| Intelligence | `intel-nvd`, `intel-cpe-dict`, `intel-kev`, `intel-epss`, `intel-matcher`, `intel-winget`, `intel-chocolatey`, `intel-capability`, `intel-lolrmm`, `intel-otx`, `intel-abusech`, `intel-endoflife`, `intel-category` | Use bounded intelligence/API resources. Material-change output requests a coalesced dependent full software classification only when its defined inputs changed. |
| Notifications | `notifications-dispatch`, `notifications-digest` | Idempotent dispatch/digest stages with delivery audit links. Retry policy is explicit and never duplicates externally delivered messages. |
| Retention and health | `retention-history`, source queue stale recovery, Jobs stale recovery, run-log stale recovery, platform-health findings | Register as internal maintenance jobs. Show them in Admin Job activity and Health, but do not offer normal operator Run now unless the handler is explicitly safe. |
| Source actions | `source_actions.process_pending` plus individual external source actions | Retain `source_action_requests`; create linked Job runs for processing attempts. Per-action idempotency, retryability, and external correlation are mandatory. |
| Legacy bridge | `agent-compliance`, `agent-compliance-evaluate`, review digest | Register only as an optional legacy capability. When disabled, show Disabled and do not enqueue periodic no-op work. When enabled, run through the same framework and replace its internal resolver thread with a durable dependency. |
| Service/bootstrap | scheduler leader, migration/bootstrap, Metabase bootstrap, HTTP server | Surface health and startup events separately from normal work. Migration/bootstrap is never an operator Run now job. Metabase bootstrap must be explicitly registered as maintenance before it is exposed. |

## Dependency contract

The registry must declare and test this initial graph:

```text
Source collection
  -> client/identity resolution when the source supplies identity signals
  -> required derived refresh/projector
  -> Platform evaluator or CMDB evaluator for the affected scope

Ninja patch collection -> Patch classifier -> Platform evaluator
Software inventory batch -> incremental Software classifier
Intel material change -> coalesced full Software classifier
Identity resolver -> Platform evaluator (affected scope)
Platform evaluator -> notification dispatch remains cadence-driven
Parity check, retention, and health -> independent; never block collection
Agent compliance (only if enabled) -> Identity resolver -> its native successor
```

Each edge must name its freshness input, affected scope, coalescing key, and
failure behavior. A failed prerequisite blocks the dependent run with a plain
reason; it must not run against partial or stale data merely to make a card
look current.

## Data model and migration sequence

All migrations require separate review and explicit production approval.

1. **Registry and schedule state.** Add `operations.job_schedules` and a
   registry-version table or immutable snapshot fields. Store definition key,
   tenant, enabled/capability result, cadence, requested/next-due times, and
   last request/outcome references. Add RLS, ownership, grants, indexes, and
   queue-registry health coverage.
2. **Generic Job-run contract.** Extend `operator_job_runs` with immutable
   definition revision, trigger (`automatic`, `operator`, `dependency`,
   `recovery`), request payload, idempotency key, correlation ID, parent/root
   run IDs, dependency state/reason, cancellation request fields, timeout,
   started/finished resource metadata, structured sanitized result, and
   terminal reason. Backfill only factual defaults for existing rows.
3. **Resource claims and event journal.** Add a tenant-scoped resource-claim
   table and append-only Job event records for requested, deferred, claimed,
   stage, checkpoint, cancellation, retry, timeout, finish, and recovery.
   Enforce append-only writes through role grants/trigger policy; retain the
   current event table only if it can meet that contract.
4. **Domain queue links.** Add nullable Job-run foreign keys to source-demand
   and source-action records. Backfill no fictional links. New work must write
   both records atomically before execution.
5. **Compatibility views/API.** Preserve current Jobs URLs and existing
   status readers during migration. Add stable admin views rather than making
   downstream consumers query mutable table details. Do not delete `run_log`.
6. **Cutover and cleanup.** Remove direct daemon-thread entry points only after
   every registered path and regression test uses the framework. Retire
   obsolete indexes/columns in a later, separately reviewed migration.

## Implementation work packages

## Exact execution order and model selection

Run these steps in order. The assigned agent continues automatically to the
next step after a passing validation. It pauses only at an item marked
**Approval gate**, a genuine design contradiction, a failed safety invariant,
or a validation failure it cannot resolve. Do not substitute a lower-tier
model for a step marked Astra.

| Step | Work | Model and reasoning | Required exit before continuing |
| --- | --- | --- | --- |
| 0.1 | Verify the current branch, plan, Docker packaging, untracked-user-work boundary, and all existing Job/queue tests. | **Luna Medium** | Confirmed baseline and no overwritten user work. |
| 0.2 | Generate the complete machine-checked inventory of scheduler entries, `/run/*` routes, direct threads, queues, handlers, catalog rows, run-log kinds, and consumers. | **Luna Medium** | Inventory is complete; registry-completeness test fails for an intentionally omitted fixture. |
| 0.3 | Run the approved read-only production measurements and summarize durations, depth, duplicate requests, timeouts, deadlocks, and run-log-only history. | **Luna Medium** | Redacted measurement artifact and documented capacity assumptions. |
| 1.1 | Reconcile inventory/measurements with the proposed architecture; decide the exact registry contract, Job-run extensions, schedule-state schema, resource claims, worker isolation, cancellation model, and compatibility path. Write ADR-0024. | **Astra High** | ADR-0024 and migration design are internally consistent and reviewed against RLS, source queues, source actions, and all consumers. |
| 1.2 | Review ADR-0024, the proposed SQL migrations, destructive/compatibility implications, Compose worker topology, and rollback plan. | **Astra High** | **Approval gate:** user explicitly approves the architecture and reviewed migrations before any schema or worker-service change. |
| 2.1 | Implement the shared declarative registry, Django/ingest registry validation, capability model, technical/operator labels, and registry completeness tests. | **Sol High** | Both services load the same definitions; missing, duplicate, or unhandled keys fail readiness/tests. |
| 2.2 | Implement additive schedule-state and generic Job-run migrations, RLS/grants, request/coalescing API, schedule leader election, and migration tests. | **Astra High** | Concurrent request/schedule tests prove idempotency, restart safety, tenant isolation, and no raw-row caller remains. |
| 2.2a | Close the missing Step 2.3 policy inputs: initial deployment/lane capacities, Job resource mapping, priority aging, dependency activation boundary, and supersession policy. | **Astra High** | **Approval gate:** user explicitly approves `jobs-resource-policy-review.md`; no enforcement uses proposed values before approval. |
| 2.3 | Implement atomic resource claims, lane capacity, priority aging, dependency wait/release, and declarative supersession. | **Astra High** | Deadlock, contention, dependency, and Software-mode regression tests pass. |
| 3.1 | Add the worker service/entry point, child-process supervisor, health checks, packaging, and local integration fixture. | **Astra High** | Scheduler/HTTP remain responsive while a test job is running; Compose and Docker review pass. |
| 3.2 | Implement factual progress, checkpoints, cooperative cancellation, timeout/grace, safe kill eligibility, orphan recovery, and retry rules. | **Astra High** | Hang, restart, cancellation, and no-double-execution tests pass without falsely completing a run. |
| 4.1 | Migrate existing durable evaluation, Software, intelligence, notification, and retention handlers to the registry without changing their business results. | **Sol High** | Per-family compatibility and run-history tests pass. |
| 4.2 | Migrate source-demand work from direct daemon threads to linked source Job runs, retaining source queue records and scoped forms. | **Sol High** | Every on-demand source run has linked domain/Job records and no direct execution thread. |
| 4.3 | Link source-action attempts and internal maintenance work to Job runs; apply explicit idempotency and retry contracts. | **Sol High** | Source-action and maintenance failure/retry tests pass. |
| 4.4 | Capability-gate the legacy bridge and replace its resolver thread with a durable dependency when enabled. | **Sol High** | Disabled bridge creates no schedule/run noise; enabled bridge follows the declared dependency graph. |
| 5.1 | Implement and validate the full dependency graph, scope/revision freshness checks, and evaluator/notification recovery safety. | **Astra High** | Failure-injection suite proves no partial data evaluation, premature recovery, or duplicate notification/action. |
| 6.1 | Build the unified Jobs home, activity filters, detail/timeline, plain-language status, safe actions, admin diagnostics, and source/health links. | **Sol High** | Request/UI/permission tests prove every status and link uses the authoritative Job run. |
| 6.2 | Apply visual polish, copy review, accessibility checks, and documentation/runbook updates. | **Luna Medium** | Operator wording is consistent and no internal diagnostics leak to ordinary operators. |
| 7.1 | Run full repository validation, migration/order review, deployment-readiness audit, and a focused code/design review. | **Astra High** | **Approval gate:** user approves commit, push, deployment, and the exact reviewed migrations. |
| 7.2 | After approved rollout, run read-only production reconciliation, health checks, query-plan review, and operator smoke tests. | **Sol High** | Results are recorded; unresolved rollout defects return to their owning step. |
| 7.3 | Review the observation period and approve removal of direct-thread/status compatibility paths, if warranted. | **Astra High** | **Approval gate:** no cleanup or legacy retirement occurs without separate explicit authorization. |

The practical cost-saving rule is simple: Luna does bounded discovery, test,
documentation, and presentation work; Sol implements well-specified code;
Astra owns architecture, migrations, concurrency, worker lifecycle, failure
safety, and final review.

### WP0 — Freeze the catalog and baseline

- Generate a checked-in registry inventory from every APScheduler entry,
  `/run/*` endpoint, direct thread start, queue processor, targeted refresh,
  and startup catch-up.
- For each entry record current handler, owner, source/action tables, run-log
  kind, cadence, current concurrency, maximum observed duration, safe retry,
  cancellation checkpoint, prerequisites, output, and consumer surface.
- Run read-only production measurements for queue depth, duration percentiles,
  duplicate requests, stale runs, deadlocks, source demand, and run-log-only
  activity. Redact customer data from the artifact.
- Add a registry completeness test that fails for any unregistered scheduled
  or HTTP-triggered background handler.

Exit: a reviewed inventory with no unknown background execution path.

### WP1 — ADR, registry, and capability model

- Create ADR-0024 and `shared` registry definitions.
- Define user-facing labels plus short descriptions; retain technical keys in
  admin detail instead of replacing them with vague names.
- Define permissions: ordinary operators request only scoped, safe work;
  administrators request fleet work, retry, cancel queued work, and see raw
  diagnostics; system work has no Run now control unless specifically allowed.
- Define capability checks for disabled source instances, notification flags,
  intel, and legacy Agent compliance. Disabled means not schedulable and has a
  stated reason, not "Never run."

Exit: Django and ingest load one validated definition set without importing one
another's runtime code.

### WP2 — Durable request, schedule, and resource foundations

- Implement reviewed migrations 1–3 above.
- Build transaction-safe request/coalescing APIs used by Django, scheduler,
  dependency triggers, and recovery. Do not let any caller insert raw rows.
- Implement persistent schedule reconciliation with a PostgreSQL advisory-lock
  scheduler leader. It must calculate next due time deterministically across
  restarts, coalesce missed ticks, and never enqueue work solely because a
  container restarted.
- Implement atomic lane/resource claim and release, priority aging, dependency
  waits, and explicit queue position within the relevant lane/resource scope.

Exit: synthetic jobs prove no duplicate claim, no cross-lane starvation, and
correct restart/cadence behavior.

### WP3 — Worker isolation, progress, timeout, and recovery

- Add a dedicated worker entry point/service in Compose using the ingest image;
  verify Docker packaging and health checks.
- Move execution from scheduler threads to the worker supervisor and bounded
  child process model. The scheduler and HTTP server must remain responsive
  during a long job.
- Add progress/checkpoint helpers that record only real stage and count data.
- Implement cancellation request, cooperative checkpoints, timeout/grace,
  terminal **Needs attention**, resource containment, retry eligibility, and
  manual recovery controls.
- Add a startup/restart reconciliation routine that distinguishes an orphaned
  child from a still-live worker before marking a run terminal.

Exit: intentionally hung test handlers do not prevent unrelated collection or
evaluation from progressing, and no false completed state is possible.

### WP4 — Migrate work families in safe dependency order

1. Migrate current `operator_job_runs` families (evaluation, Software,
   intelligence, notification, retention) onto the registry without changing
   their business behavior.
2. Move source demand from daemon threads to linked source Job runs. Preserve
   source queue records, source-specific payload, scoped selector forms, and
   source health semantics.
3. Link source action processing and enforce per-action retry/idempotency.
4. Move internal cleanup/health work to registered maintenance runs.
5. Replace legacy HTTP `/run/*` execution with request creation or a redirect
   to the correct scoped form. Keep compatibility endpoints only while callers
   are audited; they must never create an untracked thread.
6. Gate the Agent compliance bridge by capability. If enabled, migrate its
   resolver follow-up into an explicit dependency; if disabled, do not schedule
   it.

Exit: the completeness test proves every known work family starts through the
framework and all prior direct thread routes are removed or intentionally
disabled.

### WP5 — Dependencies, supersession, and correctness rules

- Implement the dependency graph above using revision/scope evidence, not a
  blanket "run everything" chain.
- Generalize Software mode supersession into declarative per-family policies.
- Define collection and source concurrency by source/client scope and verify
  API rate limits, DB-write load, and resolver/evaluator consistency.
- Make evaluator outcomes safe under retries: no premature recovery, duplicate
  notifications, source action duplication, or loss of operator decisions.
- Add failure injection for deadlocks, database pool exhaustion, source API
  timeout, worker restart, partial source collection, and dependency failure.

Exit: each registered dependency and supersession rule has a direct regression
test and an operator-visible waiting explanation.

### WP6 — Operator and administrator surfaces

- Replace the split Jobs catalog/Job activity status model with one Jobs home:
  compact category summary, registered work list, capability/schedule state,
  and a link to filtered activity.
- Job activity supports all jobs, source/client scope, lane, origin, status,
  owner, correlation/batch, time range, and technical key filters. It includes
  current and historical work without a silent record cap.
- Detail view shows plain status, start/end/elapsed, wait reason, honest
  progress, scope, result, next action, event timeline, safe Retry/Cancel, and
  administrator-only diagnostics/error/correlation data.
- Provide direct links from source health, targeted refresh, source-action
  pages, Admin Health, findings/evaluators, and affected client/device pages to
  the relevant Job run or filtered activity.
- Admin Health emits deduplicated, actionable findings for schedule failure,
  disabled-required work, queue age/depth, repeated failure, timeout, registry
  mismatch, and unmet dependency. Each finding links to its Job detail.

Exit: an operator can answer what is running, what is waiting, why, what it
affects, and what they can safely do in one place.

### WP7 — Cutover, performance, and retirement review

- Run read-only production query-plan/duration review for activity and health
  queries; add only measured indexes/partitioning/retention policy.
- Verify all containers, migrations, scheduler leader, worker health, queue
  health, registry validation, catalog/API behavior, and each job family after
  rollout.
- Run a dual-read reconciliation while old status paths remain: durable Job
  runs versus source queue/run-log evidence must be explained, not silently
  overwritten.
- Remove obsolete direct threads and duplicate status readers only after an
  approved production observation period. Treat Agent compliance retirement as
  a separate destructive project.

Exit: one authoritative execution lifecycle with documented compatibility and
no untracked background work.

## Required tests and validation

- Registry completeness and handler/catalog/schedule parity.
- Tenant/RLS/grant tests for every new table/view and role.
- Request idempotency, concurrent coalescing, lane/resource claim, priority
  aging, dependency wait/release, and supersession tests.
- Scheduler-leader, restart, missed cadence, disabled capability, and next-due
  tests.
- Worker heartbeat, timeout, cooperative cancel, forced-stop eligibility,
  orphan recovery, retry safety, and no-double-execution tests.
- Per-family integration tests for collection, source demand, resolver,
  evaluator, Software, intel, notification, source action, retention, and the
  disabled/enabled legacy bridge.
- UI/API/CSV smoke tests for labels, filters, detail visibility, diagnostics
  permissions, and links.
- Python compilation/import tests, targeted Ruff, Django checks,
  `makemigrations --check`, migration drift/order review, `git diff --check`,
  Compose/Dockerfile review, and full relevant ingest/Operations suites.
- Before production: backup/review of migrations; after production: read-only
  health, queue, schedule, job-family, and query-plan verification.

## Risks and safeguards

| Risk | Safeguard |
| --- | --- |
| Killing a process leaves partial external or database work | Only terminate reviewed kill-safe handlers; all others require cooperative checkpoints and manual recovery. |
| Duplicate work after restart or scheduler race | Durable idempotency keys, advisory leader lock, resource claims, and unique active scopes. |
| One slow job blocks all work | Independent lane workers plus resource-specific limits; use measured capacity rather than global thread count. |
| UI says success without evidence | Completion is written only by the worker after the handler returns a declared result; direct `run_log` is evidence, never lifecycle authority. |
| Source-specific semantics are lost | Keep source/action queues as domain tables and link them to Job runs instead of flattening payloads. |
| Legacy bridge creates no-op noise | Capability-gate it; disabled work does not schedule or expose a run button. |
| Large migration breaks deployed queue | Additive migrations, compatibility readers, factual-only backfills, dual-read observation, and later cleanup. |

## Files expected to change

- New shared registry/contract module and tests under `shared/`.
- `ingest/main.py`, a new scheduler/worker entry point, queue dispatcher,
  source-demand and source-action adapters, config, and ingest tests.
- `operations/apps/core/views.py`, models/migrations, Jobs/Admin Health APIs,
  templates, URLs, permissions, and Operations tests.
- `docker-compose.yml`, ingest Docker entry point/packaging, and operational
  documentation/runbooks.
- `operations/docs/decisions/0024-...`, `operations/docs/architecture.md`,
  `operations/docs/runbooks/`, root `VERSION`, and `CHANGELOG.md` when a
  reviewed implementation release is prepared.

## Handoff instructions

Work packages are sequential gates. The implementation agent must continue to
the next approved work package without pausing after routine edits, tests, or
documentation updates. Pause only for a genuine product decision, a reviewed
migration/production approval boundary, a safety conflict, or a failed
validation that cannot be resolved within the package. Keep this plan current
with confirmed decisions, completed package exits, validation, and the next
action; do not turn it into a transcript.

## Current checkpoint and next action

Repository baseline `e6bc64b`, branch `master`. The plan is modified. Task
artifacts under `shared/`, Operations tests, Operations `.work/`, and the two
ADR-0024 documents remain untracked, not checked in. Unrelated root
`.work/probe_*` and bootstrap files remain untouched. No runtime code,
schema, Compose, or deployment changes occurred in the drafting phase.

The machine-checked inventory is now schema version 2. It scans executable
Python under `ingest/` and `operations/apps/`, excluding tests, migrations,
comments, and docstrings. It records 33 scheduler registrations, 49 route
literals, 34 direct threads, 30 catalog/dispatcher keys, 16 `run_log` calls,
seven qualified queue relations, 17 relation consumers, six direct run-log
writers, startup calls, and follow-up/admission calls. Four focused tests pass,
including independent synthetic source additions and category omission checks.
It still cannot prove configuration-dependent dispatch, transitive SQL writes,
external callers, handler retry/kill safety, or runtime result correctness.
`jobs-handler-audit.md` records those explicit unknowns and the found
partial-success/wrapper hazards. The measurement artifact remains partial as
previously recorded. Source queues lack tenant columns; source-action migration
0160 has a tenant column but no RLS. DESIGN section 5's automatic stale
reset/retry conflicts with the proposed execution containment policy.

Prepared `operations/docs/decisions/0024-unified-jobs-execution-contract.md`
and `0024-unified-jobs-migration-design.md`. They define proposed request and
coalescing identities, snapshots, durable schedules, dependency revisions,
resource containment, worker fencing, domain attempt links, RLS/grants,
read compatibility, cutover, and rollback requirements. DESIGN section 5's
retry/reset policy is explicitly called out for proposed supersession.

Prepared `operations/.work/jobs-schema-preparation.sql` and its review note.
This is exact, rollback-terminated, inert M1/M2 preparation SQL outside the
migration graph: it adds no runtime grants, enables no schedules, and rejects
all nonlegacy contract versions. It covers immutable definition snapshots,
same-tenant request/schedule/tick references, tenant-1 RLS for new tenant
tables, and factual-only preflight checks. It does not provide the later
resource/dependency/domain-link/transition/worker migration set, role audit,
or activation; it has not been executed.

Prepared `operations/.work/jobs-topology-review.md`. The current ingest image
already packages `shared/` and all of `ingest/`, so a future worker module can
use the same image. The current `ingest.main` command cannot be copied as a
worker because it also starts HTTP, schedules, migrations, catch-up, and
bootstrap. A future worker must override its command and inherited HTTP
healthcheck. No replica/capacity/connection numbers were selected.

Added `operations/.work/jobs-measure.sql`: aggregate-only, repeatable-read,
read-only, statement/lock timeouts, stop-on-error, and rollback. Its interrupted
invocation returned initial status and zero active duplicate groups only.
The local tool session is unavailable; remote completion was not verified.
No new complete measurement result is claimed. The report corrects omitted
NVD/OTX/KEV/retention samples and identifies remaining evidence limitations.

Validation is intentionally light per the user's request: source review
against ADR-0012, glossary, DESIGN, queue migrations, current handlers,
Dockerfiles, and entrypoints, plus document-reference and whitespace checks.
No broad test suite, migration execution, or worker exercise was performed.
Focused validation: `pytest apps/core/tests/test_jobs_inventory.py -q` (4
passed), Ruff check/format of that test, Python compile of it, schema-draft
inert/RLS/preparation-constraint static guards, and `git diff --check`.
The inventory checks do not prove tenant isolation or failure recovery. The
earlier missing-`apscheduler` test limitation remains.

The user approved retaining tenant-1 execution initially, requiring
workflow-root completion after required children, and a quiesced cutover with
uncertain work reconciled manually. These are design choices, not migration
or deployment approval. The user approved the step 1.2 architecture and the
reviewed inert M1/M2 migration scope on 2026-09-24. That approval covers the
ADR/migration design, handler audit, preparation SQL/review note, and worker
topology review. It does not authorize executing a migration, enabling a
schedule, adding workers, changing Compose, deployment, or choosing capacities.
Resource/dependency/domain-link enforcement remains specified but intentionally
deferred to later additive migrations. Step 2.1 is complete: added
`shared/jobs_registry.py`, a standard-library-only registry of all 30 current
durable operator-queue definitions and their current catalog/lane/capability/
schedule metadata. Operations builds its static catalog and lane lookup from
the registry; ingest uses it for lane lookup and validates independent handler
and scheduled-key sets before readiness. Capability labels retain the legacy
bridge wording and expose the same disabled state for Intel, notifications,
and software-queue definitions. Resource keys remain empty and retry/kill
metadata explicitly says unreviewed; no metadata is treated as enforcement.

`test_jobs_registry.py` proves registry/catalog/handler/scheduler parity and
rejection of missing, duplicate, and unregistered keys. The machine inventory
continues to verify source-derived catalog/handler coverage after the catalog
moved to `shared/`. Focused validation passed: Python compile; Ruff for the
new/shared tests and registry; import-order review of `views.py`; and
`pytest apps/core/tests/test_jobs_inventory.py apps/core/tests/test_jobs_registry.py
apps/core/tests/test_operator_jobs.py -q` (12 passed). Full Ruff remains out
of scope and reports pre-existing diagnostics in the large views/main/queue
modules; no broad suite was run. `git diff --check` passed.

Step 2.2 began on Astra High. Added Operations migration 0183,
`jobs_contract_preparation`, implementing the approved inert M1/M2 storage:
immutable global definition snapshots; nullable generic Job-run fields and
same-tenant references; request, schedule, and schedule-event tables; forced
tenant-1 RLS; no runtime table/function grants; and checks that permit only
legacy contract version 0 and disabled schedules. It is intentionally
irreversible rather than dropping potential retained ledger history. Added
focused static migration checks. Python compilation and the Jobs focused suite
passed (14 tests); Docker Compose configuration parses with only its existing
obsolete-`version` warning. Local `psql` is unavailable, so no PostgreSQL DDL
or migration execution was performed. No database, deployment, worker, or
Compose state changed.

The user then approved the narrow follow-on activation scope: version-1 Job
admission, enabled schedule state, and explicit `EXECUTE` grants only for
constrained request/coalescing and scheduler-leader APIs. Added Operations
migration 0184, `jobs_admission_and_schedule_apis`. It replaces only the two
preparation guards, adds immutable definition registration, tenant-context
checked request/admission, schedule leader acquire/release, and due-schedule
claim APIs, and grants no direct table access. The request API rejects missing
snapshots, cross-tenant actors, malformed/null inputs, and top-level sensitive
payload keys; it preserves the legacy active-row compatibility fence and
requires conflicting legacy or differently scoped active work to drain.
Schedule claims lock their schedule row and record a single configuration/due
tick event. No schedule rows were seeded or enabled, no definition snapshots
were registered, and no caller was switched to these APIs. Existing version-0
writers remain unchanged for compatibility pending their family migrations;
the current cross-key Software supersession writer cannot be replaced until
the Step 2.3 declarative supersession API exists.

Focused static validation now passes: Python compilation, targeted Ruff
(`E`, `F`, `I`) for migrations/tests, and 17 Jobs migration/registry/queue
tests. `git diff --check` passes (with only existing LF-to-CRLF warnings).
Local `psql` remains unavailable, so neither migration nor a synthetic
PostgreSQL concurrency/RLS test was run. No database, deployment, worker, or
Compose state changed. The user directed that existing version-0 writers stay
through Step 2.3 rather than adding an interim cross-key supersession policy.
Accordingly, the Step 2.2 raw-writer exit means no direct table write may
create a converted version-1 Job; legacy version-0 writers are explicit
compatibility paths, not converted Jobs. Step 2.3 owns their replacement by
the reviewed declarative supersession API.

The Step 2.3 inspection found a plan gap: Step 1.1/1.2 did not close numeric
capacity, resource mapping, priority-aging, or production dependency policy.
The measurements remained partial, `resource_keys` were intentionally empty,
and the topology review explicitly selected no process/connection budget.
Added Step 2.2a and `operations/.work/jobs-resource-policy-review.md` as a
separate approval package. It proposes the evidence-preserving initial ceiling
of two total executions and one per lane, broad tenant-state exclusion, known
global Intel/software-catalog resources, five-minute priority aging capped at
100, generic dependency machinery with no production edges before Step 5.1,
and only the existing Software classifier supersession ordering. These are
proposals, not accepted decisions or active registry values. The user approved
the complete Step 2.2a package on 2026-09-24. Its initial limits, resource
mapping, priority aging, generic-only dependency boundary, and Software-only
supersession policy are now approved Step 2.3 inputs. Current next action:
implement additive enforcement schema and constrained APIs; do not convert
existing version-0 producers or execute any migration.

Step 2.3 implementation has started with migration 0185,
`jobs_claims_and_dependencies`. It adds tenant-scoped lane limits, claim and
dependency storage, policy-revision values, RLS and revokes, and restricted
ingest-only v1 claim/release/dependency APIs. Claims lock every required
resource in sorted identity order, preserve the approved two-slot deployment
limit and one-per-lane limit, use the approved five-minute aging formula, and
create no partial claim when capacity is unavailable. Dependencies reject
cross-version/cycle input, block claim until released, and require a completed
prerequisite to publish the exact output revision. The shared registry now
records the approved resource templates, initial limits, and Software ranks,
but no legacy producer consumes them.

Focused validation passed: Python compilation; targeted Ruff (`E`, `F`, `I`)
for the registry, 0185, and their tests; and 21 focused Jobs migration,
registry, inventory, and queue tests. `git diff --check` passes with only the
existing LF-to-CRLF warnings. Local PostgreSQL remains unavailable, so these
SQL functions have not been executed and concurrency/RLS behavior is not
proven. Current next action: add the converted Software admission API that
uses the approved ranks atomically; retain existing version-0 admission until
the later family conversion.

Recovery checkpoint (2026-09-24): the production Operations container crash-looped
after `6b1ef1f` when migration 0185 attempted to call PostgreSQL `digest()` while
seeding the fixed Jobs resource-policy SHA-256. The production database does not
provide that function. Recovery scope is limited to replacing the runtime hash
calculation with the identical precomputed digest
`6916ebcadd2176ee5710feb3fb2c3ecb65754b2080df47cf005e75309a137275`, adding a
static guard, validating the migration, and issuing an approved recovery push.

Findings correction (2026-09-24): active policy `conditions-taxonomy-6` exposes
Client name differences, but its 49 live records are `AdminFinding` rows while
the Issues queue reads only entity `Finding` rows. The approved scope is to
render Admin-owned findings in the same policy taxonomy and selected-type
Issues result, preserve their distinct ownership/actions, and include their
counts in navigation. Do not convert or duplicate evidence between tables.

Client mapping overhaul (2026-09-24): approved to replace fragmented legacy
client-name handling with a native, single-authority mapping decision model.
Scope: mapping provenance and audit, effective source-to-client mapping read
model, source-to-source comparison evidence, evaluator outcomes for explicit,
automatic, unmapped, ambiguous, split/merged, placeholder, and withdrawn
groups, Admin → Integrations → Client mappings, client reference display, and
findings only for review-required states. Do not add a second authority beside
the current source-link relationship or silently infer split/merge mappings.
Current checkpoint: deployed `14135f5` exposes Admin findings in Issues but
its client-name row lacks source-to-source comparison; local uncommitted row
formatting work must be replaced, not committed. Next action: document the
mapping-state contract/ADR and audit current source-link and legacy alias
provenance before additive schema work.

Mapping decision surface checkpoint (2026-09-25): additive migration 0201,
effective mapping view, Operations Integrations → Client mappings route, and
audited decision action are implemented locally. The action uses a restricted
security-definer database function so the Operations role cannot write the
decision table directly; each decision supersedes the prior current record.
The table now exposes explicit, automatic, ignored, and review states with
  reason/provenance. Source-observation evidence is included in the effective
  view and consumed by both the mappings surface and client references.
  Focused queue/workspace tests, template loading, Django checks, migration
  consistency, and Python compilation pass. Local PostgreSQL is unavailable,
  so migration SQL/RLS/function execution remains unverified. Next action:
  review the migration diff and request approval for one logical commit; do
  not push or deploy without separate approval.

Completion pass (2026-09-25): the prior commit delivered the decision surface
but did not complete every approved evaluator path. Active scope is limited to
the missing legacy-alias bridge and evaluator lifecycle: preserve explicit
manual/seed/alignment aliases as explicit per-source decisions, preserve
source-tier aliases as automatic, clear review findings for intentional
placeholder/excluded/withdrawn evidence, and detect incompatible source-name
topology without changing source links. The evaluator must remain evidence-
driven and may not manufacture split/merge mappings. A new policy taxonomy
version will expose any new review type in the general Issues queue. Validation
will cover migration consistency, resolver tests, and Django checks; local
PostgreSQL execution remains a stated limitation.

Completion checkpoint (2026-09-25): migration 0202 imports enabled legacy
aliases into the decision authority without overriding an existing decision;
manual/seed/alignment aliases become explicit and source-tier aliases become
automatic. The resolver now clears stale name-difference findings when active
evidence is withdrawn or marked placeholder, clears excluded/unmapped reviews,
and emits visible split/duplicate-source-group reviews without altering source
links. Policy taxonomy version 7 exposes the new duplicate-source-group type
under Client source mapping. Django checks, migration consistency, Python
compilation, and 118 focused Conditions/Findings/Workspace tests pass. Local
PostgreSQL is unavailable, so migration SQL, alias backfill, RLS, and evaluator
queries remain unexecuted. Next action: review and request separate approval
for the logical completion commit; do not push or deploy without approval.

Production recovery checkpoint (2026-09-25): automatic deployment of
`adecf55` applied 0201 but Operations crash-looped while 0202 tried to read
the `security_invoker` client-link view as `operations_migrate`, which has no
grant on that view. The migration transaction rolled back. The corrective
migration revision now performs the alias bridge through the owned base
relations and the latest active org observation, preserving the same scoped
join and decision semantics. Next action: validate, commit/push the correction,
then verify the automatic redeploy, migrations, health, and active policy.

Second recovery checkpoint (2026-09-25): the corrected alias bridge executed,
but 0202 then failed to seed its new admin finding type because the production
registry requires non-null `subject_scope`. The row is now seeded with the
existing required registry value (`device`) and explicitly disabled device
exposure; admin findings do not bind device subjects. The migration transaction
rolled back, so the revised 0202 remains safe to retry. Next action: validate,
push the corrective commit, and verify startup/migration completion.

Third recovery checkpoint (2026-09-25): the finding-type seed then exposed a
second production non-null registry column, `suppressed_by_approval`. The new
admin-only mapping finding now explicitly sets it false, alongside the already
explicit non-device exposure setting. The migration transaction again rolled
back, so no partial type, policy, or decision data was retained. Next action:
validate and push this final registry-contract correction, then verify health.

Fourth recovery checkpoint (2026-09-25): production additionally requires a
non-null `drilldown_evidence_key`. The mapping type now supplies the contract's
empty value, correctly leaving device drill-through disabled for an admin-only
finding. The failed transaction rolled back. Next action: validate, deploy the
revised seed, and confirm 0202 completes before activating taxonomy version 7.

Fifth recovery checkpoint (2026-09-25): the finding-type row and bridge now
pass, but the policy creation function requires every registered finding type
to appear in both policy definitions and taxonomy exactly once. The 0202 seed
now adds the matching definition as well as the taxonomy membership. The full
migration remains transactional and rolled back. Next action: validate, push,
and verify successful startup before any policy activation.

Policy activation simplification (2026-09-25): approved to remove the
mandatory separate review gate that prevents a completed policy from becoming
live. Scope: retain validation, the required activation reason, advisory lock,
assessment invalidation, and audit record; remove only the prerequisite review
lookup/function condition and the redundant Django Admin review action. Keep
historical review data intact and do not grant a new role or bypass policy
  validation. Validation: migration consistency, Django checks, targeted policy
  tests, and review of the generated function SQL. Next action: implement the
  additive migration and simplified activation action.

Activation simplification checkpoint (2026-09-25): migration 0203 replaces
the activation function with the same validity check, advisory lock, and
assessment invalidation but no review-table prerequisite. The sole Django
Admin action retains permission and required-reason checks and writes the
activation audit event; the redundant review action is removed. Historical
review data and function remain untouched. Next action: run focused checks,
then request approval to commit and deploy the migration.

Deployment-driven policy checkpoint (2026-09-25): approved to remove the
remaining activation action and reason requirement. Migration 0204 makes the
validated policy-creation function activate the committed version in the same
transaction, retains structural validation, serialization, and assessment
invalidation, and activates already-committed taxonomy 7. The Django Admin
policy form no longer exposes review or activation actions; a manually created
policy is committed/active in one audited save. Next action: validate the
function and admin changes, then request approval to commit/push/deploy.

Client-page recovery (2026-09-25): production logs show `/orgs/all-data-health/`
failing because runtime code still reads the restricted
`v_client_source_link`. Scope: replace every Operations runtime client-source
read with `v_client_source_mapping_effective` / `client_source_references`,
which is the approved mapping evidence projection and is readable by
`operations_app`; leave Django Admin's model registration unchanged. Validate
client workspace and findings tests, then request approval to deploy the
recovery.

Client-page recovery checkpoint (2026-09-25): completed and deployed in
`481708d` (pushed to `origin` and `a-m-rose`). Validation passed: Django
checks, migration-drift check, 67 focused client-workspace/findings tests,
Ruff F checks, and diff check. Portainer deployed the same config hash;
`ninja-operations` is healthy and `/healthz` returns 200. An unauthenticated
request to `/orgs/all-data-health/` now returns the expected 302 login
redirect, with no new restricted-view error in the Operations logs. No schema
migration was required. The authenticated page should be verified from the
operator session as the final UI check.

Production follow-up (2026-09-25): authenticated `/sources/` and
`/orgs/all-data-health/` still fail because
`v_client_source_mapping_effective` is owned by `operations_view_owner` and
its nested, security-invoker `v_client_source_link` rejects that owner. The
application role can select the link view directly. Add migration 0205 to
grant only `SELECT` on the nested view to its owning effective projection;
this repairs every consumer of the approved projection without restoring
runtime reads from the legacy view.

Client-name issue usability follow-up (2026-09-25): the unified Issues table
must show the complete source-name evidence for a canonical client, not only
the source that refreshed the finding. Its control must deep-link to the
single source-link mapping decision, rather than the unfiltered Admin health
page. Extend the effective-reference helper with the source-link identity;
use it to render the evidence and a targeted Operations mapping URL.

Effective-mapping permission correction (2026-09-25): after 0205, an
operations-app query demonstrated the projection then stopped at
`client_source_mapping_decisions`. This is not a runtime grant: the
security-barrier projection is intentionally owned by
`operations_view_owner`, which already has the needed source-link and
observation reads. Migration 0206 grants that owner only `SELECT` on the
decision history table it joins; the app continues to access it only through
the permitted effective projection.

Client mapping recovery and usability checkpoint (2026-09-25): completed in
`0c3e37b`, pushed to both remotes and deployed by Portainer. Migration 0206
applied successfully; `ninja-operations` is healthy and the effective mapping
view returns 320 rows when queried as `operations_app` with tenant context.
The Issues UI now exposes complete attached source-name evidence and deep-links
to the matching Operations mapping decision. Focused client-workspace/findings
tests (67), Django checks, migration-drift checks, focused lint, and diff
checks passed. No new restricted-view error appeared in the post-deploy logs.

Conflict presentation correction (2026-09-25): the legacy Admin rows are real
client-name mismatches, not invalid data. The prior UI flattened every source
group attached to a client, which implied unrelated groups were part of one
conflict. Render the finding's reported source name separately and list only
different literal names from other sources as explicit comparisons.

Exact-name comparison correction (2026-09-25): normalization is permitted for
identity attachment, but it must not suppress a client-name finding. The
resolver and Issues comparison now treat any non-identical reported source
names as different, including punctuation, spacing, hyphenation, and case.

Client mapping inventory completion (2026-09-28): in progress. Keep the
top-level Clients page as a status dashboard. Add Inventory > Clients as the
operator-facing canonical-client inventory, with compact source-record,
literal-name-difference, review, and unmapped-candidate counts. Rebuild
Operations Admin > Integrations > Client mappings as the complete lifecycle
surface: effective attachments, open unattached candidates, and active
collision/duplicate-group findings must all be visible through explicit
filters, with source evidence, current decision/provenance, decision history,
and direct action/detail links. Do not introduce an expected-source absence
finding until a client-source coverage policy exists. Reuse the existing
candidate acceptance/map/exclude lifecycle; do not write source evidence
directly to canonical entities.

Scope: `apps/core/views.py`, `config/urls.py`, navigation, the mapping template,
and a new Inventory Clients template. No schema migration is planned because
the approved effective mapping projection, decision history, candidate queue,
and findings already persist the needed state. Validation: Django checks,
focused request/template tests, Ruff, and diff check. Checkpoint: inspect the
existing effective-mapping/candidate paths, then implement the two read models
and links before adding focused tests.

Completion checkpoint (2026-09-28): implemented the two read models. Inventory
now opens on Clients and has a Clients sub-navigation item before Computers;
it lists canonical clients with attached source-record, literal-name-difference,
and review counts, while preserving the existing Clients status dashboard.
Operations Admin > Integrations > Client mappings now shows all effective
attachments with decision provenance/history, all candidate lifecycle records
(including resolved history), and active ambiguity/collision findings, with
source, client, candidate, and finding links. Validation passed: Python
compile, 14 focused inventory/navigation tests, Ruff F/I for changed Python,
and `git diff --check`. The local `manage.py check` cannot run because this
workstation interpreter cannot import the repository `shared` package; Docker
Compose has no local services, so rendered request/database validation remains
for the deployment environment. No migration or deployment has been performed.

Client overview presentation correction (2026-09-28): in progress. The
individual client overview must not repeat opaque source IDs and provenance as
its primary source-reference table. Keep the reported source name and current
state visible, and add direct Source record and Mapping decision detail links.

Source-record drilldown completion (2026-09-28): implemented locally. The
Source record link now targets one exact client/source attachment rather than
the generic Sources list. Its detail surface includes reported name, source
identifier/namespace, observation and presence timing, current attachment,
decision rationale/provenance, and decision history; mapping action remains a
separate direct link. Validation passed: Python compilation, 14 focused
navigation tests, Ruff F/I, and `git diff --check`. Pending commit/push.

Sources/mappings boundary correction (2026-09-28): implemented locally. Admin
Sources is source-health, collection-volume, and run-history only; it no
longer duplicates source-client identity rows. Each source card hands off to a
source-filtered Client mappings view, which is the exclusive attachment,
ambiguity, candidate, and decision-lifecycle surface. The shared Admin
navigation is stable across Overview and integration pages, with distinct
Client mappings, Client candidates, and Entity candidates labels. Pending
validation and commit/push.

Completion checkpoint (2026-09-28): validation passed: Python compilation, 14
focused inventory/navigation tests, Ruff F/I for changed Python, and `git diff
--check`. Admin home now has a Client mappings card with live review,
unassigned-candidate, and ambiguity counts. No migration is required. Next
action: commit the completed navigation and page-boundary correction, push both
remotes, and trigger the required GitOps redeploy.

Resolver recovery (2026-09-28): production startup exposed an existing
client-name resolver defect while it refreshed source identity: it attempted
to write `resolved_at` on `operations.findings`, whose lifecycle field is
`closed_at`. Correct both entity-finding closure paths and test the contract;
AdminFinding and client-candidate closure fields remain unchanged.

Migration 0186, `jobs_software_supersession`, completes the declared
Software-only cross-key admission path for converted v1 Jobs. During its
implementation, the existing request-to-run composite FK was found to require
the request and resolved run to share a definition/digest/scope, contradicting
the approved broader-Software alias behavior. 0186 replaces only that FK with
a same-tenant run reference; request rows retain their own immutable requested
definition, digest, scope, input, and identity. Its restricted API validates
the definition snapshot's declared Software family/rank, serializes the family
with an advisory lock, aliases an equal-or-broader active run, cancels only
queued narrower v1 runs with durable events, and never stops running work. It
then delegates ordinary new-run admission to the constrained 0184 API. The
registry now records `software-classifier` family metadata for the three
approved modes. No existing version-0 writer invokes this API.

Focused validation now passes: Python compilation, targeted Ruff (`E`, `F`,
`I`) for touched registry/migrations/tests, and 23 focused Jobs migration,
registry, inventory, and queue tests. `git diff --check` passes with existing
LF-to-CRLF warnings only. Local PostgreSQL is still unavailable, so 0185/0186
SQL has not run and their lock, RLS, FK-discovery, and concurrency behavior is
not locally proven. Current next action: run the required small synthetic
PostgreSQL claim/contention/dependency/supersession checks when a local test
database is available; do not proceed to worker topology or convert a family
until that Step 2.3 safety validation is evidenced.

Autonomous correction checkpoint (2026-09-28): migration 0207 fixed the
claim-result API by returning both the claimed run ID and fencing token through
one restricted function. Focused migration tests, Python compilation, targeted
Ruff, and `git diff --check` passed. It was committed as `43b2fbc`, pushed to
`origin` and `a-m-rose`, and Portainer redeployed the approved commit. The
Portainer stack reports the matching configuration hash; Operations startup
logged `Applying operations.0207_jobs_claim_result_api... OK`, `/healthz`
returned 200, and Operations, ingest, and Postgres are healthy. The direct
Portainer POST/PUT redeploy attempts were rejected by its bodyless helper API,
but the configured one-minute Git redeploy detected and completed the push.
Next action: add deterministic immutable registry snapshot registration and
then convert v1 admission/claim consumers without falling back to raw ledger
lookups.

Definition registration checkpoint (2026-09-28): the shared Jobs registry now
produces deterministic, credential-free immutable snapshot metadata and a
SHA-256 digest. Ingest registers every declared snapshot transactionally under
the ingest tenant before operational execution begins. This establishes the
definition catalog without enabling a v1 producer or worker. Validation
passed: Python compilation, targeted Ruff (`E`, `F`, `I`) for the registry and
test, targeted undefined-name lint for the touched ingest modules, 10 focused
registry/queue tests, and `git diff --check`. Next action: commit, push, and
verify the production deployment registers the snapshot catalog cleanly.

Startup-order correction (2026-09-28): production validation exposed that the
initial registration placement ran before `db.init`, leaving ingest in a
restart loop. Registration now runs immediately after the pending ingest
migrations, before recovery or scheduled execution. A focused source-order
test prevents that regression. Validation passed: Python compilation, scoped
Ruff, 11 focused registry/queue tests, and `git diff --check`. Next action:
commit and deploy the startup-order fix, then verify ingest health and catalog
registration.

Production-observed catch-up correction (2026-09-28): after the startup-order
fix restored ingest, its normal startup exposed an existing PostgreSQL
`IndeterminateDatatype` error in the optional software-classifier mode probe.
Both nullable parameters are now explicitly `text`, preventing false
"overdue" decisions and unneeded classifier catch-up work. Python compilation,
undefined-name lint, and `git diff --check` pass; the dedicated focused module
is skipped locally because this environment cannot import the ingest runtime.
Next action: deploy and verify that startup no longer logs the probe error.

Deployment verification (2026-09-28): `780ee81` is deployed to both remotes
and resolved by Portainer. Ingest and Operations health endpoints return OK;
the fresh ingest startup has no catch-up probe error and reaches ready state.
The Jobs definition catalog contains 30 immutable registered snapshots, one
for each declared registry definition. The direct Portainer redeploy endpoint
continues to reject bodyless POST requests (HTTP 405), while the configured
one-minute Git update applied each approved revision. Next action: proceed with
the next governed v1 consumer conversion without reintroducing raw ledger
access.

Worker API foundation (2026-09-29): added migration 0208 with restricted
ingest-only v1 APIs that return a claimed run ID, fencing token, and job key
atomically, increment attempts under that fence, and finish/release the claim
without a worker reading or mutating the Jobs ledger directly. This remains
dormant until worker conversion; existing version-0 traffic is unchanged.
Focused validation passed: Python compilation, targeted Ruff, 12 Jobs
migration tests, and `git diff --check`. Next action: deploy this additive API
and implement the dedicated worker process against it.

Worker API deployment (2026-09-29): committed as `8b1322a`, pushed to both
remotes, and applied by Portainer. Operations logged
`Applying operations.0208_jobs_v1_worker_api... OK`; Operations and ingest
remain healthy. Next action: add the dedicated worker process and Compose
topology, using only the restricted v1 APIs for converted work.

Dedicated worker topology (2026-09-29): added migration 0209 for fenced v1
progress/heartbeat writes, `ingest.jobs_worker` as a no-HTTP/no-scheduler
process, and the `jobs-worker` Compose service with its own health signal.
The worker claims, progresses, and finishes converted runs through the
restricted APIs; existing version-0 producers remain unchanged, so it starts
idle until the producer cutover. Focused validation passed: Python
compilation, targeted Ruff, four worker/migration tests, Compose config, and
`git diff --check`. Next action: deploy the worker topology and confirm its
health before converting the first producer family.

Worker topology deployment (2026-09-29): committed as `a1a3667`, pushed to
both remotes, and applied by Portainer. Operations logged
`Applying operations.0209_jobs_v1_progress_api... OK`; the dedicated worker,
ingest, and Operations are healthy. The worker initialized its own database
pool and definition catalog and is correctly idle because no producer has yet
created a version-1 run. Next action: convert operator-originated Job requests
to the constrained APIs, then verify a bounded first family executes through
the dedicated worker.

Operator producer conversion (2026-09-29): the Operations Jobs request,
retry, batch, and software-rebuild paths now call `jobs_request` or the
declared Software supersession API with an immutable registry digest and a
credential-free request identity. They no longer insert or supersede ledger
rows directly. Focused validation passed: Python compilation, undefined-name
lint, 11 operator-queue/registry tests, and `git diff --check`. Next action:
deploy this conversion and verify a bounded operator request completes through
the dedicated worker before converting automatic schedules.

Operator producer deployment (2026-09-29): committed as `ffcdc57`, pushed to
both remotes, and resolved by Portainer. Operations and the Jobs worker are
healthy. A live operator request was not created during this deployment
verification, so first-run execution remains to be confirmed through the
normal operator surface before automatic schedules are cut over. Next action:
implement persistent schedule state and leader-elected automatic request
production, then exercise one bounded converted request.

Automatic-admission recovery (2026-09-29): the first automatic v1 software
request encountered a still-active version-0 run. The admission API correctly
rejected the incompatible overlap, but the automatic scheduler allowed that
exception to terminate ingest. `aa02a73` now logs and defers incompatible
automatic admissions. It is deployed to both remotes and Portainer reports
the matching configuration hash. External verification confirms
`operations-ingest` and `ninja-jobs-worker` are healthy with zero restarts;
ingest is completing scheduled work and the worker remains ready. The separate
platform-findings tenant-context error remains contained by its existing
failure boundary and was not changed. Next action: implement durable,
leader-elected schedule production only after explicitly reconciling or
draining active version-0 work for each converted family.

Durable schedule cutover (2026-09-29): in progress. Migration 0212 adds the
restricted schedule reconciliation and due-schedule read APIs. Ingest now
persists resolved UTC cadence and capability state, uses a PostgreSQL advisory
leader during each durable due-tick pass, coalesces missed ticks past the
current time, and submits requests through the existing atomic schedule API.
The legacy automatic producer and startup catch-ups are retired, avoiding
duplicate producers; a still-draining version-0 family is isolated as a
deferred schedule rather than rolling back other due work. Next action:
commit, deploy, and externally verify schedule activation and a bounded first
due request before implementing v1 timeout/cancellation/recovery controls.

Lifecycle and domain conversion checkpoint (2026-09-29): commits `a235d6f`
through `51ffe88` added governed cancellation requests, absolute v1 deadlines
with conservative resource containment, per-lane child-process execution,
supervisor control-plane resilience, additive source-domain Job links, and
registered source-action/source-demand workers. Source demand no longer starts
a daemon thread; demand-aware schedule enablement prevents idle no-op history.
The next conversion routes registered ingest HTTP triggers through v1
admission, leaving only genuinely scoped/legacy/bootstrap paths for separate
review. Focused registry, topology, migration, compilation, and diff checks
passed for the individual commits.

Operational blocker (2026-09-29): read-only host verification found every
Ninja container absent. Portainer stack 16 reports inactive, automatic update
has no JobID, and its last deployed revision is `a235d6f`; later pushes are not
deployed. The user explicitly prohibited direct Portainer deployment, so no
restart/redeploy was attempted. Continue implementation locally, but final
production validation requires the automatic updater/stack to be restored
outside this task or new explicit recovery direction.

Schedule presentation checkpoint (2026-09-29): the Jobs catalog now reads
tenant-scoped `job_schedules` state as the schedule authority. Scheduled rows
show persisted capability state, next due time, and the last request outcome;
conditional source-domain schedules distinguish waiting for demand from a
disabled capability. Focused Jobs tests, Python compilation, and diff checks
pass. Next action: harden and populate the source-demand/source-action Job-run
links with same-tenant constraints and lifecycle ownership.

Source-domain ownership checkpoint (2026-09-29): migration 0218 corrects the
preparatory single-column Job references to same-tenant composite references,
adds the tenant-1 boundary and RLS to the legacy source-demand queue, and adds
RLS to source actions. Governed workers attach each claimed domain row to the
exact Job run before execution. Retained domain failures now fail the wrapper
Job instead of appearing successful. Focused migration/topology tests and
Python compilation pass; PostgreSQL migration execution remains unavailable
while the stack is inactive. Next action: inventory and convert the remaining
direct/background execution paths, beginning with maintenance and bootstrap
work that still bypasses durable admission.

Software-demand cutover checkpoint (2026-09-29): both scoped software forms
now retain demand rows and wait for the registered software queue Job. The
former direct scoped daemon thread and the demand queue's immediate worker
thread are removed; the governed drain processes demand before activity and
scheduled work. The static Jobs inventory was regenerated from its checked
discovery function. Focused inventory/operator tests and compilation pass.
Next action: add immutable per-attempt Job membership for all three software
domain queues, then make partial queue failures fail the owning Job.

Software-domain ownership checkpoint (2026-09-29): migration 0219 adds
tenant-safe Job links to all three legacy software queues and an immutable
`job_domain_attempts` journal shared by software and source-domain claims.
Each claim records its owning run and attempt before work starts; software
demand, activity, and scheduled rows share one bounded drain, and any item
failure now fails the owning wrapper Job while retaining retry state. The
software queues enforce the current tenant boundary and RLS. PostgreSQL
execution remains unverified while the stack is inactive. Next action: remove
the dormant version-0 producers/workers and convert direct maintenance work
to registered control Jobs without letting recovery depend on normal lanes.

Producer cleanup checkpoint (2026-09-29): ingest now registers one automatic
producer only: the durable schedule poller. All legacy per-definition
APScheduler registrations and startup catch-up admissions are removed, along
with the unreachable HTTP daemon-thread handlers hidden behind governed
dispatch. The scheduler still hosts bounded control/recovery loops and the
temporary version-0 drain needed for pre-cutover rows. Static inventory,
focused Jobs tests, and compilation pass. Next action: define the controlled
version-0 queue cutover and move ordinary maintenance mutations into explicit
Jobs, leaving only claim containment and service liveness outside normal lanes.

Maintenance conversion checkpoint (2026-09-29): source-demand lease recovery,
stale diagnostic-run recovery, and platform-health evaluation are now three
registered, durably scheduled service-lane Jobs. Their former direct scheduler
callbacks and startup run-log mutation are removed. Claim timeout containment,
legacy-v0 interruption recovery, HTTP liveness, and infrastructure bootstrap
remain direct control-plane duties by design. Registry/inventory tests,
compilation, and diff checks pass. Next action: quiesce or preserve any queued
version-0 runs through an explicit cutover migration, then remove the legacy
in-process v0 worker and recovery callbacks.

Version-0 cutover checkpoint (2026-09-29): migration 0220 truthfully
terminalizes any remaining active v0 rows without deleting history: queued
runs become Cancelled and running runs become Needs attention, both with
retry/review guidance and events. The in-process v0 worker, heartbeat, raw
ledger mutation, startup recovery, and stale watchdog are removed. All new
execution now uses fenced v1 APIs and isolated child processes. Focused tests,
compilation, undefined-name lint, and diff checks pass; migration execution is
pending because the stack remains inactive. Next action: complete dependency
runtime semantics and expose workflow/run detail from the common ledger.

Run-detail checkpoint (2026-09-29): Job activity now exposes the selected
run's event timeline, prerequisite and dependent edges, linked domain attempts,
contract version, scope, immutable definition digest, correlation/retry links,
parent link, and terminal reason. This gives the dependency runtime a truthful
operator surface before production edges are activated. Focused Jobs tests,
compilation, and diff checks pass. Next action: implement atomic workflow
admission plus success release and prerequisite-failure propagation.

Dependency-runtime checkpoint (2026-09-29): the shared registry declares
completion successors for patch collection and software queue draining. Both
operator and automatic admission create the full graph atomically, including
the patch-classification/resolver join before platform evaluation. Migration
0221 adds an idempotent completion-edge API, releases ready children on
successful completion, and recursively marks queued descendants Needs
attention when a prerequisite fails, is cancelled, or times out. Material
revision dependencies remain distinct and unchanged. Focused registry,
migration, operator, inventory, and worker-topology tests pass (22 tests), as
do Python compilation, undefined-name lint, and `git diff --check`; PostgreSQL
execution remains unavailable while the stack is inactive. Next action: audit
every executable handler for truthful failure/result behavior, then close
worker-shutdown and Admin Health parity gaps found by the final requirements
review.

Handler-truth checkpoint (2026-09-29): required patch and Ninja collection
substeps now continue independently but fail the owning Job after all safe
steps finish. Identity and source collectors retain partial outcomes while
propagating aggregate failure after required projections. Retention and
Windows/end-of-life projections no longer suppress failure, and failed
notification or digest deliveries fail the Job after retaining delivery
evidence. The Agent compliance resolver follow-up is now a declared atomic
dependency rather than a later request. Focused source-failure, condition
safety, registry, operator, inventory, and worker-topology tests pass, with
Python compilation, undefined-name lint, and diff checks. Next action: enforce
the accepted workflow-root rule so a requested root remains Waiting until all
required descendants complete, then audit worker shutdown and health parity.

Workflow-root checkpoint (2026-09-29): migration 0222 distinguishes handler
completion from requested-work completion. A successful run with required
children releases its resource claims and deadline, clears its worker fence,
and remains visibly Waiting without consuming execution capacity. Terminal
child state is reconciled recursively: all-success rolls Completed up through
diamond joins, while failure or cancellation rolls Needs attention up and
blocks unstarted descendants. Waiting coordinators can be cancelled without a
nonexistent worker acknowledgement. The Job activity UI labels this state
explicitly and does not claim a worker is active. Focused migration, registry,
and operator tests, compilation, undefined-name lint, and diff checks pass;
PostgreSQL execution remains pending while the stack is inactive. Next action:
complete the declared source/intelligence edge families, then close worker
shutdown and Admin Health parity gaps.

Successor/edge-family checkpoint (2026-09-29): migration 0223 replaces the
single queued-or-running key exclusion with one queued successor plus one
executing run; workflow coordinators remain workerless and do not occupy the
executing slot. Generic and Software request APIs now preserve demand arriving
during execution. Broader Software supersession rewires retained workflow
edges to the covering queued run instead of stranding a parent. The registry
now declares source collection/action -> resolver -> platform evaluation and
the intelligence -> matcher/full-classifier families; duplicate inline source
resolution was removed, while required CMDB evaluation remains in the source
handler and now propagates failure. Focused migration, registry, source safety,
inventory, operator, and topology tests pass (59 tests), along with Python
compilation, undefined-name lint, and diff checks. Next action: make worker
shutdown explicitly terminate/reconcile children and add registry/scheduler/
worker mismatch evidence to Admin Health.

Worker-shutdown checkpoint (2026-09-29): migration 0224 adds a fenced worker
interruption transition. On graceful supervisor shutdown, exited children use
their normal terminal transition; still-running unaudited handlers become
Needs attention, lose their ledger fence, retain contained resource claims,
and block required descendants before the container owns process teardown.
The supervisor never calls terminate or kill because no handler is certified
kill-safe. Focused migration/topology tests, compilation, undefined-name lint,
and diff checks pass. Next action: replace the provisional broad source and
intelligence completion chains with dependency metadata and revision-aware,
affected-scope admission required by ADR-0024, then add Jobs control-plane
health evidence.

Revision-dependency checkpoint (2026-09-29): the provisional completion-only
edges are replaced with named revision contracts and condition-aware
admission. Migration 0225 validates each edge against the prerequisite's
immutable definition snapshot, persists scope/condition/coalescing/failure
metadata, publishes successful output revisions, and rechecks exact freshness
before release. CMDB evaluation is a separate registered Job. Source-demand
and source-action handlers publish bounded source-type signals. Intelligence
handlers retain integer compatibility but now report material change
explicitly; unchanged upserts do not count, and the full CVE matcher compares
semantic before/after output sets. Job detail exposes requested/input/output
revisions and edge contracts. The checked inventory was regenerated. Focused
Operations tests pass (20), focused ingest/material/projector tests pass (67),
and Python compilation, undefined-name lint, and `git diff --check` pass.
PostgreSQL execution remains unavailable while the stack is inactive. Next
action: commit and push this slice, then add Jobs registry/scheduler/worker,
claim-containment, and policy mismatch evidence to Admin Health and expose the
remaining persisted control-plane data.

Control-plane diagnostics checkpoint (2026-09-29): in progress. Migration
0226 adds tenant-protected scheduler/worker heartbeat storage and restricted
heartbeat/stop APIs. A read-only administrator API provides paginated access
to every persisted Jobs control relation: definition revisions, schedules and
ticks, request aliases, runs and events, dependencies, domain attempts,
lane/resource policy and claims, and runtime heartbeats. The new Jobs control
plane page exposes those records without direct table grants. Admin Health
compares the stored definition/schedule/policy state and fresh runtime registry
digests against the shared registry, and flags missing runtimes or contained
claims. The final schema-name review also corrected the run-detail query from
the nonexistent `requested_input` name to the authoritative `request_payload`
column before this slice was committed. Focused Operations tests pass (65),
focused registry/material tests pass (16), Django system checks pass, and
compilation, undefined-name lint, and `git diff --check` pass. PostgreSQL
execution remains unavailable while the stack is inactive. Next action:
review and commit/push this slice, then complete Job activity filters/
pagination and remaining request/schedule outcome semantics before the final
requirement audit.

Job activity checkpoint (2026-09-30): in progress. The activity query now has
bounded durable pagination with a count, filtering for Job, source/client
scope, lane, origin, status, owner, correlation/batch identifiers, requested
date range, and technical lineage identifiers. System run-log history is
separately counted and paginated, so neither list silently truncates. The
Jobs home asks the same authoritative run query for the finite set of active
definition states rather than relying on an arbitrary 200-row cap. Focused
validation passed: five Jobs/UI tests, Django system checks, Python
compilation, undefined-name lint, and `git diff --check`. PostgreSQL-backed
request checks remain unavailable while the local stack is inactive. Next
action: commit/push this slice, then add durable terminal schedule outcomes
and continue the requirement audit.

Schedule terminal-outcome checkpoint (2026-09-30): migration 0227 makes
`job_schedules.last_outcome` authoritative for the terminal result of its
current `last_run_id`. An `AFTER UPDATE OF status` security-definer trigger
handles every completion path and refuses to overwrite a schedule that has
advanced to a newer request; an additive backfill corrects prior terminal
schedule rows. Focused migration/Jobs tests (7), Django system checks, Python
compilation, undefined-name lint, and `git diff --check` pass. PostgreSQL
execution remains unavailable while the local stack is inactive. Next action:
commit/push this migration, then audit and implement remaining actionable
Admin Health findings and cross-surface Job links.

Admin Health persistence correction (2026-09-30): before adding the remaining
Jobs conditions, the existing platform-health evaluator was found to import an
entity-finding helper despite its admin-only contract. It now writes its
deduplicated source-failure and queue-stall conditions to
`operations.admin_findings`, preserving the condition assessment participant
contract. Focused condition-safety tests (37), Python compilation,
undefined-name lint, and `git diff --check` pass. Next action: commit/push
this regression correction, then register and evaluate the seven required
Jobs health conditions.

Jobs health policy checkpoint (2026-09-30): migration 0228 registers the
seven required Jobs Admin Finding types under platform health and clones the
active condition policy into a new validated revision with a Jobs control-plane
taxonomy entry. The shared policy carries the same definitions, preventing a
code-only condition taxonomy. Policy parsing, Python compilation, and
`git diff --check` pass. Next action: commit/push the policy prerequisite,
then implement the evaluator's seven measured, deduplicated conditions and
their Job deep links.

Evaluator handoff: implement the seven measurements in
`ingest/platform_findings.py` using durable Jobs schedules, runs,
dependencies, queue registry, immutable definition revisions, and runtime
heartbeats. Each emitted detail must retain `job_key`, `job_run_id`, or
schedule/control-plane section data for the Admin Health deep link; resolve
only after a fresh governing condition assessment permits clearing.

Jobs health evaluator checkpoint (2026-09-30): migration 0229 exposes a
tenant-bound, security-definer measurement API to the platform-health Job,
so the ingest role does not gain direct access to control-plane tables. The
evaluator now emits all seven policy-registered conditions from durable
schedules, run outcomes, dependencies, queue policy, immutable definition
snapshots, lane/resource policy, and runtime heartbeats. Queue and dependency
age thresholds come from the `operator.jobs` registry; repeated failures and
timeouts retain a bounded 24-hour observation window. Each finding has a Job
activity run/definition link or a control-plane section link. Focused
condition-safety and Jobs/migration tests, Django checks, compilation,
undefined-name lint, formatter checks for changed implementation files, and
`git diff --check` pass. PostgreSQL execution remains unavailable while the
local stack is inactive. Next action: review the full requirements against the
current framework, correct any remaining cross-surface or handler gaps, then
commit/push this evaluator slice with this checkpoint.

Audit correction in progress (2026-09-30): the inventory identified Metabase
bootstrap as an ungoverned daemon-thread path at startup and on the legacy
HTTP endpoint. It is explicitly classified as maintenance work by the Jobs
contract, so it is being registered as a capability-gated service Job and
admitted through the existing request API. HTTP serving and the scheduler
remain service infrastructure rather than Job work. The bootstrap result must
be truthful: disabled configuration creates no run, while configured but
unavailable or incomplete Metabase fails the Job for explicit manual retry.

Metabase bootstrap correction checkpoint (2026-09-30): `metabase-bootstrap`
is now a registered, capability-gated maintenance Job. Startup and the
`POST /bootstrap-metabase` endpoint admit it through the durable request API;
the prior daemon threads are removed. Disabled configuration returns no Job,
and a configured external dependency that is unavailable or incomplete makes
the Job fail rather than logging a false success. The checked registry
inventory was regenerated, retaining its coverage metadata. Focused inventory,
registry, and Jobs UI tests (22), Django checks, Python compilation,
undefined-name lint, and `git diff --check` pass. PostgreSQL-backed admission
and external Metabase execution remain unavailable while the local stack is
inactive. Next action: commit/push this audit correction, then continue the
full requirement audit for any remaining ungoverned background paths or
cross-surface gaps.

Timeout-contract correction in progress (2026-09-30): the review found that
the durable claim path still assigned one hard-coded 90-minute deadline and
definition snapshots did not describe timeout, progress, result, or
permission contracts. Add those immutable registry fields to every snapshot
and introduce a fenced v4 claim API that derives the deadline from the
claimed revision. Existing v1 snapshot rows without the new field retain the
previous 90-minute behavior only as backward-compatible historical input.

Timeout-contract correction checkpoint (2026-09-30): immutable definition
metadata now contains timeout, retry, stage-progress, result, and permission
contracts. Migration 0230 adds a tenant/fence-preserving v4 claim API, which
reads the claimed immutable snapshot and records its timeout in the run. The
v3 90-minute fallback is reachable only for historical v1 snapshots that
predate this contract; every newly registered revision carries its own value.
Focused inventory/registry/Jobs worker/UI/migration tests (26), Django
checks, Python compilation, undefined-name lint, and `git diff --check` pass.
PostgreSQL execution remains unavailable while the local stack is inactive.
Next action: commit/push this contract correction, then continue the full
requirement audit.

Priority-contract correction in progress (2026-09-30): admission still got
the legacy table default priority instead of an immutable definition contract.
Add priority, coalescing scope, and concurrency scope to every snapshot, and
apply the definition priority in a fenced `BEFORE INSERT` trigger for v1 run
admission. This keeps the existing priority-aging claim order but removes an
untracked request-time default.

Priority-contract correction checkpoint (2026-09-30): snapshots now include
priority, coalescing scope, and concurrency scope alongside the previously
added timeout/progress/result/permission contracts. Migration 0231 applies
the immutable priority with a security-definer, before-insert trigger for v1
Jobs, while preserving legacy rows and the reviewed priority-aging claim
order. Focused registry/worker/UI/migration tests (22), Django checks, Python
compilation, undefined-name lint, and `git diff --check` pass. PostgreSQL
execution remains unavailable while the local stack is inactive. Next action:
commit/push this correction and continue the full requirement audit.

Cross-surface correction in progress (2026-09-30): active source-demand rows
already retain their same-tenant `job_run_id`, but the Sources page displayed
only a generic queued/running label. Expose a direct Job activity link from
that durable relationship; do not derive a link from run-log diagnostics.

Cross-surface correction checkpoint (2026-09-30): Sources now queries active
source demand under tenant context and renders its retained Job-run link for
queued or running work. Focused Jobs UI tests (7), Django checks, and `git
diff --check` pass. Next action: commit/push this correction, then complete
the remaining requirement audit.

Completion audit checkpoint (2026-09-30): the full governed Jobs scope is
implemented in the current branch. The shared immutable registry now records
owner, technical key, presentation, capability, cadence/trigger, lane,
resource/concurrency/coalescing scope, dependency contracts, priority,
timeout, retry, progress, result, permission, and handler revision; its
machine-checked inventory covers registered dispatchers, schedules, HTTP
admission paths, queues, startup work, and the remaining service threads.
Every converted invocation is admitted before execution, domain attempts link
to their Job run, and all Jobs readers use the durable ledger/schedule/control
relations rather than run-log lifecycle state. The worker uses fenced APIs,
isolated children, contained timeouts, cooperative cancellation, immutable
revision dependencies, and explicit stalled/blocked outcomes. Jobs Admin
Health has all seven governed, deduplicated, actionable measurements with
durable Job/control-plane links; Sources has the active demand-to-Job link.

Validation: `pytest apps/core/tests/*jobs*.py` passed (57), `python manage.py
check` passed, Python compilation and undefined-name lint passed for each
changed implementation slice, and `git diff --check` passed. Relevant pushed
commits include `c5df42c`, `62e2b8a`, `f0836c0`, `622555f`, and `83cc24e`.
The local PostgreSQL stack is inactive, so migration execution, runtime
admission/claim behavior, and automatic GitOps deployment cannot be directly
verified here. Per user direction, do not call Portainer; origin pushes are
the deployment handoff. No legacy data/history is deleted or fabricated.

Production regression correction in progress (2026-09-30): read-only SSH
health validation after the automatic deployment found `operations-ingest`
restart-looping because `SCHEDULED_OPERATOR_JOB_KEYS` omitted five registered
durable maintenance schedules. The fail-closed registry check correctly
prevented a partial scheduler from running, but its test inspected obsolete
direct scheduler declarations rather than the parity constant. Restore exact
membership and test the parsed constant against `scheduled_definition_keys()`.

Production regression correction checkpoint (2026-09-30): restored the five
omitted schedule keys and added exact parsed-constant parity coverage. Focused
registry/inventory/Jobs UI tests (24), Django checks, Python compilation,
undefined-name lint, and `git diff --check` pass. Next action: commit/push
the correction and use read-only SSH health checks to verify the automatic
GitOps restart; do not call Portainer.

Live corrective checkpoint (2026-09-30): production has all Jobs migrations
through 0231 and healthy scheduler/worker heartbeats, but 26 queued runs, no
running run, and three `held` claims belonging to a stalled
`agent-observations` run. The existing claim SQL returns after its first
resource-blocked candidate instead of considering later compatible work.
Schedule admission correctly refuses incompatible immutable definition
revisions, but it currently raises and retries the same due tick without a
durable deferred outcome. Implement migration 0232 to reconcile terminal
held claims into explicit containment, scan queued candidates fairly past
blocked resources, persist a schedule deferral event, and expose a
confirmation-gated administrator recovery for contained claims. Do not
automatically release uncertain claims or call Portainer. Next action: add
the migration, worker/API/UI integration, focused tests, then commit/push and
verify automatic GitOps deployment before any explicit recovery action.

Worker finalization corrective checkpoint (2026-10-01): after 0232 deployed,
the fair claim path correctly admitted an independent `intel-kev` Job while
the old tenant-state claim remained contained. Its exited child then exposed
an existing supervisor bug: repeated `communicate()` calls read an already
closed stdout pipe and left the run running. Read a completed child's stdout
once after `poll()`, and when any finalization transition cannot be recorded,
fence it through the existing worker-interruption containment API instead of
retrying forever. Next action: commit/push this worker correction, verify the
automatic rollout contains the stranded run, then use the administrator
recovery surface only after explicit process/effect verification.

Live verification checkpoint (2026-10-01): automatic GitOps deployed commits
`3227e39` and `c97a0ef`; migration 0232 is applied and all three containers
are healthy. The scheduler now records durable `deferred` outcomes rather
than emitting conflict errors, and the worker code has the stdout/finalization
fix. The previously stuck `intel-kev` child was safely timed out, so there are
zero held claims and zero running runs. Six claims are deliberately
contained: three from the prior interrupted `agent-observations` collector
and three from `intel-kev` (deployment, intelligence lane, and CVE corpus).
The Jobs activity page now exposes a CSRF-protected, administrator-only
confirmation action to release contained claims after process/effect
verification. Do not impersonate an operator or release these claims through
SSH: an authenticated administrator must perform the explicit recovery.

Jobs-page authorization correction in progress (2026-10-01): live navigation
to `/admin/jobs/` returned HTTP 500 because `_operator_job_runs` directly
queried tenant-protected `job_dependencies` (and would next reach similarly
protected domain-attempt and claim relations) under `operations_app`. Preserve
the intentional no-direct-table-grant boundary: add a bounded,
tenant-validated security-definer relation API for the selected Job IDs and
make the activity page use it. Next action: implement migration 0233 and the
view adapter, validate locally, commit/push, then verify the automatic rollout
returns the Jobs page successfully.

Jobs relation API correction (2026-10-01): migration 0233 deployed but its
first runtime-role probe found a PL/pgSQL output-column collision in the
null-array validation alias (`run_id`). Add migration 0234 that replaces the
function using an explicitly named unnest column, then repeat the controlled
API probe and Jobs-page verification. No permissions or data were changed by
the failed read.

Jobs-page verification checkpoint (2026-10-01): automatic GitOps deployed
`dce9b45`, `3d10dcb`, and `3282fd7`; migrations 0233 and 0234 are applied.
The relation API now succeeds under `operations_app`, and a read-only internal
render of `/admin/jobs/` with the deployed host header returns HTTP 200. The
prior 500 was fully corrected without granting direct access to control-plane
tables. The six contained claims remain intentionally unreleased pending an
authenticated administrator's explicit recovery confirmation.

Recovery-safety correction in progress (2026-10-01): the contained-claim
action improperly asked an administrator to attest to an outcome that the
Jobs ledger cannot prove. The activity screen has technical history but no
verified child termination or domain-effect evidence, so it must not present
claim release as an operator decision. Retire the direct release capability
from the Operations runtime role and replace it with clear, domain-facing
recovery guidance that identifies the owning service and explains that the
affected work remains safely paused pending owner-provided recovery evidence.
Preserve the contained claims and history; do not invent evidence or release
any live claims. Add focused regression coverage and validate the migration,
template, and request surface before the authorized commit/push.

Job-activity usability addition (2026-10-01): group the bounded activity
page by Job name so an operator can scan related attempts together. Add a
selection-based bulk queue control that delegates every selected run to the
existing tenant- and actor-validated cancellation API; queued work is
cancelled and running work receives only a cooperative cancellation request.
Do not provide bulk retry, recovery, or claim-release controls because their
safe eligibility evidence has not been implemented.

Recovery-safety and activity usability checkpoint (2026-10-01): migration
0235 revokes the direct contained-claim release function from
`operations_app`; the release endpoint and misleading confirmation control
are removed. Contained work is now described as a paused, unverified outcome
that requires platform incident escalation, rather than a decision an
administrator can make from incomplete evidence. Job activity is grouped by
Job name and has a maximum-50-selection bulk control that uses the existing
fenced cancellation API for each selected run. Focused Jobs/migration tests
(12) and Django checks pass; `git diff --check` passes. The repository-wide
ruff invocation still reports existing violations in `views.py`; the new
migration and URL module pass targeted ruff. Next action: commit and push the
reviewed code plus migration 0235, then verify automatic GitOps deployment
and the read-only Jobs page.

Recovery-completion work in progress (2026-10-05): production now has 26
queued runs, no running run, 30 Needs-attention runs, and 8 contained resource
holds. The prior safety gate correctly blocks unsupported operator release but
does not provide the service-owned evidence path required by ADR-0024, so the
framework is not operationally complete. Implement a durable recovery-evidence
contract and per-definition reconciler only where the handler can prove a
safe replay boundary; retain an escalation state for every other definition.
The reconciliation result must be visible on Job activity, enforceable by
the claim-release API, and tested under tenant/RLS boundaries. Then deploy by
the approved GitOps push, verify recovery of the known contained work, and
prove queued Jobs can drain without direct Portainer action.

Replay-safe recovery checkpoint (2026-10-05): migration 0236 adds an
append-only recovery-policy/evidence ledger and tenant-protected diagnostics.
Only the exact historical revisions of `intel-epss` and
`software-classify-only` are approved for automatic release: both reconcile
database state transactionally, converge on a later replay, and have no
external mutation. The worker registers reviewed current policy revisions and
reconciles only those contained runs before it claims work; all other
interrupted definitions remain safely escalated. Focused Jobs, registry, and
migration tests (23), Django checks, Python compilation, and `git diff
--check` pass. Next action: commit/push migration 0236 and verify the
automatic rollout records recovery evidence, clears the eight reviewed holds,
and drains queued work.

Recovery rollout race correction in progress (2026-10-05): migration 0236
deployed and its authorities/policies are present, but the Jobs worker started
before Operations completed the migration. Its startup reconciliation safely
treated the API as unavailable and did not retry, leaving the reviewed holds
contained. Retry idempotent recovery-policy registration and reconciliation on
the worker's existing heartbeat interval, then push and verify the automated
assessment and queue drain. Do not invoke the recovery function manually.

Final replay-safe recovery correction (2026-10-05): retry-on-heartbeat
deployed and released the original eight held resources with two durable
assessments. A pre-existing `intel-kev` child was correctly interrupted by the
rollout and contained because it lacked an approved policy. Its handler is a
transaction-scoped conditional upsert of a public feed, so migration 0237
adds its exact reviewed revision. The only active child is the full software
classifier; its read-only upstream fetches and deterministic Operations
reconciliation are also replay-safe, so migration 0238 records its exact
reviewed revision before the final deployment. Focused Jobs, registry, and
migration tests (24), Django checks, Python compilation, and `git diff
--check` pass. Next action: commit/push migrations 0237/0238, then verify
the final automatic rollout clears remaining contained claims and Jobs drain.

NVD replay-safe recovery correction (2026-10-05): final rollout correctly
recorded recovery assessments for KEV and the full classifier, but also
contained an already-running NVD feed refresh. NVD is an audited,
transaction-scoped conditional upsert of a public feed, so migration 0239
adds its exact reviewed revision. The active Ninja collection cycle is not
included: it remains deliberately unreviewed for automatic replay and will
stay visible/escalated if interrupted. Focused Jobs, registry, and migration
tests (22), Django checks, and `git diff --check` pass. Next action:
commit/push migration 0239 and verify NVD recovery plus the durable queue
progress; do not force-release collection work.

Collection recovery completion in progress (2026-10-05): inspection verified
that CPE dictionary and Ninja collection handlers only read external sources
and converge local state through cursor-backed or source-projection
reconciliation; neither invokes a vendor-side mutation. Migration 0240 adds
their exact reviewed revisions, while source actions, notifications, and all
other unreviewed mutation handlers remain escalation-only. Focused Jobs,
registry, and migration tests (22), Django checks, and `git diff --check`
pass. Next action: commit/push migration 0240 and verify automatic recovery
clears the remaining contained claims and the queue resumes.

OTX recovery completion in progress (2026-10-05): after the 0240 rollout,
one interrupted `intel-otx` run retained three contained claims. Handler audit
confirms it only reads AlienVault's subscribed-pulse feed and conditionally
upserts local `safety_signal` records in one transaction; it has no
provider-side mutation. Migration 0241 therefore authorizes only that exact
immutable digest for replay-safe recovery. Next action: run focused checks,
commit/push the migration, and verify the automatic GitOps rollout records
recovery evidence and clears containment without direct Portainer action.

Current-status separation in progress (2026-10-05): immutable terminal Job
records were appearing beside queued and running work, making historical
interruptions look like active failures. Add a bounded control-plane current
work relation (queued, running, or still protected by contained resources),
keep terminal records in a separate Run history view, and expose durable
recovery evidence as "Recovered automatically" without changing the original
run outcome. Next action: run focused checks, commit/push the migration and UI
change, then verify the live default page shows only current work.

abuse.ch recovery completion in progress (2026-10-05): the 0242 automatic
rollout interrupted one `intel-abusech` run, leaving three contained claims.
The handler reads only public MalwareBazaar and ThreatFox feeds and performs
transaction-scoped conditional local-signal upserts; it has no external
mutation. Migration 0243 authorizes only the interrupted immutable revision
for replay-safe recovery. Next action: validate, commit/push, and verify the
worker records recovery evidence and clears the final contained claims.

Jobs activity usability refinement in progress (2026-10-05): the page exposed
the ledger grouping as repeated Job-specific tables, forcing operators to scan
long sections and repeatedly interpret status. Replace that layout with a
compact current-work summary and one table per selected view: Current work,
Needs attention, or Run history. Preserve all run detail, recovery evidence,
safe controls, filters, and diagnostic links. Next action: validate the
focused UI checks, commit/push, then confirm the deployed page renders.

Latest-status refinement in progress (2026-10-05): Current work should answer
the status of each Job rather than list every simultaneous attempt. Collapse
the default view to the latest active attempt per Job and link that Job to its
complete immutable Run history; attention and history retain individual runs.

Operations orchestration rework in progress (2026-10-05): retain the durable
Job ledger, worker, claims, dependency edges, recovery evidence, and history,
but stop presenting or scheduling every executable step as an independent
operator Job. Define a small registry layer of operator-facing Operations
tasks with an entry step, scheduled cadence, and visible step list. The
scheduler must admit/coalesce a task entry only; dependent steps are admitted
from that sequence. A completed step must become terminal and release claims
immediately, while the sequence separately tracks unfinished follow-on work.
The Jobs surface will show Operations tasks and their always-visible steps;
individual technical controls stay on step rows behind guarded controls. Do
not delete existing schedules or run history during migration. Next action:
inventory schedule roots versus dependent steps, design the durable task and
sequence contract, then implement migrations and worker/UI changes in small
validated slices.

Operations orchestration implementation checkpoint (2026-10-05): the shared
registry now treats only operation entry points as automatic schedules and
retains every dependent Job as a visible linked step. Operations Jobs presents
those entry points in four plain-language areas (Data updates, Software and
security, Reports, Maintenance) with the constituent steps shown on the same
row. Forward migration 0244 makes every completed Job terminal, preserves
root/parent dependency lineage as the sequence record, retires only enabled
dependent schedules without deleting their history, and corrects the prior
handler-complete pseudo-running coordinator rows. Live inspection found the
existing queue is also blocked by a contained `intel-matcher` run
`fa825f0a-14f6-46e1-87b1-4efb4a508944`; 0245 records digest-specific,
audited replay-safe recovery because that handler rebuilds local data in a
transaction and makes no external mutation. Focused registry and Operations
tests pass, Django check passes, and diff check passes. Next action: review
the staged diff, commit and push the approved migration/UI/scheduler change,
then verify automatic GitOps migration, recovery evidence, terminalized old
coordinator rows, and queue progress without a direct Portainer action.

Post-rollout verification (2026-10-05): commit `5ae4890` was pushed to origin
and the required mirror. Automatic GitOps applied 0244 and 0245; the worker
recorded one replay-safe matcher recovery and became healthy. The retired
dependent schedules are disabled and the three former pseudo-running
coordinators are terminal `completed` records. The catalog was then refined
so an operation stays visibly in progress when its completed entry has linked
active steps; each displayed step now uses that operation run's root lineage,
not an unrelated latest Job run. Focused tests and template/Django checks pass.
Next action: commit/push the lineage display refinement and make one final
read-only queue-progress verification.

Queue-resume compatibility fix (2026-10-05): after the matcher containment
was safely released, `agent-compliance` reached execution and failed because a
shared connector identity field (`external_namespace`) was passed to the
legacy `ninja_agent_compliance.platform_observations` projection, which does
not own that column. The projection now explicitly persists only its stable
schema columns, preserving all compliance data while ignoring shared-only
connector metadata. A focused test covers the projection boundary; it cannot
collect on the local Python install because that environment lacks ingest's
`pydantic` dependency. Next action: commit/push this narrow compatibility fix
and verify the automatic rollout moves the queue past agent compliance.

Agent-compliance follow-on (2026-10-05): the resumed handler also exposed a
pooled-connection RLS context gap in the Ninja presence connector. Its read of
the protected device-detail projection did not establish tenant 1 and could
inherit an empty setting. The connector now sets the transaction-local tenant
before that read. Next action: commit/push both queue-resume fixes and verify
the automatic rollout completes an agent-compliance run.

Automatic-rollout recovery (2026-10-05): the worker restart during the
queue-resume deployment interrupted `intel-endoflife` while it held the shared
execution, software-catalog, intelligence-lane, and tenant-state resources.
Handler review confirms it only reads endoflife.date and applies convergent
local upserts. Migration 0246 authorizes only its recorded immutable digest
for replay-safe claim release. Next action: validate, commit/push 0246, then
verify this final contained hold is automatically released and queued work is
claimed.

Resource fairness rework in progress (2026-10-05): live queue inspection
proves the blanket `tenant:{tenant_id}:state` lock serializes unrelated work.
Replace it with explicit domain locks; retain global corpus/catalog and
delivery locks, keep per-lane limits and the deployment-wide capacity of two,
and add every new template to the durable resource-limit policy. The change
must not weaken protection for two handlers that write the same derived data.
Next action: register reviewed per-definition domain ownership, migrate the
resource policy, then validate parallel claims only occur for disjoint domains.

Fairness validation refinement (2026-10-05): the global capacity is already
two, but every lane was also limited to one. That prevents two disjoint Jobs
in the same lane from occupying both reviewed global slots. Migration 0248
raises each lane ceiling to two; the deployment-wide ceiling remains two and
domain resource claims remain the safety boundary. Existing queued records
retain their old immutable broad-lock snapshot and will drain as a short
transition backlog. Next action: deploy and verify two disjoint Jobs claim
the available slots concurrently.

Completion-regression recovery in progress (2026-10-05): live inspection
found three queued Jobs with completed prerequisites whose dependency edges
remained waiting. Migration 0244's terminal-step rewrite accidentally omitted
the immutable output-revision publication that the dependency release function
requires. Migration 0249 restores publication for future completions and
reconstructs only missing revisions from existing waiting workflow edges on
completed prerequisites, then uses the normal propagation function to release
them. It does not rerun work or release failed dependencies. Next action:
review the migration, run focused checks, commit/push, and verify the queue
claims released work after automatic rollout.

Completion-regression recovery verified (2026-10-05): commit `2f5636d` was
pushed to origin and the required mirror. Automatic GitOps applied migration
0249. Live inspection shows two genuine Jobs running (`patches` and
`software-classify-full`); the former completed-prerequisite waits are no
longer the only queue state. Remaining queued rows are either normal resource
contention for the two worker slots or valid downstream dependencies. Next
action: continue the broader Jobs framework audit and address any separate
handler failures found during normal execution.

Jobs page availability fix in progress (2026-10-05): live request logging
identified a `KeyError` in the operation-row status fallback. Operation entries
intentionally contain presentation and step metadata, while historical status
metadata belongs to their underlying Job definition. Resolve status from that
definition when available, preserve dynamic-source metadata, and treat an
absent fallback as no recorded run. Next action: run focused view/template
checks, commit/push, and verify `/admin/jobs/` after automatic rollout.

Jobs and activity alignment in progress (2026-10-05): the Jobs page showed
an operation's stale entry-step status even while a linked step was active,
and its card layout hid the current stage, wait reason, and elapsed time that
the Activity page exposes. Make an operation inherit the current state of its
active sequence, retain visible step rows and guarded controls, add the same
running/queued/attention summary, and use Activity-style operation tables
with current status, result, schedule, and action columns. Live queue review
shows two heartbeating Jobs occupying the reviewed deployment capacity; four
dependent Jobs wait for their current revisions and five await capacity.
One old full-classification run retains its immutable pre-fairness broad lock
until completion, so this is visible transitional serialization rather than a
stalled worker. Next action: validate rendering, commit/push, and inspect the
automatic rollout.

Routine classification scope refinement in progress (2026-10-05): routine
software classification already uses exact installation-state markers and the
full rebuild cadence already defaults to weekly (168 hours). The registry was
nevertheless sending every material intelligence update to the full rebuild.
Route those automatic follow-ons to the incremental classifier instead, so
routine work handles only new or changed installations. Preserve the weekly
full rebuild and explicit full-rebuild control as the authoritative fleet-wide
reconciliation path; allow the current healthy full run to finish. Next
action: validate registry/worker behavior, commit/push, and confirm new
material-change dependencies target incremental classification after rollout.

Patch-classification scope implementation (2026-10-05): migration 0251 adds
durable per-device patch evaluation state. The classifier builds a
transaction-local scope of devices whose patch signal, reboot state, or boot
state changed, evaluates only that scope, evaluates approval backlog for its
affected clients, and limits auto-resolution to the same scope. It falls back
to a full reconciliation every 168 hours (`PATCH_CLASSIFY_FULL_REBUILD_HOURS`)
and records the mode in run history. Next action: commit/push, verify the
automatic migration, then inspect a live incremental run and its scoped state.

Patch full-reconciliation marker (2026-10-06): migration 0253 records the
last successful full patch evaluation atomically with its durable device state.
Weekly cadence now uses this marker rather than optional run history. Next:
commit/push and verify the automatic rollout.

Patch-classification rollout verified (2026-10-06): commits `db44dc3` and
`dc1383d` are deployed. Production has migrations 0251 and 0253, 2,809 durable
per-device state rows, and a live patch classifier. The one failed run was a
safe startup-order race before 0253 created its table; a later run is healthy.
With no full marker, the classifier deliberately performs the first full
reconciliation and writes the marker only after that transaction succeeds;
subsequent routine runs are scoped to changed patch, reboot, or boot state.
Focused Jobs checks pass (8), Python compilation passes, and the diff check
passes. The patch-classification performance objective is complete. The
separate capacity-controls rollout remains pending automatic GitOps application
of migration 0254; do not deploy it manually.

Jobs capacity controls (2026-10-06): authorized extension. Raise governed
global execution capacity to three, prevent the legacy agent-compliance bridge
from crowding native Operations work, and add an audited admin surface for
editing reviewed lane and resource capacity policy. Next: migration, admin
write API/view, validation, commit/push, and rollout verification.

Capacity-controls validation (2026-10-06): commit `185892a` contains the
migration, capacity API, and admin surface, but its registry test still asserts
the former execution capacity of two. Focused Jobs checks therefore report 21
passing and one failure (`test_registry_exposes_the_approved_conservative_resource_policy`).
Production has migrations 0251--0253 only and remains at global capacity two;
0254 has not yet been applied by automatic GitOps. Correct the stale assertion,
run the focused checks, commit/push the correction, then verify 0254 and the
capacity-three policy live. No direct deployment.

Software target implementation (2026-10-05): migration 0250 creates a
tenant-scoped durable target queue. The CVE matcher compares its old and new
match sets and records only changed version identities or product-level names;
incremental classification merges those targets with its existing installation
hash scope and consumes them only after a successful transaction. Material
intelligence dependencies now request incremental classification, while the
full classifier is restored as an independent weekly schedule. Patch scoping
is the next implementation slice and must preserve device and client finding
resolution semantics.

---

# Jobs dispatch and capacity rework

## Status

**Historical (2026-10-15)** — not active, not verified complete. Later
capacity commits (`91703d5`, `d5be94c`) and ADR-0026 likely supersede it;
carried to the root plan for confirmation (J9).
Original status: **Implementation in progress.** This plan supersedes the
earlier capacity-three implementation direction. Commit `185892a` and migration
0254 remain immutable history, but their lane/global-capacity policy is not the
target design. Production was last verified with migrations 0251--0253 and a
global execution capacity of two. Do not invoke Portainer; rollout remains the
automatic GitOps consequence of a separately approved push.

## Implementable goal

Replace arbitrary lane and global-count scheduling with truthful, pool-aware
Jobs dispatch while preserving every Job run, schedule, dependency, resource
claim, recovery record, and operation/step relationship.

The completed system must keep four concerns separate:

| Concern | Mechanism |
|---|---|
| Operator organization | An Operation and its visible steps |
| Lifecycle | Waiting, Ready, Running, Completed, Needs attention, Cancelled |
| Platform capacity | Execution-resource pools claimed atomically by each Job |
| Data safety | Fixed domain resource locks for overlapping writers |

At most two runs may be Ready. Work that cannot start must remain visible with
one factual reason: waiting for data, protected work, or capacity. Capacity is
not a single global job count and is not inferred from an operator-facing
category.

## Confirmed problem

- The worker stores one child per hard-coded lane and therefore enforces a
  physical one-child lane boundary regardless of the configured lane limit.
- The deployment-wide `execution:deployment` capacity of two then overrides
  otherwise independent work. Raising lane and global rows to three does not
  make the worker honor three children in one lane.
- `queued` currently includes dependency waits and resource waits, so queue
  depth is not the number of runs that are ready to execute.
- Existing domain claims correctly protect shared writers, but capacity claims
  and correctness locks are represented and administered as though they were
  the same policy.
- Every isolated child can open a Postgres pool of up to four connections.
  Production reported 20 of 100 connections in use during review, so child
  count and database headroom require an explicit rollout check.
- PostgreSQL transactions already let readers use committed state while a
  writer prepares a new transaction. A new dataset-versioning framework is not
  required.

## Decisions and invariants

### 1. Preserve Operations and steps

Operations remain the operator-facing scheduled/manual units. Their existing
steps, root/parent lineage, schedules, controls, and immutable run history are
unchanged. Pool names, claims, definition digests, and raw wait metadata stay
in administrator detail, not the normal operator layout.

### 2. Use truthful lifecycle presentation without rewriting history

Keep the physical v1 run statuses required by ADR-0024. Derive lifecycle as:

- `queued` with dependency/workflow wait metadata: **Waiting for data**;
- `queued` with a conflicting domain claim: **Waiting for protected work**;
- `queued` with an unavailable execution pool: **Waiting for capacity**;
- `queued` with no wait reason and admitted to the bounded ready window:
  **Ready**;
- existing running and terminal statuses retain their established meanings.

All admission, dependency-release, claim, cancellation, and recovery APIs must
maintain this invariant. No page or API may count Waiting runs as Ready.

The Ready window is a fixed contract of two runs. Promotion is serialized in
the database and must look past blocked candidates. Additional eligible work
remains Waiting for capacity; it is not hidden or discarded.

More than two Waiting runs may legitimately exist because prerequisites,
protected data, or available capacity cannot be discarded. They must never be
reported as queued. The operator queue count is exactly the Ready count and can
therefore never exceed two.

### 3. Replace lanes/global count with execution-resource pools

Definitions declare `capacity_keys` independently of `resource_keys`. A Job
may require more than one capacity pool. Initial reviewed pools are:

| Pool | Purpose | Initial capacity |
|---|---|---:|
| `capacity:external-io` | External source and intelligence retrieval | 2 |
| `capacity:processing` | Classification, matching, resolution, and evaluation | 1 |
| `capacity:control` | Short recovery, health, cleanup, and reporting work | 1 |

The initial emergency child-process ceiling is four, equal to the sum of the
reviewed pool capacities. It is a deployment-wide database-enforced safety
fuse, not an in-process counter or alternative scheduling policy. Before
rollout, the handler inventory must confirm each definition's actual pool
requirements; names or old lanes are not evidence.

Pool claims are acquired atomically with domain claims in stable key order.
A job that needs two pools starts only when both are available. A failed claim
leaves no partial ownership.

### 4. Keep domain locks fixed and specific

`resource_keys` continue to describe data-safety boundaries. Their capacity is
one and is not operator-editable. Same-scope source application, identity
promotion, shared derived-state writers, notification delivery, and the same
materialized-view refresh remain serialized where their handlers require it.

Different source scopes and unrelated derived domains may overlap. Broad
`global:software-catalog` and `global:intel-cve-corpus` declarations require a
handler-by-handler read/write audit. Narrow a lock only when transaction and
follow-on revision behavior prove that a reader can safely consume the prior
committed state; do not weaken it based on naming alone.

### 5. Use database-coordinated dispatch with stateless supervisors

Postgres remains the only dispatch authority. A supervisor owns no durable
queue truth, ordering, or capacity in memory; it supervises only its local
children. Deploy one supervisor initially, while making the contract safe for
multiple supervisors without redesign. Atomic claims, `SKIP LOCKED`, claim
tokens, generations, pool limits, the Ready bound, and the emergency process
ceiling are deployment-wide database rules.

Replace the `children[lane]` worker map and lane-specific claim call with a
local child map keyed by run ID. Each stateless supervisor repeatedly:

1. reconciles exited children and heartbeats live children;
2. promotes eligible Waiting work into the two-position Ready window;
3. claims the oldest eligible Ready run using bounded priority aging;
4. atomically acquires every required capacity and domain claim;
5. starts children until no further compatible work fits;
6. contains interrupted work under the existing recovery contract.

Control capacity remains available to control jobs and is not borrowed by
processing work. Parent Operations that are only coordinating steps consume no
child or pool claim. Existing definition/scope coalescing remains authoritative.
Supervisor heartbeats are independent; loss of one supervisor prevents only
its local children from reporting and invokes the existing containment rules.
Another supervisor may continue claiming disjoint work. No supervisor leader
election is introduced.

### 6. Make only capacity policy editable

The Admin control plane shows each execution pool's capacity, active use,
waiting count, and recent duration/throughput. User-facing labels are **Data
retrieval**, **Data processing**, and **Control work**; technical keys remain in
administrator detail. An administrator may change a pool only within its
reviewed minimum/maximum, with a required reason and audit record. The Ready
limit, domain locks, dependency rules, and recovery policy are not capacity
knobs.

The Jobs and Activity pages use the same lifecycle labels and counts. Normal
operator surfaces never show lanes. Administrator detail may show capacity
pools, protected domains, wait evidence, definition revision, and claim owner.

### 7. Preserve compatibility and tenant boundaries

Create a forward migration after 0254; do not edit a committed migration.
The migration supersedes the capacity-three policy, distinguishes execution
pools from domain locks, installs the central dispatch APIs, and preserves all
historical rows. Old immutable queued definitions remain executable through a
bounded compatibility branch that honors their old lane/global claims until
they drain; no history is rewritten and no successful work is invented.

Retain ADR-0024's accepted tenant-1 execution boundary for this change, enforce
RLS throughout, and introduce no new hard-coded tenant assumptions. Global
pool coordination must disclose no tenant-specific run details. Enabling a
second tenant remains a separately validated rollout.

## Non-goals

- No dataset-versioning framework, event-store rewrite, or duplicate current
  data model.
- No merge of Job runs with source demand, source actions, findings, or audit
  records.
- No operator editing of correctness locks, retries, deadlines, or recovery
  authority through the capacity form.
- No claim that every materialized view is safe to refresh concurrently; each
  changed path requires its own index and behavior evidence.
- No direct Portainer deployment, manual migration, queue deletion, or run
  history rewrite.

## Affected artifacts

- `operations/docs/decisions/0026-jobs-dispatch-and-capacity.md`: supersede
  ADR-0024's lane-capacity and queued-presentation clauses while retaining its
  admission, fencing, dependency, isolation, and recovery contracts.
- `shared/jobs_registry.py`: separate `capacity_keys` from domain
  `resource_keys`; retain legacy lane metadata only for immutable compatibility.
- `ingest/operator_job_queue.py`: database-coordinated promotion/claim adapter
  and truthful wait transitions.
- `ingest/jobs_worker.py`: stateless, run-keyed local child supervision rather
  than one child per lane.
- A forward Operations migration after 0254: resource kinds, pool policies,
  restricted dispatch/capacity APIs, compatibility behavior, grants, RLS, and
  stable lock order.
- `operations/apps/core/views.py`, `operations/config/urls.py`, Jobs/Activity
  templates, and the Jobs control-plane template: shared lifecycle and pool
  presentation plus audited pool controls.
- Focused registry, worker, migration, tenant/RLS, view, and template tests.

## Implementation slices

### Slice 1 — Decision and complete definition audit

1. Write ADR-0026 with the four-concern model, lock order, lifecycle mapping,
   Ready bound, execution pools, compatibility behavior, and failure modes.
2. Inventory every executable definition's external I/O, processing, control,
   domain writes, materialized-view refreshes, connection behavior, and output
   revisions.
3. Assign capacity keys from inspected handler behavior. Keep uncertain broad
   domain locks until evidence supports narrowing them.
4. Add registry validation: known pool keys, at least one pool where required,
   fixed domain-lock policy, and no pool key in `resource_keys`.

Gate: every executable key has reviewed capacity and domain ownership, and the
registry remains standard-library-only and deterministically digested.

### Slice 2 — Durable policy and dispatch APIs

1. Add a resource kind that distinguishes `execution_pool`, `domain_lock`, and
   legacy compatibility rows, or an equivalent normalized relation that keeps
   those authorities separate.
2. Seed the three pool policies and reviewed bounds; supersede the 0254
   capacity-three API without deleting its history.
3. Add restricted, tenant/RLS-safe promotion and central claim functions.
4. Acquire capacity and domain claims atomically in stable order, recheck
   dependency freshness, scan past blocked candidates, and maintain exact wait
   category/reason evidence.
5. Enforce at most two Ready runs under one database coordinator lock.
6. Retain a compatibility claim path for old immutable queued definitions.

Gate: database contention tests prove the Ready bound, no partial claims,
same-domain exclusion, disjoint-domain concurrency, multi-pool atomicity,
cross-tenant non-disclosure, and fair scan past blocked work.

### Slice 3 — Stateless isolated worker supervision

1. Replace lane iteration and the lane-keyed child map with database claims and
   a run-keyed map of local children.
2. Enforce the deployment-wide emergency child ceiling in the database while
   relying on pool claims for normal admission.
3. Preserve claim token/generation fencing, heartbeats, deadlines,
   cancellation checkpoints, shutdown containment, and replay-safe recovery.
4. Give each supervisor its own runtime identity and heartbeat; do not require
   worker leader election.
5. Report active pool use, deployment-wide child count, and local child count
   in runtime diagnostics.

Gate: focused process tests prove independent jobs overlap, conflicting jobs
do not, control work remains responsive, two supervisors cannot over-claim,
and shutdown contains every live local child without orphaning claims.

### Slice 4 — Operator and administrator surfaces

1. Centralize lifecycle mapping so Jobs, Activity, Health, and APIs produce the
   same Ready/Waiting/Running/terminal result.
2. Count only Ready runs as queued; group Waiting by factual reason.
3. Keep Operations and visible steps as the normal organization.
4. Replace lane/global forms with audited execution-pool controls and usage.
5. Show domain claims read-only in administrator detail.
6. Ensure current status and immutable history remain separate.

Gate: focused request/template checks cover empty, Waiting, Ready, Running,
attention, mixed-operation, and pagination/filter states without a 500.

### Slice 5 — Compatibility, rollout, and proof

1. Run focused Python, registry, Django, SQL/migration, template, and
   `git diff --check` validation; keep testing proportional but include the
   concurrency invariants.
2. Review the migration plan from 0253 through the new forward migration and
   prove both cases: an environment where 0254 is already applied and one where
   it is applied immediately before the corrective migration.
3. Before push, calculate worst-case child connection demand against live
   Postgres headroom and verify no blocking materialized-view path defeats the
   proposed overlap.
4. Obtain separate commit and push approvals. Push origin first and the mirror
   second. Do not invoke Portainer.
5. Verify automatic rollout: migration applied, registry/worker healthy,
   Ready never above two, pool use truthful, unrelated work overlaps, same
   domain remains serialized, old queued definitions drain, and Jobs/Admin
   pages render.

## Acceptance criteria

1. Operators see Operations and steps, never scheduler lanes.
2. `Queued` means Ready and its count never exceeds two; Waiting is displayed
   separately and may exceed two without being mislabeled as queue depth.
3. Every non-running active run has one truthful wait/ready reason.
4. No global job-count claim controls ordinary admission; the deployment-wide
   process ceiling is only an emergency safety fuse.
5. Jobs acquire all declared capacity pools and domain locks atomically.
6. Same-domain writers cannot overlap; unrelated work can overlap when pool
   capacity exists.
7. Support/control work cannot be crowded out by long processing work.
8. Pool capacities and use are visible and audited; domain locks are not
   operator-editable.
9. Existing schedules, requests, dependencies, history, recovery evidence,
   operation lineage, and old definition snapshots remain readable.
10. No data-versioning layer or broad data-model rewrite is introduced.
11. Tenant/RLS and global-resource privacy behavior pass focused tests.
12. Automatic rollout and live behavior are verified without direct Portainer
    action.

## Validation plan

- Registry contract and digest tests for separate capacity/domain metadata.
- PostgreSQL contention tests for Ready promotion, pool capacity, stable claim
  order, same-domain exclusion, disjoint concurrency, and compatibility runs.
- Worker process tests for multiple children and supervisors, fencing,
  heartbeat, completion, cancellation, no over-claim, and shutdown containment.
- Existing Jobs dependency, coalescing, supersession, recovery, and schedule
  suites to catch contract regressions.
- Focused Django views/templates and Admin audit tests.
- `python manage.py check`, changed-module compilation, migration review, and
  `git diff --check`.
- One read-only live rollout audit of migrations, capacities, active/waiting
  state, claims, runtime heartbeat, and Jobs/Admin HTTP behavior.

## Current checkpoint and next action

The four-concern design, truthful Ready/Waiting contract, execution pools,
fixed domain locks, and database-coordinated stateless-supervisor model are the
final implementation plan. Implementation was authorized on 2026-10-06.
Completed in the working tree: ADR-0026; reviewed pool/domain declarations for
every executable definition; migration 0255 with durable pool policy,
Ready-window promotion, atomic multi-pool/domain claims, and compatibility for
immutable historical definitions; a stateless worker supervisor; pool-only
administrator controls; and matching Ready/Waiting/Running language on Jobs
and Job activity. Migration 0254 was corrected before application because its
policy revision values violated the already-existing 64-character revision
constraint.

Validation completed: changed Python modules compile; registry validation and
the focused pool-dispatch migration contract pass; `git diff --check` passes;
Compose configuration validates. Focused Django and pytest suites remain unavailable because the local virtual
environment lacks Django and pytest. PostgreSQL contention and rollout checks
also remain pending until a reviewed deployed environment is available.

Production checkpoint (2026-10-06): a read-only Operations startup-log review
confirmed that the previously pushed 0254 migration is failing before it can
be recorded, because its `capacity-3` policy revision violates the existing
64-character revision constraint. Operations is restarting at this checkpoint.
The working-tree correction replaces every invalid 0254 revision literal with
a valid immutable digest; 0255 then supplies the approved pool-dispatch
design. Local development dependencies were installed only in the ignored
workspace virtual environment. `manage.py check` passed, 25 focused Jobs
tests passed, focused F/I Ruff passed, and the migration graph lists 0254 then
0255. Docker Desktop is unavailable, so PostgreSQL contention tests cannot
run locally.

Next action: commit and push the approved Jobs recovery/rework to `origin`
then `a-m-rose`; do not invoke Portainer. Verify automatic migration recovery,
container health, Ready/Waiting behavior, and pool diagnostics through
read-only checks afterward.

Rollout correction (2026-10-06): after 0254/0255 applied and the stack became
healthy, a read-only queue audit found one queued dependency run whose durable
wait category was correct but whose persisted stage still said `Waiting for
capacity`. Migration 0256 makes the existing queued-write trigger derive every
queued stage/detail from its durable wait category and repairs existing queued
rows. This keeps the operator-visible lifecycle and stored state truthful.
