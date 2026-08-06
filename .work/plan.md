# Active root implementation plan

Track: **ADR-0010 generic entity, claim, relationship, and admin completion**

**Status (2026-08-05, end of session):** E1-E5.3 complete and deployed. E6 step
one (entity anchors required) deployed and verified. Deployed head `3c7d9a1` on
both remotes; all containers healthy; working tree clean.

**Deployed: retire `device_links` (E6).** Release `0.111.0`, commit
`6019b0a`, on both remotes. Migration 0121 applied; its parity gate reported
`5298 rows, 0 differences`. `operations.device_links` is gone,
`v_device_source_link` is live as a `security_invoker` view, and the first
post-deploy cycle synced 8,355 links and refreshed derived state in 10.19s
with zero errors. Patching scope held at 2,643 Included / 1,926 Excluded.
Stale-but-live links are 0 across all four sources, down from 8,316.
One follow-up recorded in `.work/backlog.md`: the new view inherited DML
grants from schema default privileges that it cannot honour.

### device_links retirement (E6) — done

`operations.device_links` is gone. `operations.v_device_source_link` over
`entity_source_links` replaces it, maintained for every source by
`sync_entity_source_links_from_observations()`. Attachment authority is
observations, per ADR-0012. No compatibility alias remains — all readers moved
in the same release.

**Six writers removed**, not the five the backlog listed. The sixth was
`views._merge_devices`, which did `UPDATE` + `DELETE`. It now moves only the
observations; the links follow on the next sync with history intervals
correctly closed. Writing `entity_source_links` directly would have orphaned
the open `entity_source_link_history` row.

**The ordering trap was in two places**, not one: the resolver promotion guard
and `fast_path` step 1 both read the table inside the transaction that wrote
it. Both now read `entity_observation_current.device_id`, which the same
transaction writes — zero disagreements across all four sources in production.
Both also gained an `entity_type` filter the old unique key could not express.

**A compatibility view was built first and rejected.** It required inventing
`match_method` / `match_confidence` / `external_name` constants and a synthetic
primary key, and it was a ~365x performance regression: building
`device_patching_scope_current` took 247 ms against the original table, >90 s
through the aggregating view, and 278 ms through the flat view that shipped.
The aggregate planned *identically* to the fast form — same nodes, same cost
estimate — so only execution against production exposed it.

The aggregate turned out to be unnecessary. Ninja is the only source with two
namespaces, and `device-health` is the health-poll companion of the same
records (already excluded from presence by migration 0098). Excluding it gives
exactly one row per key: verified identical row sets (14,286 each, zero either
side), zero duplicate keys, zero disagreement on `missing_since` presence and
`last_seen_at`.

Defect fixed, measured after cutover: stale-but-live links are **0 across all
four sources** (was 8,316), and `missing_since` is maintained everywhere —
LogMeIn 65, Ninja 392, ScreenConnect 7, SentinelOne 138.

Validation: `manage.py check` clean, `makemigrations --check` clean, 74 ingest
tests + 42 Operations tests pass, Ruff unchanged at 67 findings (zero
introduced). Full migration dry-run against production completed in **567 ms**
with its parity gate reporting `5298 rows, 0 differences`; `device_links`
absent, `v_device`/matview restored with exact owners, options and ACLs, and
`operations_app` holding SELECT only on the new view.

Operational note for deploy: the migration holds ACCESS EXCLUSIVE on the
dropped relations for ~0.6 s. Run any production dry-run with server-side
`statement_timeout` **and** `idle_in_transaction_session_timeout` — a killed
client does not stop the server-side transaction, and one such orphan blocked
ingest for ~3 minutes during this session until it was cancelled.

### In progress — retire `client_links` (E6)

Second of E6's compatibility tables, after `device_links` (ADR-0014).

**Mapping verified 2026-08-06.** 320 rows both sides against
`entity_source_links` where `entity_class_id = 'client'`. One benign
difference each way: ScreenConnect's instance-level key was renamed
`sc_uta` -> `self`, same client `6d3418ea`. Zero clients disagree about which
entity a source identity attaches to. No dependent database objects. **No
companion namespace to exclude** — each source has exactly one
(`company`/Hudu, `group`/LogMeIn, `organization`/Ninja, `site`/SentinelOne,
`source-instance`/ScreenConnect), so unlike the device side there is no
`device-health` analogue and no risk of the aggregate that cost 90 s there.

**No same-transaction ordering trap.** `_load_client_links`
(`source_observations.py:265`) and `_upsert_client_links` (`:536`) sit in one
transaction, but the read is first and the write last, so the read only ever
serves links from prior cycles. `entity_source_links` is synced at the
collection boundary by `derived.refresh_after_collection`, which gives the
same staleness. This is the check that made the device-side retirement risky;
it does not apply here.

**The reason this is worth doing is a near-totally suppressed detector.**
`client_name_conflict` skipped the finding when the observed source name
matched the stored `client_links.external_name`, which `client_resolver`
refreshed to the observed value on every sync. Measured after deployment: 1
open finding existed beforehand (2026-07-13), 50 appeared on the first run
after the change, 51 open now. Same defect class as the Ninja-only filter
behind `device_links`.

**Measurement correction, recorded so it is not repeated.** This was first
written up as "zero findings, cannot fire", which was wrong twice: these
findings live in `operations.admin_findings`, not `operations.findings`, and
the comparison uses `_norm()` (strips whitespace, hyphen, underscore, dot),
not plain lowercase. Two wrong measurements agreed with each other, so neither
caught the other. Check the table and the comparison function before calling a
detector inert.

**Decision: surface the 56.** The current behaviour hides them with no
operator decision and no record, which the "nothing hidden" rule forbids. An
as-linked *accepted* name would be a legitimate suppression, but only as a
recorded acceptance — that is a separate feature, and building it first would
keep the drift hidden meanwhile. `external_name` therefore disappears with the
table rather than being reproduced; the attribute contract cannot supply it in
any case (`claim(name)` is per (client, source_instance), `external_name` is
per (source, external_id) — the join fans 320 links to 522 rows, 204
differing).

**Scope.** Writers to remove: `_upsert_client_links`
(`source_observations.py:178/536`), the `client_resolver` INSERT (`:272`), and
the `views.py` INSERT. Readers to repoint: `_load_client_links`
(`source_observations.py:163`), `client_resolver` drift/matching queries,
`core/devices.py`, `client_workspace.py`, `views.py`, the `client.links` ORM
accessor plus `org_index.html`. Model `ClientLink` becomes unmanaged
`ClientSourceLink` on a new `v_client_source_link` view; admin read-only.
Migration drops the table after repointing, mirroring 0121.

**Next action.** Build `v_client_source_link`, repoint readers, remove the
three writers, change the drift detector to compare observed against the
canonical client name only, then dry-run the migration against production and
confirm the finding count moves 0 -> 56.

### Capability restored after the `bootstrap_clients_from_ninja` retirement

Retiring that command in 0.112.0 followed a documented decision (BLUEPRINT
Track C superseded it 2026-07-13, removal scheduled as C.7), but it removed a
working behaviour: Ninja org renames were applied to `clients.display_name`
while preserving `slug`.

Track C's replacement is "name drift = finding, never re-match", and
`human_labels` already labels `client_name_conflict` as "Client renamed at
source". The finding half existed; **the apply half was never built**, so the
only action on an admin finding was acknowledge. Between 0.112.0 and 0.113.0
the capability was therefore absent.

0.113.0 adds the apply action, completing the designed replacement rather than
restoring the command. Renames are now operator-reviewed instead of silently
applied, which is what Track C intended, and the 50 drift findings surfaced in
0.112.0 are the backlog of renames that had accumulated while the detector was
suppressed.

Rule this reflects: a workflow is fixed or recreated, never removed. A prior
repository decision to delete one still collides with that and should be
surfaced rather than acted on silently.

### E6 remaining scope — resolved 2026-08-06 (ratified in ADR-0013 amendment)

The phase line reads "obsolete compatibility columns/readers" and was never
enumerated. It covers two halves; only one is actionable.

**Columns — closed, they stay.** Codex design history framed the flat
`operations.devices` cache columns as transitional ("validating
cache/projection equality until the compatibility columns are dropped"), which
conflicts with this track's later entry that they are permanent. Measurement
settles it without needing the preference: `os_group` and `device_type` have
**0 of 5,298** effective-contract rows and no source to give them one — the
projector derives them instead. Dropping them is not achievable until that
source is built, which is separate work and not an E6 gate. Supporting
figures, measured 2026-08-06: `os_family` 5,244/5,298 effective coverage,
`device_role` 4,721, `os_name` 4,720, with **zero** mismatches wherever a
value exists; flat read 4.7 ms against 362.9 ms pivoted from the contract.
The single-writer projector plus its ratchet test is therefore the permanent
enforcement, not an interim one.

**Tables — this is E6's remaining work.** Measured 2026-08-06:

| relation | rows | code readers | note |
| --- | --- | --- | --- |
| `client_links` | 320 | 12 | **exact twin of the retired `device_links`.** `entity_source_links` holds 320 `client` rows — 1:1. |
| `client_candidates` | 9 (8 open) | 6 | **keep — not debt.** The preventive workflow that makes client merging unnecessary: its *map* action attaches a differently-named source group to an existing client before a duplicate can be created. Zero duplicate clients across 76 confirms it works. See the ADR-0012 amendment. |
| `merge_candidates` | 0 | 3 | **surface with no producer** — nav badge, workspace section and admin, but nothing writes it. See backlog; decide whether the feature is wanted before dropping. |
| `source_bindings` | 5 | 28 | duplicates `source_instances` (also 5); most readers, least urgent |
| `ninja_device_detail_current_shadow` | 5,499 | 6 | **keep — not debt.** Adapts `entity_observation_current.canonical_data` JSON into a typed columnar contract, which is the same pattern as `v_device_source_link`. Retiring it would push the JSON extraction into 6 readers. |
| `ninja_device_health_current_shadow` | 5,499 | 2 | keep, as above |
| `ninja_device_seen_daily_shadow` | 357,669 | 3 | keep, as above |
| `device_agent_presence_current_legacy` | 0 | 0 | dead matview — dropped in 0124 |
| `source_health_current_legacy` | 4 | 0 | dead matview, superseded by `source_health_current` (5 rows) — dropped in 0124 |
| `client_user_links` | 0 | 2 | **not an E6 table.** Data structure for the unbuilt Users capability — see below. |

**E6's table list is closed — none of the eight was compatibility debt to
retire beyond the two link tables and two dead matviews already done.** `device_links` and
`client_links` are retired; the two dead matviews are dropped;
`merge_candidates` was a missing producer, now fixed; the three shadow views
and `client_user_links` are not compatibility debt at all. `client_candidates` and `source_bindings` both stay: the
first is the preventive client workflow (ADR-0012 amendment), the second
carries the collector and schedule dimension that `source_instances` does not.

**E6 is complete.** Entity anchors required (`322d2a4`), competing attachment
authority retired (`device_links` 0.111.0, `client_links` 0.112.0),
compatibility columns closed by ratified decision, and the compatibility table
list resolved.

**Why the shadow views stay.** They were listed for retirement because the
name implies a temporary duplicate. They are not: each adapts the generic
observation store's JSON into a typed columnar contract in one place, exactly
as `v_device_source_link` does for source links. Retiring them would duplicate
the JSON extraction across 11 readers. Renaming to drop "shadow" was
considered and rejected — touching 11 readers for a naming improvement is the
kind of churn that silently broke `device_merge.html` earlier in this session.
Documented here instead so they are not re-listed as debt.

**Correction on the shadow views.** They were listed as empty because the
inventory joined `pg_stat_user_tables`, whose `n_live_tup` covers tables only
and silently reports 0 for every view and matview. Counted directly they hold
5,499 / 5,499 / 357,669 rows and are working correctly — they are the *new*
path wearing legacy names, not abandoned debt. Nothing is broken there, so
they drop down the order rather than up it. Count a view before calling it
empty.

### Deployed this session

| commit | change | verified |
| --- | --- | --- |
| `c3dcd9d` | os_name to os_family becomes data (migration 0118); os_family returns NULL not 'Unknown' | 123/123 os_name values identical; 13,716 stale `Unknown` claims cleared to 0 |
| `7e57ba3` | device cache projector is sole writer of five columns; nine producer writes removed | live run matched dry run exactly; all five columns 0 changes after convergence |
| `803417d` | node_class taxonomy becomes data (migration 0119); evidence counter corrected 379 to 33 | `device_type` 0 changes live, so table-driven derivation is behaviour-preserving |
| `79f4462` | mapping-table loads contained in a SAVEPOINT | fixes a defect 803417d shipped; clean startup, no `InFailedSqlTransaction` |
| `322d2a4` | Client/Device entity anchors required (migration 0120) | both columns NOT NULL; promotion path proven by a rolled-back transaction |
| `e52eb20` `aa500f7` `d8243b6` `3c7d9a1` | records: findings sanitization closed, backlog findings, ADR-0013 amendment, device_links rule | docs only |

### Decisions closed this session

- **Findings sanitization: no code required.** Of 139 matching findings, 43 are
  publisher strings containing vendor URLs, 95 are Hudu clickthrough links, 16
  are real serials across 14 findings. No exposure path exists — no
  finding-detail route, no API, and `operations.findings` grants SELECT only to
  `metabase_ro` and `operations_readonly` under forced RLS.
- **`v_device_current` retracted** (ADR-0013 amendment). It was never built so
  never had consumers; `v_device` predates ADR-0005 and is the read surface;
  release 0.64.0 recorded that the flat columns stay as a cache; and pivoting
  from the effective contract is ~70x slower (5.5 ms vs 383.6 ms).
- **The flat Device columns are permanent** as a single-writer projection. The
  defect was nine producers, not the cache.
- **The typed layer tables stay.** No retirement pressure now that
  `v_device_current` is retracted.

### Deferred, with reasons recorded in `.work/backlog.md`

Unscoped entities (not an E6 gate; needs an RLS policy replacement on a
forced-RLS table); write-only layer tables and
`agent_instance_field_history` at 0 rows; silent `conflict = false` on genuine
source disagreement; the 33 unevidenced form factors; the remaining hardcoded
mapping tail.

## Authority and checkpoint

- The user authorized autonomous implementation, commits, both pushes, and
  their coupled Portainer deployments. Validation should remain basic and
  proportional: syntax/static checks, migration consistency, and basic
  deployed version/health/HTTP-500 and aggregate behavior checks. The user
  explicitly waived further local Docker rehearsal for this phase.
- Release `0.103.0`, commit `0f32922`, is deployed on both remotes. All enabled
  collector families use the generic source-record current/change-history
  contract. The verified cycle wrote zero legacy Ninja detail/health snapshots.
- Existing unrelated backlog, instruction, design, and probe-file changes are
  preserved and excluded from release commits.
- Agent Compliance redesign/cleanup and legacy Ninja historical deletion/disk
  reclamation remain explicitly excluded. Existing typed patch, software,
  immutable activity, audit, notification, finding, and run-ledger semantics
  remain distinct from accidental poll-copy storage.

## Production sizing findings (aggregate-only, read-only)

- Generic source storage contains 30,088 stable current records, 29,240 active,
  57,955 retained material intervals, 341,130 daily rollup rows, and 695 compact
  snapshot-run rows. The measurement returned no identities or payload values.
- Expanding normalized top-level scalar/set members produces 428,425 current
  claim rows (417,931 active). Per-record claim medians are 5-20 by contract;
  p95 is at most 21 for the large namespaces and the measured maximum is 46.
- Attribute-level comparison, excluding unchanged projection-contract-only
  intervals, found 50,107 changed claim members in the latest seven-day window.
  Because Ninja health existed for only part of that window and rollout changes
  are recent, use a conservative 7,200-10,000 changed-member/day envelope.
- Projected claim-history additions are 216k-300k at 30 days, 648k-900k at
  90 days, and 2.63m-3.65m at 365 days. With a deliberately conservative
  256-512 bytes per heap-plus-index row, current claims require about
  105-209 MiB; history requires 53-147 MiB at 30 days, 158-440 MiB at 90 days,
  and 642 MiB-1.74 GiB at 365 days. WAL remains an estimate until a disposable
  scale benchmark: roughly 2-4x changed indexed bytes, or about 1.3-7.0 GiB at
  the 365-day envelope.
- Existing physical totals are 182.6 MiB generic current, 70.8 MiB generic
  history, 45.5 MiB daily rollup, and 0.7 MiB snapshot runs. Typed stores are
  materially larger but semantically intentional: activities 7.02 GiB, patch
  facts 864.6 MiB, software current 1.46 GiB, and software history 445.7 MiB.
- Initial claim history does not justify partitioning below four million rows
  per year. Use identity/open-interval B-tree indexes plus a time BRIN, retain
  closed claim history for 90 days in line with source material history, and
  retain compact daily rollups for at least 365 days. Revisit partitioning at
  10 million retained rows or sustained 25,000 changed members/day.
- Claim current rows must not receive heartbeat writes. They change only when
  an attribute value, supporting evidence, authority, or withdrawal changes;
  last receipt/contact remains inherited from the source-record current row.

## End-state acceptance

1. Every canonical client/device has a stable generic entity anchor without
   changing existing typed IDs or foreign keys.
2. One authoritative generic source link maps each attached stable source
   identity to an entity; compatibility links remain until all readers cut over.
3. Deployment-controlled definitions and mappings produce typed, sensitivity-
   classified current claims and attribute-delta history without per-poll
   duplication. Unmapped fields default restricted and remain visible by count.
4. Authority policy and audited operator decisions produce one rebuildable
   effective-value contract. Equal-authority conflicts are visible and never
   silently broken by recency.
5. Relationship evidence, canonical edges, decisions, candidates/events, and
   source-native events preserve provenance and withdrawal independently.
6. Generic read models and Operations admin pages expose entities, sources,
   evidence, claims/conflicts/effective values, candidates, relationships, and
   source health without source-name template branches.
7. Existing typed device/session/patch/software consumers move only when their
   effective projections have measured parity. Compatibility columns/tables
   and destructive cleanup remain separate final contracts.

## Delivery phases

### E1 — Generic entity and source-link kernel (`0.104.0`, complete)

- Add entity-class/scope registries and the tenant-scoped generic entity anchor.
- Add nullable unique entity anchors to Client and Device, backfill them while
  preserving typed primary keys, and keep typed tables authoritative.
- Add generic source-link current/history and generic candidate current/events.
  Backfill links from exact stable observation identity plus existing resolved
  client/device compatibility IDs; unresolved evidence remains unattached.
- Expose populated registries/entities/links read-only; keep empty candidate
  admin pages hidden until the E4 engine exists, per the engine-first UI rule.
- Expand entity-type capabilities required by ADR-0010. Add read-only Django
  admin visibility. Apply RLS, tenant-consistent uniqueness, least-privilege
  grants, and additive rollback-safe constraints.

### E2 — Attribute definitions and delta claims (`0.105.4`, complete)

- Add versioned attribute definitions, source-field mappings, identity/
  attribute authority policies, typed current/history claims, and withheld
  classification counts.
- Seed the normalized fields required for identity, lifecycle, session,
  operating-system, source health, and CMDB evidence; all unmapped fields are
  restricted and counted rather than silently trusted.
- Backfill roughly 428k current claims in bounded batches. Project only changed
  attributes on later material transitions; do not update claims for heartbeat-
  only polls. Add 90-day closed-history retention and threshold monitoring.

### E3 — Effective values and operator decisions

- Add audited single/set operator decisions, conflict rows, effective current
  values, and supporting-claim references.
- Implement deterministic policy selection: operator decision, authoritative
  eligible claims, then lower-tier claims. Equal-authority single conflicts use
  the definition policy (`retain_last_uncontested` or `unknown`).
- Add one projector and parity reports; connectors/resolvers may not write
  effective typed cache fields directly after promotion.

### E4 — Relationships, candidates, and generic source events

- Add relationship type/policy registries, unresolved external relationship
  evidence, canonical edges, supporting evidence, and audited include/exclude
  decisions.
- Promote candidate current/events to the generic review authority and migrate
  existing identity/client candidate workflows through compatibility views.
- Add immutable generic source events. Implement Ninja `NODE_DELETED` capture
  with protected actor metadata and source-withdrawal confirmation; never
  auto-retire a canonical entity.

### E5 — Generic read/admin surface and consumer cutover

- Add tenant-safe entity summary, source evidence, claim/conflict/effective,
  relationship, candidate, and source-health read models.
- Add Operations Admin landing/detail surfaces driven by registries, including
  restricted-value redaction and permission-checked audited reveal.
- Repoint APIs, exports, findings, notifications, evaluators, and approved typed
  readers to the shared effective contracts. Verify aggregate parity per reader.

### E6 — Contract and operational follow-up

- Make Client/Device entity anchors required only after full parity. Retire
  competing attachment authority and obsolete compatibility columns/readers in
  separately reviewable contract migrations.
- Keep Agent Compliance retirement and Ninja snapshot archive/delete/reclaim as
  independent backlog operations with their own backup/restore and destructive
  approvals. Audit/event retention and fleet-wide audit UI remain their defined
  follow-up tracks where not completed by E4/E5.

## Next E4 scope

- Add deployment-controlled relationship types and authority policy, unresolved
  source relationship evidence, canonical/effective edges and support, and
  audited include/exclude decisions.
- Activate the existing generic candidate/event foundation as the review
  authority while preserving current typed workflows until their measured
  compatibility cutover.
- Add immutable generic source events and route Ninja `NODE_DELETED` through
  the common event/withdrawal contract without retiring canonical entities or
  exposing protected source-actor metadata.
- Update root/Operations plans, ADR-0010 progress, `VERSION`, and
  `CHANGELOG.md` with the implemented E4 contract.

## Basic validation and deployment

- `python manage.py check`, `makemigrations --check --dry-run`, targeted Python
  compile/Ruff/tests on changed files, and `git diff --check`.
- Verify aggregate relationship/candidate/event counts, RLS/policies,
  uniqueness and tenant consistency, decision audit triggers, idempotent event
  capture, and safe deletion-event withdrawal behavior.
- Commit only E4 release files, push `origin`, immediately trigger Portainer,
  push the identical commit to the mirror, then verify its version, migration
  application, service health, expected root status, and zero HTTP 500s.

## Current checkpoint and next action

Phase E1 is deployed as `0.104.0` / `5b2e873` on both remotes. Migration 0101
is recorded; production has 5,336 anchors, 24,924 current links and the same
number of open attachment intervals, with zero unanchored typed records,
duplicate stable links, or tenant/class mismatches. All five tables have
forced RLS and policies. Operations/ingest/Postgres are healthy, root/health
return 302/200, and there are zero HTTP 500 or ingest error markers. The first
Operations start deadlocked during 0101; its normal restart applied the
migration successfully and no recurring error remains.

E2 is deployed. The first `0.105.0` deployment applied
migration 0102, then PostgreSQL rejected 0103 table DDL while its newly seeded,
initially deferred foreign-key triggers were pending. The transaction rolled
back cleanly. Corrective release `0.105.1` validates those deferred constraints
before table-level RLS/ownership DDL. Migration 0103 then applied; its first
accelerated projector call wrote no claims and exposed unqualified
`pgcrypto.digest` under the restricted security-definer search path.
Corrective `0.105.2` proved that `pgcrypto` is not installed. Production
catalog measurement confirmed PostgreSQL's built-in
`pg_catalog.sha256(bytea)` is available; corrective `0.105.3` uses it without
adding a dependency and replaces the projector through migration 0105. The
full backfill then completed at 30,097 source records and 266,113 current/open
claim intervals. The immediate no-op exposed avoidable full-JSON re-hashing;
corrective `0.105.4` reuses the stored source `material_hash` plus version/link
metadata and replaces the projector through migration 0106.
Definitions/mappings and independent authority policy are deployment-controlled;
unmapped fields are restricted/count-only; current claims and per-member SCD-2
history are projected in separately committed bounded batches after migration;
heartbeat/contact timestamps remain on source current and do not create claim
writes. Basic Python, Django, migration-drift, retention, and diff checks
passed; the only Ruff findings were four pre-existing observation models
outside E2.

Corrective `0.105.4` / `032dc07` is on both remotes and deployed. Migrations
0104-0106 are applied and the one-time projection-hash refresh completed in
seven bounded transactions across 30,152 processed records. It recorded only
real intervening deltas: 71 inserted, 737 updated, and 36 withdrawn claims;
808 history intervals opened and 773 closed. The immediate steady-state pass
completed in 0.431 seconds with zero processed records or writes. Production
now has 30,103 source-current/projection/withheld rows, 266,184 current claims
(266,148 active and 36 withdrawn), and 266,921 history rows (266,148 open and
773 closed). There are zero duplicate current members, duplicate open
intervals, active/open-presence mismatches, tenant mismatches, or definition
type/cardinality mismatches. All five E2 tenant tables have forced RLS and one
tenant policy. Version is `0.105.4`; Postgres, ingest, and Operations are
healthy; root/health return 302/200; recent HTTP 500, traceback, and ingest
error counts are zero.

E3 is deployed as corrective release `0.106.1` / `7f07124` on both remotes.
The initial `0.106.0` deployment applied 0107, then PostgreSQL rejected 0108
because its initial dirty-key seed left deferred tenant constraints pending
before ownership DDL; the transaction rolled back and no typed consumer had
been cut over. Corrective 0108 forces the constraints before that DDL, and
migrations 0107-0109 are now applied.

The bounded initial projection completed in 363 transactions over 181,239
entity/attribute keys, producing 181,239 effective headers, 5,640 set members,
163,304 effective support rows, 168 visible conflicts, and 662 conflict-support
rows. The durable queue is empty; an immediate pass completed in 0.126 seconds
with zero processed records or writes. Duplicate, tenant/class/type/cardinality,
support, typed-value, set-status, and conflict-flag mismatch counts are all
zero. All eight E3 tenant tables have forced RLS and one tenant policy; the
tenant-scoped redacted view has exact 181,239-row parity. No operator decisions
exist yet, so production audit triggers were verified from the enabled catalog
contract without fabricating a customer-affecting decision.

Version is `0.106.1`; Postgres, ingest, Metabase, and Operations are healthy;
root/health return 302/200; current HTTP 500, traceback, ERROR, and CRITICAL
counts are zero. Both remotes match `7f07124`.

E4 was implemented for release `0.107.0`: deployment-controlled
relationship types and authority; unresolved relationship evidence; audited
include/exclude decisions; dirty-key effective edges/support; generic candidate
create/reopen/attach projection and atomic attach/reject services; immutable
restricted source events; and going-forward Ninja `NODE_DELETED` capture. A
read-only production measurement found 4,918 currently unattached source
identities (4,842 asset observed-only, 10 client observed-only, and 66 device
pending) for the bounded initial candidate projection. It also found 228
retained deletion events, all with actor IDs but none with a stable device ID;
the nested payload contains only a message. The deployment does not backfill
those historical events and never parses message/hostname text into identity.
Future deletion events withdraw evidence only when an exact stable device ID is
supplied and in order. Python compile, Django check, migration drift, focused
Ruff, nine contract tests, and diff checks pass; no local Docker rehearsal was
run. Next: commit the scoped E4 release, push both remotes with immediate
Portainer redeploy, then verify migrations, bounded candidate/no-op behavior,
aggregate relationship/event/RLS invariants, health, and current error counts.

The first `0.107.0` deployment applied migration 0110, then 0111 rolled back
because the relationship-type seed left initially deferred entity-class foreign
keys pending before ownership DDL. No E4 data or consumer cutover occurred.
Corrective `0.107.1` forces those constraints immediately after the seed and
adds an explicit E4 regression assertion. Next: validate, commit, push both
remotes with immediate redeploy, and complete the planned aggregate checks.

`0.107.1` then applied migrations 0111-0113 and both application containers
became healthy. The first manual bounded candidate transaction failed closed
before inserting rows because the SQL insert omitted the non-null
`latest_decision` and `latest_decision_reason` fields whose empty defaults are
Django-side only. Corrective `0.107.2` supplies both values for fresh installs
and migration 0114 replaces the already-deployed projector.

`0.107.2` / `6656385` is deployed on both remotes with migration 0114 applied.
The initial candidate projection created 4,890 candidates/events in 4.105
seconds: 4,842 asset observed-only, 10 client observed-only, and 38 device
pending. The immediate pass completed in 0.517 seconds with zero changes; the
relationship pass completed in 0.144 seconds with zero writes. Candidate
duplicate, observation, link/status, create-event, and tenant invariants are
all zero, and no eligible unmatched identity remains unprojected. E4 RLS and
trigger checks pass.

The runtime privilege check found schema-default named-role grants surviving
the original PUBLIC-only revoke, including protected `source_events` access by
`operations_app`. Corrective `0.107.3` adds migration 0115 and fresh-install
SQL that explicitly revoke all E4 table privileges from known runtime roles,
then reapply the documented least-privilege matrix.

Corrective `0.107.3` / `47bb68b` is deployed and mirrored. Migration 0115 is
applied and its deployed artifact matches the committed file. The exact ACL
matrix now passes: raw relationship evidence/history and protected source
events are ingest-only; Operations has only registry, decision, and effective
relationship access; no runtime role has DELETE. Both projectors are immediate
no-ops (candidates 0/0/0 in 0.375 seconds; relationships all zero in 0.012
seconds). Production holds 4,890 current candidates and 4,891 lifecycle
events; all six candidate invariants remain zero. All eight tenant tables have
forced RLS and one policy, and all seven E4 triggers are enabled. Both remotes
match, Portainer is active, every container is healthy, root/health return
302/200, and current HTTP 500, traceback, ERROR, and CRITICAL counts are zero.

Next: begin E5 by inventorying existing generic read models, Operations admin
surfaces, restricted-value permissions, and typed consumers against the E5
acceptance contract; then implement the smallest complete generic read/admin
slice and measured consumer cutovers without changing incompatible typed IDs.

## E5 checkpoint

- Production has 5,348 canonical entity anchors (76 clients and 5,272
  devices), five source instances, 24,980 current generic source links, 30,164
  current observations, 266,594 current claims, 181,380 effective values, 168
  conflicts, 4,890 candidates, and no current relationships. Fourteen active
  source-instance/type groups are sufficient for a row-based generic health
  surface; fixed per-class columns are not required.
- Existing attribute claim/effective views redact sensitive and restricted
  values, but the custom Operations UI has no generic entity/candidate/
  relationship surface. Source health is platform-keyed with fixed client and
  device columns, and Device Identity & raw reads observation JSON on ordinary
  GET.
- `operations_app` cannot read raw claim/history or E4 protected evidence, but
  still has direct `SELECT` on observation raw JSON and the underlying E3
  effective/conflict tables. Those grants cannot be revoked before named
  readers move to redacted views and an audited permission-checked reveal path.
- E5 will ship in reversible slices: E5.1 generic redacted read/admin and
  candidate workflow plus row-based source counts; E5.2 audited restricted/raw
  reveal and direct-table privilege cutover; E5.3 measured typed consumer
  parity/cutover. APIs, exports, evaluators, findings, notifications, and typed
  domain views move only when their output contract has measured parity.
- E5.1 release `0.108.0` / `6433f44` is deployed and mirrored. Migration 0116
  is applied. Its seven security-barrier views have the expected no-login,
  non-BYPASSRLS owner and exact app/read-only grants; ingest and Metabase are
  denied. Aggregate view counts match the underlying contracts (5,348 entity
  summaries, 24,980 source links, 168 conflicts, 4,890 candidates, 14 source
  instance/type groups, five source-health rows, and no relationships). Six
  authenticated read-only renders returned HTTP 200, containers were healthy,
  root/health returned 302/200, and current error counts were zero.
- E5.2 release `0.109.0` is implemented locally: default-denied audited reveal
  for observation and restricted claim/effective evidence, safe observation
  metadata for named write workflows, removal of raw Device GET reads, and
  revocation of obsolete observation-payload and E3 protected-table reads.
  Django check and migration drift pass; 11 focused E4/E5 contract tests and
  template loading pass. Next: complete the migration/privilege review and
  focused validation, commit, push/redeploy/mirror, then verify aggregate-only
  ACL, function, audit-contract, route, migration, health, and error behavior.

- E5.2 release `0.109.0` / `6d180bc` is deployed and mirrored with migration
  0117 applied and an exact artifact hash match. The reveal permission exists
  with zero direct/group assignments. Raw/canonical observation columns are
  denied to Operations, read-only, and Metabase; ingest retains them. E3
  protected tables are denied to runtime readers; only Operations can execute
  the two reveal functions. Device identity and generic entity GETs returned
  200 with zero raw observation SELECTs; reveal GET returned 405 with zero
  audit delta. No reveal was invoked. All stack containers are healthy,
  version is 0.109.0, root/health return 302/200, and current ERROR,
  traceback, critical, HTTP-500, privilege, and E5-table error counts are zero.
- E5.3 inventory confirms there is no data API beyond schema documentation;
  the generic entity CSV is redacted. Device presence/session/patch/software
  stores remain intentionally typed. Three independent legacy writers still
  select source precedence for Device role/OS caches (Ninja device ingest,
  resolver attribute sync, and evaluator role sync), and some older findings
  still embed sensitive serial/CMDB URL detail; those must be removed during
  E5.3 rather than treated as effective-contract consumers.
### E5.3 restated (2026-08-05, evidence-based)

The earlier parity table mixed two different kinds of column and the decision
gate rested on that conflation. Corrected:

- **Anchors need no work and the gate is closed.** `canonical_hostname`,
  `canonical_serial` and `canonical_vm_uuid` are written once at promotion
  (`resolver.py:733`, `:845`) and never updated: zero
  `UPDATE ... SET canonical_*` repo-wide, and zero `serial` / `vm_uuid` rows in
  `asset_field_history` across 5,273 assets despite an enabled trigger watching
  both fields. "Retain identity on withdrawal" is already the behaviour, so
  there is nothing to decide or build. The alarming hostname figure
  (28/5,186 exact) compared a write-once anchor against a live selection — a
  category error, not a blocker.
  Qualification (2026-08-05): the "zero `UPDATE ... SET canonical_*` repo-wide"
  half of this claim was a raw-SQL grep and missed
  `bootstrap_devices_from_ninja.py:169`, which updates `canonical_serial` and
  `canonical_vm_uuid` through the ORM. The gate still holds, but on the *other*
  half of the evidence: `asset_field_history` carries zero `serial` / `vm_uuid`
  rows across 5,273 assets under an enabled trigger, which is data evidence and
  independent of how many code paths exist. The command is manual-invocation
  only. Do not restate the code half without re-deriving it.
- **The work is five cache columns**: `os_name`, `os_family`, `os_group`,
  `device_role`, `device_type`. These are rewritten every resolver run, which
  ADR-0012 forbids. Their parity is strong and is the parity that matters:
  role 4,708/4,708, OS name 4,682/4,706, virtual flag 4,533/4,545.
- **Writer inventory: nine sites, not five.** The five-site list was derived by
  grepping raw SQL only. Re-derived 2026-08-05 by four methods — raw SQL, Django
  ORM, `pg_trigger`, and `pg_get_functiondef` — which found four more. Triggers
  and DB functions came back empty, so there is no database-side writer.
  1. `resolver.py:733` INSERT (promotion) — all five, `os_group` hardcoded
     `'Unknown'`
  2. `resolver.py:845` INSERT (promotion) — all five, same hardcoded `'Unknown'`
  3. `core/devices.py:278` `_sync_operations_device_roles` — device_role,
     os_name, os_family, os_group. Called from `devices.py:177` on the live
     Ninja collection path; arguably the primary producer
  4. `bootstrap_devices_from_ninja.py:169` — device_type, via the ORM
  5. `resolver.py:996` — device_role
  6. `resolver.py:1028` — device_type
  7. `resolver.py:1068` — os_name, os_family
  8. `evaluator.py:316` — device_role, `dev_claims.get("Ninja")` precedence
  9. `resolver.py:1078+` — facet propagation, writes `assets` / `os_instances`
     **from** the cache columns. Repoint, do not delete: removing the others
     without it freezes 5,273 assets and 5,255 os_instances.

  The two promotion INSERTs matter beyond the count: revoking `UPDATE` does not
  block `INSERT`, so a privilege-based cutover would have left both still
  stamping all five columns and looked like it worked.
  Out of scope: `evaluator.py:718` writes `lifecycle_status` (ADR-0011);
  `views.py:7590` writes `deleted_at`.
- **`os_group` and `device_type` have no effective-contract source.** Measured
  5,289/5,289 NULL for both. The projector derives them instead — `os_group`
  from `os_family` via `os_group_mappings`, `device_type` from entity type plus
  node_class — so the original "projector reads the effective contract for five
  columns" target was never achievable as written.
- **Target**: one projector reads the effective contract for `os_name`,
  `os_family` and `device_role`, derives `os_group` and `device_type`, and
  preserves the existing value where no claim is selected. The eight producer
  writes are deleted and facet propagation is repointed.
- **Enforcement is a test, not a privilege.** The projector runs on the shared
  `ingest.db` pool as the ingest role, so revoking `UPDATE` from that role would
  disable the projector along with the producers. A revoke would only add
  protection against ad-hoc `psql` writes, which self-heal on the next
  projection anyway — these are rebuildable cache columns and the blast radius
  of a violation is one cycle. Enforce with a ratchet test in the shape of
  `ingest/tests/test_no_hardcoded_domain_mappings.py`.
- **Findings sanitization: closed, no change required.** Measured 2026-08-05.
  139 findings match `serial` or a URL, and they are three different things:
  43 are false positives where the URL sits inside a software *publisher*
  string ("The Wireshark developer community, https://www.wireshark.org") and
  stripping it would corrupt the publisher name; 95 are Hudu deep links
  (`https://<tenant>.huducloud.com/a/...`) which are the operator clickthrough
  to the source record, so removing them makes `cmdb_asset_stale` and
  `cmdb_link_incorrect` non-actionable; 16 are real device serials, across 14
  findings, and in `shared_serial` the serial *is* the finding.
  No exposure path exists to sanitize: there is no finding-detail route (only
  the queue plus ack/resolve/snooze), `_detail_string` has no branch for either
  type so the queue renders nothing for them, there is no data API, and
  `operations.findings` grants SELECT only to `metabase_ro` and
  `operations_readonly` under enabled-and-forced RLS.
  An audited-reveal wrapper was considered and rejected: it would add a reveal
  surface for data that no screen displays.
- Also in scope, unchanged: run aggregate consumer parity before E6
  constraints.

#### E5.3 implementation checkpoint (2026-08-05, local, not deployed)

Done:

- Producer writes removed: `resolver._sync_device_attributes` lost its three
  derivation blocks (94 lines), `evaluator.py:316` lost its `device_role`
  UPDATE but kept the `device_role_conflict` finding, and
  `core/devices._sync_operations_device_roles` is deleted with its call site.
- Both promotion INSERTs now write neutral literals (`'unknown'`, `''`) instead
  of source-derived values. They must still name the columns because all five
  are NOT NULL; the projector fills them later in the same cycle.
- `bootstrap_devices_from_ninja` retired — orphaned since E3 per
  `SESSIONS.md:480`, docstring falsely claimed it ran from `entrypoint.sh`, and
  it carried a third form-factor classifier that returned `PHYSICAL` by
  default, the exact ADR-0005 bug.
- Projector wired into `resolve_all()` **before** `_sync_device_attributes`.
- `ingest/tests/test_device_cache_sole_writer.py` added. It parses INSERT
  column/VALUES lists positionally, so it flags a cache column only when it
  receives a bound parameter, not merely when a NOT NULL column is named.
  Verified by reintroducing one `%s` and confirming it reported exactly
  `device_type` at that line.

Correction to the target above: **facet propagation does not need repointing.**
It reads `operations.devices` — the projector's output — so it is a
cache-to-facet copy, not a second producer. It needed ordering, not a rewrite,
which removes the step that risked freezing 5,273 assets.

Deployed and verified (`7e57ba3`): the projector's first live run reported
`os_name 21, os_family 0, os_group 17, device_role 0, device_type 0,
rows_written 38` — identical to the dry run. Re-running the parity query after
it returned 0 changes on all five columns. 5,293 open assets, 0 out of sync
with `device_type`, and `os_instances.updated_at` matching the projection
timestamp, which confirms the ordering fix.

`node_class` to data is done in `803417d` (migration 0119, **not yet
deployed**). It also fixed `_like_to_regex`, which silently mishandled
backslash escapes and used unanchored `.search()` instead of LIKE's whole-string
semantics, and corrected `device_type_evidence_missing` from a spurious 379 to
the real 33.

Still open in E5.3: sanitize findings embedding serial / CMDB-URL detail, and
aggregate consumer parity before E6.

Unscoped entities moved to `.work/backlog.md` — investigated 2026-08-05 and
confirmed **not** an E6 gate, since E6 covers the tenant-scoped Client and
Device anchors and both are already fully populated.

#### Projector verified against production (2026-08-05, read-only dry run)

The projector's target SQL was run read-only against production before and
after an approved on-demand run of all five sources. Change counts, 5,293
devices considered:

| column | before | after | direction |
| --- | --- | --- | --- |
| `os_name` | 21 | 21 | trailing whitespace and `Microsoft ` prefix; effective is cleaner |
| `os_family` | 146 | **0** | all 146 were regressions to `Unknown`; cleared by withdrawal |
| `os_group` | 14 | 17 | all fixes, `Unknown` -> `Windows`, `os_family` already correct |
| `device_role` | 0 | 0 | — |
| `device_type` | 0 | 0 | — |

- **The `device_type` derivation is correct.** Zero changes across every device,
  including the hardcoded `NMS_` / `_VM_HOST` patterns. Those patterns are an
  ADR-0012 section 6 maintainability violation, not a correctness defect — the
  distinction matters, because the projector was previously described as unsafe
  to deploy.
- **The withdrawal path works.** All 13,716 `Unknown` `os_family` claims cleared
  to zero after the source runs, which is what took `os_family` from 146 to 0.
  This was the cutover gate and it is now closed by measurement, not by design
  argument.
- **The `os_group` fixes trace to writers 1 and 2** — devices stuck at
  `'Unknown'` because promotion hardcodes it and nothing revisits it.
- Net: the projector now produces 21 `os_name` improvements, 17 `os_group`
  fixes, and zero regressions on any column.
- Not yet verified: the projector's Python has never executed (the dry run
  transcribed its SQL into `psql`), steps 4-6 are untested, no test covers it,
  and the 30 devices counted by `device_type_evidence_missing` remain a mapping
  gap to close.
