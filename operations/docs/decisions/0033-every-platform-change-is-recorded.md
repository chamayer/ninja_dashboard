# 0033 — Every platform change is recorded, with a full timeline per entity

Status: Accepted 2026-10-16; not yet implemented (see the archived legacy Operations plan)
Date: 2026-10-16

## Context

What sources report is already history: observations, attribute claims,
relationship evidence and source links each keep a history table. What
Operations itself changes, automatically or through an operator, mostly does
not. Measured on production 2026-10-16:

- Recorded today: lifecycle transitions (`audit_log`), identity-candidate
  events, asset, agent-instance and OS-instance field changes (triggers),
  software installations, job and condition-policy versions, attribute and
  relationship decisions (audit triggers).
- Overwritten in place with no history table found: Computers (creation, name,
  serial, merge, deletion), findings and admin findings (status), clients and
  client mappings, identity and authority policies, finding types,
  requirement profiles, suppression and notification rules, patching scope,
  software decisions, users and permissions, and projected values such as a
  Computer's displayed name.
- `audit_log` holds 12 kinds of action; 484,016 of its rows are lifecycle
  transitions on 2,345 Computers since 2026-07-31, nearly all oscillations
  (130,094 active → needs review and 129,824 back; 112,139 active → offline
  aging and 111,640 back; 1,194 Computers with 100 to 462 transitions).
- Because Computer creation was never recorded, how the 2026-07-13 rebuild
  split server Computers cannot be determined (ADR-0032).

The Computer Activity page reads only the first Ninja record's events
(`views.py` `device_detail`).

## Options considered

- One central audit log for everything. Rejected: history belongs with the
  entity it describes, and one action touching many entities would be spread
  across unrelated rows.
- Per-entity history only. Rejected: one action (a merge touches two
  Computers, many links, findings and the displayed name) would have no single
  record of what happened and why.
- Per-entity history linked by an action record. Selected.

## Decision

### Scope

Every change to Operations state made by an automated Operations process or by
an operator is recorded. Changes reported by sources are already recorded and
are out of scope. Pure mechanics (work queues, heartbeats, locks, dirty flags)
are excluded only through the reviewed exemption list below.

Classification of what is recorded (decided 2026-10-16):

- Source evidence (observations, claims, relationship evidence, source events,
  software installations) already has history and is out of scope.
- Pure mechanics (queues, dirty flags, heartbeats, locks and capacity claims,
  caches, projection progress, run logs) are exempt, each listed in the
  registry with the test "not visible to users and not a decision".
- Decisions and state are recorded: Computers, clients, findings including
  changes to their details, merges, links, policies, configuration, operator
  decisions, users and permissions, displayed values, and `cve_match` on the
  product it concerns.
- `software_device_readiness` and `device_windows_servicing_current` are
  exempt: every change that matters to the Computer's story appears as a
  finding change or as source evidence.

### Shape

- An action record per change: when, who (operator, or process and version),
  the action type, a reason a person can read, and the structured evidence.
- History rows stored with the entity they describe (Computer history with
  Computers, finding history with findings, and so on): entity, before,
  after, the action, and the Computer and client the entity belonged to at the
  time of the change.
- Existing history mechanisms stay and are listed in the coverage registry;
  they gain the action reference where the timeline needs it.

### Security and scope of history

- Recorded columns are an allowlist per table, held in the coverage registry.
  A column not on the list is never copied into history; adding a table
  means deciding its columns.
- Secret values are never stored. For credentials, tokens, keys and similar
  columns (for example `operations.secrets`), history records only that the
  value changed, when, and by whom.
- Restricted and personal values follow the entity's own visibility: a column
  shown only with an explicit reveal (restricted evidence) is recorded
  redacted, with the reveal itself recorded as an action.
- History tables carry the entity's tenant and client and get the same
  row-level security as the entity; runtime roles append, never update or
  delete; reading history requires the permission that reads the entity.
- Actions are tenant-scoped or global. A change to a table without a tenant
  (catalog and policy rows such as `finding_types`, `entity_types`,
  `eol_product_map`) is recorded once, without a tenant or client, and shown on
  every timeline that relates to it. `cve_match` carries a tenant and is
  recorded under it, without a client.
- The registry covers every table the platform or an operator changes,
  including those outside the `operations` schema (users, groups and
  permissions in Django's tables, if they are used there); which schemas and
  tables are in scope is listed during the measurement workstream.

### Full timeline per entity

- Each entity has one timeline of its own history plus everything related.
  For a Computer: its own changes, its source records and their events,
  findings on it, displayed values, OS installation, agent instances, asset,
  software, relationships (VM and host, client), operator decisions, and the
  full timelines of Computers merged into it.
- A record that belonged to several Computers shows on every one of them,
  stored once. Entries are marked by period ("before it joined", "after it
  moved to") and the move itself shows on both sides with its reason.
- Entries are grouped by action and filtered by origin: reported by sources,
  changed by the platform, changed by people. Repetitive entries are grouped
  and expandable, never omitted. Pages load newest first, by keyset.
- The Computer page's Activity tab is renamed History.

### Lifecycle history

The oscillation was diagnosed and fixed at its cause (commit `725f8ae`): two
lifecycle steps disagreed in every evaluator run and each wrote its move.
Migration 0305 deleted the 485,220 false rows (they recorded no change; the
user decided not to keep them), merged 286 real changes that had been written
through a false step, and recorded the removal as one `audit_log.cleanup`
row. The real transitions remain and are carried into Computer history. New
lifecycle entries add a readable reason, the evidence values (source and
time) and the process version.

## Enforcement

- `operations.begin_change(...)` creates the action record and sets it for
  the transaction. Database triggers on every covered table write the history
  row in the same transaction. Until a table's writers open explicit actions,
  a change without one is recorded under an implicit action naming the
  database role and application (`application_name` is `ingest` or
  `operations`); the registry's `enforce_action` then makes a missing action
  an error for that table.
- A table rebuilt by delete and re-insert records its real differences from
  the writer instead of a row trigger (`cve_match`, through
  `operations.record_cve_match_changes`).
- A coverage registry (`operations.change_history_registry`, migration 0306)
  lists every Operations table as covered, own history, history store, or
  exempt with a reason. A table missing from it raises the admin finding
  `change_history_unclassified`; the migration test asserts every covered
  table gets its history table and trigger.
- Runtime roles may append history and action records but not update or
  delete them.
- Timeline tests cover a merge chain, a record that moved, a split, and the
  period marking.

## Rationale

Without a record of what the platform decided, its past cannot be explained or
undone: the July rebuild cannot be reconstructed and a merge could not be
reversed. Triggers make recording independent of each code path. Storing
history with its entity keeps it where readers look for it; the action record
ties together everything one change touched.

## Consequences

- History storage grows with every platform change. Daily change rates per
  table are measured before the triggers are enabled, so volume is planned,
  not discovered.
- Every write path must open an action first; code that writes without one
  fails, by design.
- `audit_log` is replaced (decided 2026-10-16). Its real rows are carried
  into the per-entity history and action records, so past lifecycle
  transitions, merges and operator decisions appear on the timelines; the table
  becomes read-only once every writer uses the action records, and is kept,
  not dropped. The false lifecycle transitions it held were removed by
  migration 0305 before the carry-over.

## Supersedes or superseded by

Extends ADR-0011's append-only lifecycle audit to every platform change.
Supersedes the 2026-10-15 plan decision "no new event store for Activity".
Related: ADR-0007 (observation history), ADR-0031 (finding state), ADR-0032
(identity, merge and split).
