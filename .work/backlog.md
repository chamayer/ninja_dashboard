# Root and cross-service deferred work

This is the proposed successor to the root-level open-work portion of
`TODO.md`. Operations-only items belong in `operations/.work/backlog.md`.

## EOL/EOS: upstream lifecycle gaps for Adobe and Visual C++

- Reason deferred: Adobe Acrobat/Reader and Microsoft Visual C++
  redistributables are the two measured high-impact lifecycle gaps, but neither
  has an endoflife.date corpus entry. Local maps, dates, or exception queues
  would violate the automated lifecycle design.
- Required path: contribute maintained product/release lifecycle data upstream
  to endoflife.date, then confirm the existing connector receives it. Add only
  narrowly scoped, migration-managed matching rules once the corpus entries
  exist.
- Constraints: no operator-maintained mappings, local date tables, broad title
  matcher, or manually refreshed candidate queue.
- Trigger: upstream corpus entries are accepted and published.

## EOL/EOS: Microsoft 365 channel currency

- Reason deferred: old Microsoft 365 Click-to-Run builds are lifecycle risk,
  but they are serviced by update channel rather than a fixed Office-product
  EOL date. The generic Office perpetual rule deliberately excludes them.
- Required path: identify a trustworthy machine-readable Microsoft channel /
  build reference, ingest it as global source evidence, and derive a
  channel-currentness finding. Do not use a periodic download-and-maintain
  spreadsheet or an operator-maintained build map.
- Trigger: an authoritative automatable source is available and approved.

## EOL/EOS: agent currency reference sources

- Reason deferred: NinjaRMM and Sentinel agent-version lag is operationally
  valuable, but current-version claims require a vendor-authoritative reference
  rather than fleet-relative inference or a manually maintained version list.
- Required path: identify and ingest supported vendor release feeds, then
  derive version-currentness findings with provenance and staleness handling.
- Constraints: no hardcoded current versions or manual update workflow.
- Trigger: a reliable vendor feed and permitted authentication/collection path
  are available.

## Operations pages 500 on gunicorn worker timeout, with no attributable cause

- Observed 2026-08-11: `/findings/?status=active&category=software&type=eol_runtime`
  returned 500 in the browser. It is **not** an application error — the only
  traceback is gunicorn's own `handle_abort` / `SystemExit`, i.e. a
  `WORKER TIMEOUT`. The worker is killed before writing a response, so the
  access log carries no `500` line and the aborted URL is never recorded.
- The page itself is healthy: that exact query string renders **HTTP 200 in
  0.90 s**, 18 queries, slowest 0.19 s; `_affected_device_rows` for
  `eol_runtime` takes 0.33 s across 368 devices.
- Four timeouts on 2026-08-11: 20:49:53, 22:10:14, 23:07:28 and 23:09:00 UTC.
  The first two precede the `c853a6e` classifier deployment at 23:04, so this
  is recurring and pre-existing, not caused by scheduling the classifier.
- Leading hypothesis, **not proven**: the software matviews
  (`software_title_current`, `v_software_safety`) are refreshed on a ~5-minute
  cycle, and a plain `REFRESH MATERIALIZED VIEW` holds `ACCESS EXCLUSIVE`,
  blocking every reader until it completes. It fits the timing and the
  `/software/` referer, but the timed-out URL was `/findings/`, which reads
  neither matview — so the mechanism is incomplete. Do not close this by
  asserting the lock story without evidence for that request.
- Two fixes worth taking regardless of the root cause:
  1. `REFRESH MATERIALIZED VIEW CONCURRENTLY` removes the reader block
     entirely. It requires a unique index on each matview; verify that exists
     or add it before proposing the change.
  2. No `statement_timeout` is set on the Operations database role, so a slow
     query rides until the worker dies instead of failing fast with a real,
     attributable error. This is why the symptom was an unattributable 500.
- First diagnostic step: make the aborted request identifiable — gunicorn does
  not log the URL on abort, so today a timeout cannot be traced to a page.
- Trigger: another user-visible 500, or the next Operations performance work.

## Intel matcher slowness — ROOT CAUSE FOUND AND FIXED 2026-08-12

**This entry originally proposed the wrong work.** It framed the matcher as
structurally too expensive and floated making it incremental or set-based. The
actual cause was a one-line indexing mistake, now fixed; keeping the original
framing would have sent someone to redesign a security-relevant path that did
not need redesigning.

- `matcher.py` filtered CPE candidates on
  `LOWER(vendor) || '|' || LOWER(product)`. The only usable index is
  `cpes_vendor_product_idx ON intel.cpes (lower(vendor), lower(product))` —
  two columns, not a concatenation — so the predicate could not use it and
  PostgreSQL fell back to a **parallel sequential scan of the whole table,
  once per installed title**, ~21k times per run.
- Survivable at 164,860 CPE rows; not after `d0b8aea` took `intel.cpes` to
  **1,799,966** (10.9x). The code never changed — the table underneath it did.
- Fixed by joining on the two indexed columns via `unnest`. Measured on
  production with identical inputs: parallel seq scan removing 596,768 rows per
  worker, versus a **20 ms index scan**, both returning the same 9,662 rows.
- Guarded by `ingest/tests/test_matcher_uses_cpe_index.py`, verified to fail
  when the concatenated form is reintroduced. The regression is invisible
  otherwise — the query stays *correct* and merely gets slower as the table
  grows, which is exactly how it survived the backfill.
- Migration 090 adds `intel_ingest_status.last_duration_seconds` so the next
  such drift shows up as a number rather than as someone waiting.

**Still open, and genuinely separate:** `matcher.py` ends with a
**non-concurrent** `REFRESH MATERIALIZED VIEW operations.v_software_safety`,
whose inline comment calls the view "small enough that a full rebuild is cheap"
with no figure behind it. That refresh takes `ACCESS EXCLUSIVE` and is a
candidate mechanism for the worker-timeout item above. Measure it before
assuming; that assumption is what this entry got wrong the first time.

**Do not make the matcher incremental** without a separate, measured case. The
full rebuild (`DELETE tenant + INSERT`) is what guarantees no stale match
survives a CVE withdrawal or CPE correction, and a silently retained match is
worse than a slow one.

## Jobs catalog: add the classifier-only entry once `views.py` is free

- `/run/software-classify-only` was added 2026-08-12 and runs the classifier
  without the intel pre-steps — the same path the scheduler uses, ~45 s against
  the enriching endpoint's many minutes.
- It has **no `_JOB_CATALOG` entry**, so an operator cannot see or run it from
  the Jobs page. That is the exact "built but invisible" pattern the Admin Jobs
  catalog item below exists to close, and it is deliberate only in timing:
  `_JOB_CATALOG` lives in `operations/apps/core/views.py`, which had unrelated
  uncommitted work in the tree at the time, and staging a whole file would have
  swept that work into an unrelated commit.
- The entry to add, beside the existing `software-classify` row:
  id `software-classify-only`, name "Software classifier (no intel refresh)",
  category `evaluators`, endpoint `run/software-classify-only`, status_key
  `software_classifier`, status_source `run_log`.
- Trigger: `views.py` is clean, or the next Jobs-page work — whichever first.

## Domain-mapping ratchet is failing on four deployed constants

- `ingest/tests/test_no_hardcoded_domain_mappings.py` fails as of 2026-08-12.
  The ratchet exists to stop new module-level domain mappings entering the
  codebase (ADR-0012 §6), so a failing ratchet means it has stopped protecting
  anything — every future violation lands in an already-red test.
- The four unlisted constants, all in `operations/apps/core/views.py`:

  | constant | arrived in |
  | --- | --- |
  | `_COALESCED_OFFLINE_FINDING_TYPES` | `319ce57` findings queue device impact |
  | `_PATCH_SEVERITY_VALUES` | `2bd4205` patch evidence filters |
  | `_WINDOWS_11_COMPATIBILITY_CHOICES` | `95c3537` Windows 11 readiness filter |
  | `_SOFTWARE_POLICY_CANDIDATE_TYPES` | `2091c02` Issues scope percentages |

- All four are **already deployed**. Verified pre-existing by stashing the
  capability-recognition work and re-running: the failure is identical without
  it.
- Each needs its own decision, not a blanket one. Some are plausibly genuine
  exemptions — `_WINDOWS_11_COMPATIBILITY_CHOICES` is arguably UI display
  choices rather than a domain mapping, and `_PATCH_SEVERITY_VALUES` may be a
  source-value normalization. Others map finding-type names to behavior, which
  is exactly what the ratchet is for and what
  `finding_types.suppressed_by_approval` (migration 0136) did instead.
- Do **not** simply add all four to the reviewed inventory to make the test
  green. That converts the ratchet into a rubber stamp.
- Trigger: next Operations work touching these surfaces, or sooner if another
  change needs the ratchet to be trustworthy.

## Migration 086 was deleted — do not recreate it

`sql/migrations/086_eol_candidates_word_and_alias.sql` existed untracked for
days, was briefly committed by mistake, and is now deleted. Recorded here so
nobody restores it from history thinking it was lost.

**What it did.** Rebuilt `operations.v_eol_mapping_candidates`, replacing the
substring matcher from 081 (`canonical_name ILIKE '%' || name || '%'`) with
whole-word regex plus corpus aliases.

**Why it is moot.** Migration 088 retired that materialized view. Verified
2026-08-13: no relation matching `%eol_mapping_candidate%` exists, and the
25 enabled rows in `intel.eol_managed_product_rules` are what does the job now.
086 would recreate a view a later migration deliberately removed.

**Why it was actively dangerous.** The ingest runner applies every pending file
in `sql/migrations/` at container start. 086 matches 21,437 titles against 462
corpus products with word-boundary regex — roughly 30 million evaluations, none
indexable. On 2026-08-13 it ran over 7 minutes without completing and held
ingest at `readyz 503`, because migrations run before the service reports
ready. A long-running migration in that directory is an outage, not a slow job.

**Its measurement is worth keeping**, since the same trap applies to any future
title-to-corpus matcher. Measured 2026-08-11 across 21,437 titles / 462
products:

| approach | pairs | device weight |
| --- | --- | --- |
| substring on name/label (what 081 did) | 20,899 | 780,486 |
| whole-word on name/label/alias | 8,019 | 103,285 |
| substring-only, i.e. rejected by whole-word | **6,937** | 365,411 |

A third of all pairs and 47% of device weight existed only because a corpus
term sat inside a longer word: `Intel(R) Trusted Connect Services Client`
matched `rust`, `ClickOnce Bootstrapper` matched `bootstrap`,
`ExpressConnect` matched `express`. Anchored or word-boundary matching is the
rule the EOL managed rules already follow, and `catalog.capability_rule` now
enforces with a CHECK constraint.

**If a candidate queue is ever wanted again:** build it as a query behind an
operator surface, not as a materialized view refreshed by a startup migration.

## Dashboard reporting performance

- Reason deferred: broad historical and compliance cards previously exceeded
  acceptable response times.
- Relevant areas: reporting materialized views, Metabase bootstrap SQL, and
  activity/patch aggregations.
- Trigger: a removed or deferred card is prioritized for restoration.
- First verification: time candidate SQL against representative live data
  before changing dashboard definitions.

## Ingest domain separation

- Reason deferred: scheduling and startup orchestration remain shared even
  though domain packages exist.
- Relevant paths: `ingest/main.py`, domain entrypoints, shared scheduler and
  bootstrap plumbing.
- Constraint: do not break current schedules, manual-run endpoints, migrations,
  or shared-client reuse.
- Trigger: an approved runtime isolation or independent deployment requirement.

## Legacy agent-compliance cutover

- Reason deferred: native Operations paths are substantially implemented, but
  legacy consumers and destructive retirement require audit.
- Relevant areas: `ingest/agent_compliance/`, scheduler/manual endpoints,
  legacy schema, Metabase consumers, configuration, and migration history.
- Constraints: backup, consumer audit, verified parity, and explicit
  destructive approval.
- Trigger: P7 cutover approval.

## Legacy Ninja snapshot archival, deletion, and disk reclamation

- Reason deferred: the generic ingest cutover must first prove that current,
  change-history, compatibility, and daily-rollup consumers are correct. Disk
  reclamation is operational cleanup, not part of the generic deployment.
- Relevant objects: `ninja_core.device_snapshots`,
  `ninja_core.device_health_snapshots`, their indexes and compatibility views,
  and the storage volume that contains them.
- Preconditions: both Ninja endpoint namespaces are authoritative through the
  generic contract; every named current/session/health/troubleshooting/trend
  consumer is verified; retention/archive policy is approved from aggregate
  30/90/365-day sizing; backup and restore rehearsal pass.
- Constraints: do not touch Agent Compliance; do not bundle historical
  deletion, archive, table truncation, partition removal, vacuum/repack, or
  filesystem reclamation into the generic deployment.
- Trigger: explicit post-cutover operational approval with an exact retained,
  archived, and deleted row/time range plus rollback and disk-reclamation plan.

## Source-confirmed device decommissioning workflow

- Reason deferred: the confirmed Ninja deletion-event design and its generic
  ingest implementation are deliberately parked so the approved historical
  evidence restoration and daily-rollup track can finish unchanged. Canonical
  retirement remains an operator-owned decision, and the end-to-end
  decommissioning workflow is outside that track.
- Relevant areas: generic source-event evidence, source-record withdrawal,
  the Ninja activities connector and backfill, Operations findings,
  `operations.audit_log`, entity detail/admin surfaces, and future
  decommissioning approvals.
- Required behavior: an exact source deletion event may automatically confirm
  the source-removal step, retain the source actor identifier and protected
  display metadata, and open or refresh an idempotent finding when deletion is
  unexpected or other workflow requirements remain. It must not delete or
  retire the canonical entity by itself. The source actor and the Operations
  decision actor remain separately attributable. Correct Ninja filtering to
  use `status=NODE_DELETED`, retain/backfill events idempotently, and use exact
  stable-identity matching. The 2026-08-03 read-only measurement found 51 of
  260 historical restoration identities with exact deletion evidence; the
  active restoration intentionally continues to use `missing_since` for all
  260 until this deferred work is approved.
- Trigger: explicit approval to implement generic source-event ingestion, or
  to design the full cross-source decommissioning workflow.

## Honour `source_bindings.schedule` (replaces cadence-by-capability)

- Reason deferred: `operations.source_bindings.schedule` exists and is
  populated (empty string today) but **nothing reads it** — every source is
  collected on one shared cycle. Adding Hudu made this bite: it is ~122
  paginated requests, changes daily at most, and `load_sources()` orders by
  `s.name`, so `Hudu` precedes every agent source and would delay them on
  each 4-hour cycle.
- **Interim measure now in place (must be reverted by this work):**
  collection cadence is partitioned by source *capability* rather than by the
  per-binding schedule —
  `ingest/source_observations.py::is_identity_source`,
  `ingest/main.py::run_agent_observations_once` (filtered to identity
  sources), `ingest/main.py::run_documentation_observations_once`, the
  `documentation_observations_cycle` scheduler job, and
  `DOCUMENTATION_SCHEDULE_HOURS` in `ingest/config.py`.
- Revert path: delete the documentation job and both source filters. Or,
  without a code change, set `DOCUMENTATION_SCHEDULE_HOURS` equal to
  `AGENT_COMPLIANCE_SCHEDULE_HOURS` to restore a single effective cadence.
- Why it is only interim: capability is a poor proxy for cadence. Two
  documentation sources may warrant different intervals, and a per-source
  schedule is already modeled in the database — this hardcodes in Python
  what the schema was designed to express.
- Constraints: must not change existing agent-source cadence without
  approval; per-binding schedules need a defined format (cron vs interval)
  and a sane default for the four existing bindings.
- Trigger: a third collection cadence being needed, or any source requiring
  a schedule that differs from others of its capability.

## `device_session_current` counts CMDB syncs in `last_observed_at`

- Corrected measurement 2026-07-30: **31 devices**, of which 9 would become
  null (known only to Hudu). An earlier note in this file said 856 — that was
  measured with `COALESCE(last_contact_at, last_observed_at)`, which is the
  *lifecycle* formula (already fixed in `_sync_lifecycle_status`), not what
  this matview uses.
- `last_contact_at` is **not** affected: CMDB rows set no `last_seen_at`, so
  it is null for them and `max()` already ignores it. Verified: 0 devices
  change.
- No application code reads `last_observed_at` from this matview. The only
  consumer (`views.py:2304`) reads `online_sources`, which is unaffected —
  CMDB rows never set `reported_online`.
- Deliberately not fixed: recreating a matview with 3 indexes and 4 grants in
  production to correct 31 rows of an unread column is not worth the
  deployment risk. A migration was written, validated, and discarded on that
  basis.
- Fix when touched: add `LEFT JOIN operations.entity_types` and filter the two
  contact aggregates on `is_identity_signal`. Leave
  `device_agent_presence_current` unfiltered — it answers "which sources hold
  records on which devices", which `source_health_current.device_count` needs.
- Trigger: any consumer starting to read `last_observed_at` from this matview,
  a Metabase question depending on it, or the next migration in this area.

## Admin Jobs catalog — scheduled work with no operator surface

- Principle: an operator should be able to see and run every scheduled job.
  Several run on a schedule with no entry in `_JOB_CATALOG`
  (`operations/apps/core/views.py`), so they can neither be observed nor
  triggered from the Jobs page.
- Missing entries: `activities` (only runnable as part of the whole Ninja
  source cycle), `platform_health_findings`, `run_log_stale_reaper`,
  `observation_history_retention_cycle`, CMDB findings
  (`_run_cmdb_findings`), and documentation/Hudu observations.
- Two of these need an ingest HTTP endpoint before a catalog entry is
  possible — there is no `/run/activities` and no `/run/platform-findings`.
  The catalog rows themselves are cheap.
- Note: `platform_health_findings` was added in 0.110.0 without a catalog
  entry — the same "built but invisible" pattern this item exists to close.
- Trigger: next Jobs-page or ingest-endpoint work; or sooner if an operator
  needs to run activities without a full Ninja cycle.

## Findings: one row per condition with a recurrence counter

- Today a resolved finding cannot be reopened: `uq_findings_active_condition_key`
  is partial on `status IN ('open','acknowledged')`, so a recurring condition
  inserts a new row instead of matching. The reopen branch inside `_upsert`
  (`status = CASE WHEN findings.status = 'resolved' THEN 'open' ...`) is
  unreachable dead code.
- Scale: 256,382 rows for 159,594 conditions. Concentrated in
  `stale_required_platform` — 98,515 rows for 1,828 conditions (avg 53.9
  episodes, max 96), 38% of the table. Every other type is 1.0-1.1x.
- Verified: no condition_key has more than one OPEN row, so the
  no-duplicate-open rule is enforced. The growth is resolved-episode history.
- Agreed direction: `recurrence_count` + `last_resolved_at`, unique index
  dropped to `(tenant_id, condition_key) WHERE condition_key > ''` so the
  reopen path becomes reachable, and a collapse migration (1,792 keys,
  96,788 rows removed, 256,382 -> 159,594).
- Payoff beyond storage: `recurrence_count` makes flapping actionable data —
  a notification rule can gate on it, and an operator sees "recurred 96
  times" rather than one indistinguishable instance.
- PREREQUISITE: audit every writer of `operations.findings` before touching
  the index. Known sites — `cmdb_findings._upsert`,
  `evaluator._upsert_finding`, `identity/resolver.py` raw INSERT
  (`unmatched_source_group`), `identity/client_resolver.py:406`, and
  `platform_findings` (inherits from cmdb_findings). A missed `ON CONFLICT`
  predicate starts raising on every run.
- Open decision: is `recurrence_count` sufficient, or is per-episode history
  needed (separate `finding_occurrences` table)? Zero operator state exists
  on any finding today (0 acknowledged / owned / reviewed / snoozed), so the
  collapse destroys nothing a human did.
- Related, separate: `whitelist_suggestion` holds 131,073 OPEN findings — a
  bulk report on the findings surface rather than an actionable queue.
- Trigger: explicit approval; the collapse is destructive.

## `merge_candidates`: producer wired; reconcile the two surfaces next

Fixed in 0.113.0 and 0.114.0. The queue had a fully built review surface and
no producer: 0 rows, nothing writing it, and a badge filtering
`status="pending"` which is not a member of `MergeCandidate.Status`.

- 0.113.0 fixed the badge filter.
- 0.114.0 wires the producer. `resolver._maybe_create_candidate` now writes
  the proposal alongside the `identity_conflict` finding it already emitted,
  carrying member snapshots, match reason and confidence. Migration 0125 adds
  a partial unique index on `(tenant_id, canonical_key) WHERE status = 'open'`
  so repeat detections refresh one row instead of piling up.
- Production is a reconciling pass (`project_merge_candidates`) over current
  device collisions, run each resolver cycle. Hooking it to observation
  resolution — the first attempt — would have produced nothing: production has
  zero unresolved identity observations against nineteen open
  `identity_conflict` findings. Measured: 38 proposals across 8 clients,
  idempotent on a second pass, members 4-6 devices per collision.

**Done in 0.114.1:** findings link to the queue filtered to their own
collision, the queue page renders against the 38 real rows, and its CSV export
no longer claims three fields the model does not have.

**Remaining:** resolving one surface does not yet close the other. An operator
who merges from the queue leaves the `identity_conflict` finding open until
the next resolver pass re-evaluates it, and acknowledging the finding does not
touch the proposal. Decide whether the finding should auto-resolve on merge or
whether both should simply reconcile on the next cycle — the latter is already
true for the candidate, which closes when its collision stops holding.

`client_user_links` is covered separately below — it is not compatibility debt.

## Users capability: designed, ingested, never built

- `operations.client_users` and `operations.client_user_links` hold **0 rows**
  and have no producer. They are the canonical person entity and its
  source-identity attachment — the same shape as the device and client link
  tables, for people.
- **The input data is already flowing.** 4,522 device rows carry a
  last-logged-in user, across 3,405 distinct users, available through
  `ninja_device_detail_current_shadow.last_user`.
- Meanwhile the user-risk page derives its users ad hoc from that raw field
  rather than from the canonical entity, so there is no stable person identity
  to attach anything to — no cross-source correlation, no lifecycle, no
  findings.
- Memory records Users as an intentional nav stub in the client context, so
  this is unbuilt rather than abandoned. Under the fix-don't-remove rule the
  tables stay; the work is the producer.
- Not an E6 item: this is a feature whose storage landed before its engine,
  not compatibility debt. Sizeable — canonical identity for people needs the
  same care as devices (what makes two logins the same person across sources)
  and should not be improvised.

## `whitelist_suggestion` volume — RESOLVED by ADR-0015 step 3

- The original entry recorded 131,073 open `whitelist_suggestion` findings
  measured 2026-08-06, roughly half of every finding in the system, and
  concluded the granularity was wrong: it should be per title with a device
  count rather than per (device, title).
- That is exactly what ADR-0015 step 3 did. Measured 2026-08-11 against
  production: **1,491 open, at `subject_type = 'software_product'`.** The
  diagnosis was right and the fix is deployed; keeping the old figure would
  send someone to re-solve it.
- Retained only as the pointer that the ~273 ms distinct-title tile cost on
  the software dashboard was a symptom of this volume and should be re-timed
  before any further index work on migration 0126's expression index.
- Still open, and genuinely undecided: `whitelist_suggestion` (>=10 devices)
  and `rare_recent` (<=2 devices) are the same question at opposite prevalence
  ends, and may belong as one finding with a prevalence attribute. `rare_recent`
  remains device-scoped by design (recency is a per-device fact), so this is a
  finding-model question, not a re-subjecting one.

## Source-to-entity-type mapping is data for Ninja and code everywhere else

The authoritative taxonomy already exists: `entity_classes` (8) ->
`entity_types` (11), each type carrying its class and capability flags. What is
missing is the **path from a source record to a type**, per source.

Ninja has it as data: `node_class_mappings` maps pattern -> `entity_type` ->
`form_factor` with priority and first-match-wins, which is how one source
yields five types (`agent.rmm`, `vm.guest`, `vm.host`, `network.device`,
`monitor.target`). Migration 0119 moved it out of code.

**No other source has an equivalent.** Each declares a single
`sources.entity_type` and stops. Hudu is the worst case, measured against the
live API 2026-08-07: **12,451 assets across 21 layouts**, all mapped to one
`cmdb.asset` type.

| layout | count | arguably |
| --- | --- | --- |
| Computer Assets | 4,327 | device or asset |
| Auvik | 2,863 | network monitoring records |
| **People** | **2,571** | **user** |
| Servers | 1,434 | device |
| Printing | 299 | peripheral / device |
| Locations | 267 | a location entity (nav stub exists) |
| Applications | 124 | software |
| Network Devices / WAN | 107 / 107 | device |
| Special Role Devices | 98 | device |
| Mobile Devices | 73 | device |
| Client Summary | 48 | client attributes |
| Remote Access | 45 | relationship, not entity |
| Content Filtering / Wireless / File Share | 21 / 14 / 12 | mixed |
| Managed Certificate | 13 | its own class — ADR-0012's own example |
| Email Summary / Vendor Summary / Backup | 8 / 7 / 6 | mixed |
| Credit Card | 7 | **exclude, see below** |

We ingest 9,837 of the 12,451; the gap is People plus a few dozen.

### The work

A `layout -> entity_type` mapping table for Hudu in the same shape as
`node_class_mappings`, and the same treatment for any source whose records span
types. Then:

- The People exclusion stops being `_EXCLUDED_LAYOUTS = {"people"}` in
  `ingest/connectors/hudu.py:44` and becomes a mapping row an operator can see
  and change — the question is not "should we stop excluding People" but
  "which entity_type does the People layout map to", answer `user`.
- Asset identity stops being derived from one source's shape. The earlier rule
  recorded here — "linked -> device, unlinked -> asset" — was inferred by
  inspecting Hudu layouts, which is what `node_class_mappings` exists to
  prevent.
- ~~Layout must be stored on the observation.~~ **Wrong -- it already is.**
  `hudu.py:113` writes `hudu_layout` (and `hudu_layout_id`) into
  `canonical_extra` on all 9,837 rows. The earlier claim measured a key name
  (`asset_layout`) that was guessed rather than read. No re-pull is needed and
  the mapping is cheap.

### Measured 2026-08-07: the gap is Hudu alone, not every non-Ninja source

| platform | entity_types emitted |
| --- | --- |
| Ninja | `agent.rmm`, `vm.guest`, `vm.host`, `network.device`, `monitor.target` (+ `org`) |
| SentinelOne | `agent.edr` (+ `org`) |
| LogMeIn | `agent.remote_access` (+ `org`) |
| ScreenConnect | `agent.remote_access` (+ `org`) |
| Hudu | `cmdb.asset` (+ `org`) |

The three agent sources are genuinely single-type -- one agent product, one
record shape -- so a mapping table for them would hold exactly one row. The
heading above overstates the problem: **there is nothing to migrate for three
of the five.**

### Bulk promotion of the 4,843 asset candidates is NOT safe

Measured layout split of the unlinked CMDB records. Roughly 1,400 are
plausibly assets; the rest are other classes or not entities at all:

| layout | unlinked | actually |
| --- | --- | --- |
| Auvik | 2,863 | devices synced in from Auvik (confirmed by the user) |
| Servers / Computer Assets / Printing / WAN / Network Devices / Special Role / Mobile | ~1,414 | device or asset |
| Locations | 261 | a location, not an asset |
| Applications | 124 | software |
| Client Summary | 48 | client attributes, not an entity |
| Remote Access | 45 | a relationship, not an entity |
| Managed Certificate | 13 | its own class |
| Credit Card | 7 | exclude |

**Do not promote in bulk.** ~500 are unambiguously not assets, and the `asset`
class would become a catch-all for devices, locations, software and
certificates. The taxonomy question -- which classes/types these map to --
comes before promotion, and several target classes (`location`, certificate)
are not registered.

### `provenance` already answers the promotion question and nothing reads it

`hudu.py:118` computes `provenance` per record and stores it. Auvik is
**2,863/2,863 `second_hand`**. The module docstring already states the policy:
"Relayed vendors that Operations does not ingest directly stay second-hand:
recorded, never promoted to first-party evidence." It is recorded and never
enforced downstream.

Two traps measured 2026-08-07 before using it as a gate:

1. `_provenance` is **vendor-level and ignores `sync_type`**. Ninja emits
   *location* cards, which are `integrated=True` but not device cards, so
   **247 Locations records come out `first_party`**.
2. `_provenance([]) == "first_party"` (asserted in `test_hudu_cards.py:93`),
   so **920 records with no cards at all** are first-party by default.

A naive `provenance = 'first_party'` promotion gate therefore admits 1,167
records carrying no first-party device evidence.

**And mapping a Hudu layout to an identity-signal type is a promotion
decision, not a classification.** `_promote_unmatched_clusters` gates on
`identity_entity_types()`, which is exactly `entity_types WHERE
is_identity_signal`. Mapping Auvik to `network.device` would route 2,863
records with 1.3% serial coverage, 0% MAC and 0% OS into device promotion,
clustered on a `hostname` that is really the Hudu record *name* -- re-running
the incident the resolver comment memorialises ("4,991 Devices were minted
from Hudu doc.asset records before this was caught").

### Exclude Credit Card from ingest

The `Credit Card` layout (7 records) must be excluded, alongside whatever
replaces the People exclusion. Card data has no place in the observation store
and nothing consumes it.

## Entity instantiation — `asset` DONE; `software` resolved elsewhere; `user` starved

Measured 2026-08-12: eight classes registered, **three instantiated**.

| class | live entities | |
| --- | --- | --- |
| device | 5,375 | working |
| **asset** | **1,425** | **done 2026-08-10** |
| client | 76 | working |
| software / user / peripheral / service / unknown | 0 | see below |

**The generic anchor-creation gap is closed.** `promote_candidate` (`b53957b`,
2026-08-07) added the missing verb — creation had been hardcoded per class in
`resolver.py` and migration 0101 while attachment was already generic. Layout-
scoped promotion (`65cada0`, 2026-08-10) then created the 1,425 asset entities,
each carrying `created_reason = candidate.promote:<candidate-uuid>`.

**Three of the four "simultaneously blocked" items in the original entry are
resolved:**

- ADR-0015 step 3 shipped 2026-08-10 (`6c4ac9f`) — it did **not** need entity
  instantiation; software+version got its identity from the reference catalog
  instead. See the ADR-0015 section.
- ADR-0012 §5's hierarchy exists in `catalog.*` as global reference data, per
  the 2026-08-10 amendment. Not an entity-store item.
- ADR-0013's "give the unanchored CMDB records the asset class" is done for the
  seven device/asset layouts; the remainder are deliberately unpromoted.
- The Users capability remains genuinely blocked — see below and its own entry.

### Asset: 3,435 candidates remain `observed_only`, each for a recorded reason

Not a queue to work through. Measured by layout 2026-08-12: Auvik 2,863
(`second_hand` provenance — relayed vendor, never promoted to first-party),
Locations 267 (a location; class not registered), Applications 124 (software),
Client Summary 48 (client attributes, not an entity), Remote Access 45 (a
relationship, not an entity), Managed Certificate 13 (own class, not
registered), Credit Card 7 (should be excluded from ingest), and 68 across
Content Filtering / Wireless / File Share / Email / Vendor / Backup. Promoting
these would make `asset` a catch-all for devices, locations, software and
certificates.

### Software: not an entity-store problem at all

Resolved by ADR-0012's 2026-08-10 amendment — software is global reference
data, not an owned entity. `entity_classes.software` and
`entity_types.software` stay registered and stay empty by decision. Nothing to
build here.

### User: no usable identity signal without Hudu

Measured 2026-08-12 from Ninja: 4,528 devices carry a `last_user`, 3,315
distinct values, **0 containing `@` and 0 containing a domain backslash**.
`client_users` and `client_user_links` both hold 0 rows. A bare username with
no email, domain or display name cannot establish a person: there is no way to
tell whether the same string at two clients is one person or two. Hudu People
is the only source with real identity records and is excluded at ingest.
See the Users capability entry.

### Identity rules — determined by measurement, not preference

**asset** — settled by the data. Of 9,837 Hudu CMDB observations, **4,994
already carry a `device_id`** and 4,487 carry a serial. So a CMDB record is
documentation *about a device* when it resolves to one, and an asset in its own
right when it does not — which is exactly the 4,843 unlinked candidates.
Rule: linked -> attach to the device's entity; unlinked -> own asset entity.
Client-scoped.

**software** — **SUPERSEDED 2026-08-10: software is not an entity.** ADR-0012's
amendment places `publisher`, `product` and `software+version` as global
reference data beside `intel.cves`, not in `operations.entities`. The
observation below stands as history and its conclusion was right for the wrong
destination — software identity is derived, not learned, so it was never a
promotion — but the sizing and the "first real use of the relationship engine"
framing no longer apply.

The retracted framing, kept so it is not re-derived: 4,863 publishers, 20,876
products, 40,261 product+versions were sized at ~66,000 entities / ~27 MB, and
484,636 installations at ~320 MB, with the note that "all eight E4 relationship
tables hold 0 rows, so software installations would be that engine's first real
use." **They will not be.** ADR-0012's amendment states the installation
relationship already exists and needs no generic rebuild; measured 2026-08-12,
`software_installations_current` carries `software_version_id` on 490,732 of
490,732 rows plus `install_location` and `install_date`. The E4 tables stay
empty, and agent presence — not software — is the relationship engine's
intended first use per ADR-0013.

Original measurement, still valid: 0 software observations, 0 candidates, 0
source links, so `promote_candidate` (`b53957b`) does nothing for software.
Asset and software need different machinery; do not plan them as one track.

Base data is clean: 0 installs missing a name, 4 missing a publisher, 13,817
(2.9%) missing a version, and only **99** (name, version) pairs claimed by more
than one publisher.

**Publisher normalization is NOT solved**, contrary to what this entry said
before. `publisher_aliases` holds 56 enabled rows, all literal (`is_regex`
false), matched with **ILIKE** (`raw_pattern`, per migration 0088 line 102 --
not equality and not regex). Measured with the correct operator:

| | |
| --- | --- |
| publishers matched | **296 of 4,863** (6%) |
| installs covered | **407,494 of 484,636** (84%) |
| distinct canonical publishers | 43 |
| publisher entities after normalization | **4,608** (from 4,863) |

So aliases cover install *volume* (the big vendors) but collapse only 255
distinct publishers. Instantiating today mints ~4,608 publisher entities, most
unnormalized. Not a blocker, but budget for the tail.

Identity is (canonical publisher, product, version). **Unscoped** per the
glossary, so the installation relationship runs device -> software+version;
an unscoped entity must never reference a scoped one.

**user** — **two sources, and correlation is the whole problem.**

An earlier version of this entry said Ninja was the only source and that no
cross-source correlation was needed. That was wrong: it measured
`entity_observation_current`, which is the *output* of a deliberate exclusion.
`ingest/connectors/hudu.py:44` sets `_EXCLUDED_LAYOUTS = {"people"}`, so Hudu
People records are fetched every run and then dropped — "personal data, and
they deliver nothing until a Users surface exists", with the count reported in
the run summary so the exclusion stays visible.

So the real picture:

- **Hudu People** — proper identity records (name, email, company), currently
  excluded at ingest, client-scoped through the Hudu company.
- **Ninja `last_user`** — a bare username on a device. Of 4,528 values, zero
  contain `@` and zero contain a backslash, so it carries no domain and no
  email.

The identity rule is therefore a correlation rule: match a bare Ninja username
to a Hudu person within a client. That is the same cross-source shape as device
identity, and it is the hardest of the three classes — a wrong match conflates
two real people.

Prerequisite: **decide whether to stop excluding Hudu People.** The exclusion
was correct while no Users surface existed; instantiating the class is what
changes that. Personal data handling (retention, redaction, who may view it)
needs settling with it — `entity_attribute_definitions` already has a
sensitivity classification and an audited reveal path from E5.2, which is the
mechanism to use rather than a new one.

### Order — superseded by outcome

1. ~~**asset**~~ — **done** 2026-08-10, 1,425 entities.
2. ~~**software**~~ — **withdrawn.** It was ordered here to unblock ADR-0015
   step 3 and the CVE version work; both shipped on 2026-08-10 without it, and
   ADR-0012's amendment removed the requirement entirely.
3. **user** — the only one left, and blocked on input rather than order:
   without Hudu People there is no identity signal to instantiate from.

`peripheral` and `service` stay registered and empty; nothing feeds them.
`peripheral` does have one registered relationship type
(`peripheral_attached_to_device`, enabled), which is the only row in
`relationship_types` — a registered edge for a class with no entities.

## Software ecosystem — ADR-0015 steps 1-6 COMPLETE; one clause unimplemented

**All six ordered steps are deployed** as of 2026-08-11. Verified against
production 2026-08-12; the step list below is retained as the record of what
was done, not as pending work.

| step | landed |
| --- | --- |
| 1. Import the legacy decision corpus | `97936c4`, `4ed7687`, `23d071c` |
| 2. Split trust out of `categories` | `0533779`, migration 0127 |
| 3. Findings onto real subjects | `6c4ac9f` — 137,540 rows to 2,719 |
| 4. Bind `cve_match` to the version | `d2964d9`, migration 077 |
| 5. Resolve `software_catalog.eol_date` | endoflife corpus + managed rules, migrations 078/081/082/087/088 |
| 6. Schedule the classifier | `c853a6e`, 24h cadence, catch-up verified live |

**Superseded — "instantiate `publisher` and `product` entities" is no longer
the larger unscheduled piece.** ADR-0012's 2026-08-10 amendment places them,
and software+version, as global reference data beside `intel.cves` rather than
rows in `operations.entities`. They exist today in `catalog.*`: 4,650
publishers, 21,438 products, 40,795 versions, measured 2026-08-12. See the
retired unscoped-entities item above.

**The installation relationship is also complete**, contrary to the framing
this section previously carried. ADR-0012's amendment states it "already
exists" and needed only the title strings to gain an identity. Measured
2026-08-12: `software_installations_current` holds 490,732 rows with
`software_version_id` populated on **490,732 — zero unlinked** — and carries
`install_location` and `install_date` as relationship attributes. It does not
need rebuilding on the generic E4 relationship tables.

### Still open: ADR-0015 §2 vs the implementation on `install_path_suspicious`

ADR-0015 §2 assigns three subject kinds, and one was not implemented:

- ADR-0015 §2: "**Installation facts** — `install_path_suspicious`. The path
  belongs to the device-and-software pair, so the finding belongs to the
  **relationship**." It adds that this "becomes the platform's first finding on
  a relationship rather than an entity", and that whether a relationship
  subject needs more than `subject_type` is "an implementation question this
  record does not settle".
- `.work/plan.md` states the opposite: "`rare_recent` and
  `install_path_suspicious` stay on `subject_type='device'` — recency and
  install path are per-device facts."
- Measured 2026-08-12: `install_path_suspicious` is `subject_type='device'`,
  51 open. The plan's position was implemented; nothing records that an
  Accepted ADR was overruled.

Blocker to settle first: `operations.findings.subject_id` is a uuid, and
`software_installations_current` has **no id column** — it is keyed by device
plus title strings. A relationship subject therefore needs either a minted
installation id or a composite subject, which is exactly the implementation
question ADR-0015 left open. Decide the subject identity before emitting.

`rare_recent` is not part of this: recency is a per-device fact and ADR-0015
does not place it on the relationship.

### Still open: the prevalence question

`whitelist_suggestion` (>=10 devices) and `rare_recent` (<=2 devices) are the
same question at opposite prevalence ends, possibly one finding with a
prevalence attribute. Genuinely undecided. Recorded 2026-08-06 by a Claude
session; no user decision on record.

### Original step list, retained as the record

Ordered; each step depended on the one before. ADR-0015 applies ADR-0012 §5
and the glossary's identity test to the software domain.

1. **Import the legacy decision corpus.** 418 decisions in
   `inventory-scripts/SW Inventory/output/decisions_global.csv` — 303
   title-scope, 115 publisher-scope — against 3 in production. Measured: decides
   **814 of 1,867** open `whitelist_suggestion` (title, publisher) pairs, 44%,
   publisher decisions carrying 740 of them. Forward-compatible with §1, since
   title and publisher scopes map onto `product` and `publisher`. The corpus has
   two spellings for publisher approval — `Approve` and `Approve Publisher`,
   both `Type=publisher` — mapping to `approve_publisher`.
2. **Split trust out of `categories`.** Move the 5 `whitelist` and 7
   `trusted_publisher` entries into `software_decisions` as approvals; change
   suppression to test *decided* rather than *labeled*. Functional categories
   (`av`, `remote_access`, `rmm`) stay as the coverage mechanism.
3. **Move findings onto their real subjects.** Five types to software+version,
   `install_path_suspicious` to the installation relationship, the two
   `unauthorized_*` types unchanged. 137,534 rows collapse to 1,782. Existing
   rows closed and re-emitted: operator-visible, own approval.
4. **Populate `cve_match.version_range`** and match against the installed
   version. All 2,636 rows currently have it empty, so `vulnerable_software`
   flags patched devices identically to unpatched ones. Until then the finding
   must state on its face that it is product-level. See the ADR-0008 amendment.
5. **Resolve `software_catalog.eol_date`.** Populated on 0 of 52 rows while
   `eol_runtime` runs off 9 regex rules. Populate or drop.
6. **Schedule the classifier.** Run three times ever, last 2026-07-27, never
   scheduled. Must come last: scheduling before step 3 regenerates 134,861+
   rows and undoes 0.115.0's page-load work.

Larger, not scheduled: **instantiate `publisher` and `product` entities**. The
raw material exists — 4,789 publishers, 39,321 title+version pairs. Until then
`software_decisions`' title and publisher scopes are the hierarchy in flat
form, and `software_catalog` stands in for both levels.

Open, not decided: `whitelist_suggestion` (>=10 devices) and `rare_recent`
(<=2 devices) are the same question at opposite prevalence ends, possibly one
finding with a prevalence attribute.

## Continuous check that read models stay read-only

- Migration 0122 revoked `INSERT, UPDATE, DELETE, TRUNCATE` from the runtime
  roles on all 17 views and matviews in `operations`, and asserts none remain.
  That assertion covers the population at migration time only.
- The root cause is not fixed and cannot be: `ALTER DEFAULT PRIVILEGES` grants
  `operations_app=arwd` on everything `operations_migrate` creates, and
  PostgreSQL's default-privilege object type `r` does not distinguish views
  from tables. Tables must keep those privileges, so any new read model will
  keep inheriting them.
- The rule is currently enforced by documentation only
  (`operations/AGENTS.md`), which this repository has repeatedly shown is
  insufficient on its own.
- Options, cheapest first: a Postgres integration test asserting the invariant;
  a startup assertion alongside the existing privilege checks; or an event
  trigger on `CREATE VIEW` that revokes automatically. The event trigger is the
  only one that cannot be forgotten, and is also the most surprising — decide
  deliberately.

## Layer tables are write-only; `agent_instance_field_history` never populated

- Measured 2026-08-05. `operations.assets` (5,293), `os_instances` (5,275) and
  `agent_instances` (~12,800) are written every resolver cycle and read by
  **nothing** — no view, matview, Python query, template or Metabase card. The
  only references are the writes in `resolver.py` plus Django `related_name`
  declarations.
- Cause, not neglect: ADR-0005 built them to answer retroactive per-layer
  questions, and `v_device_current` was meant to expose them. **That view was
  never built**, so the tables filled and the consumer never arrived.
- `agent_instance_field_history` has **0 rows** despite ~12,800
  `agent_instances` rows and code that claims to maintain the audit trail. A
  silent no-op. This is the one concrete defect here — the others are
  unfinished work, this is a mechanism that does not work.
- The capability is served better elsewhere. Attribute claim history vs layer
  field history on the same fields: `os_name` 9,790 vs 3,881; `os_family`
  18,671 vs 15; and claim history additionally covers `device_role` (9,781),
  `node_class` (5,537) and `is_virtual_machine` (4,562), which the layer tables
  never tracked. Claim history also records the asserting source;
  `os_instance_field_history.change_reason` is the constant `'trigger.audit'`.
- **Do not drop these tables yet.** ADR-0013 permits it "once consumers move to
  the effective contract **or to `v_device_current`**" and that view does not
  exist, so the precondition is half-met. Time depth of the two histories has
  not been compared, only row counts. Dropping is destructive, needs a backup
  and its own approval, and the tables are cheap to leave in place.
- Correct sequence: build `v_device_current` (owed by both ADR-0005 and
  ADR-0013), then revisit.
- Not an E6 blocker: E6 needs populated anchors, single-writer cache columns
  with measured parity, and no breaking consumers. All three hold.

## Deviation from ADR-0013 in the E5.3 cutover

- ADR-0013's first consequence reads: "The device cache projector computes form
  factor once and writes `device_hardware.form_factor` and `devices.device_type`
  together, so the copy step in `resolver.py:1078+` is deleted rather than
  repointed."
- `7e57ba3` did the opposite: the copy step was **kept and reordered** to run
  after the projector. The data is correct and consistent (measured: 5,293 open
  assets, 0 out of sync with `device_type`), but this is deferred work, not
  completed work, and it was reported at the time as a simplification.
- Also outstanding from ADR-0013: rename `operations.assets` to
  `device_hardware`; narrow `asset_type` to hardware-descriptive values;
  promote peripherals/licenses to their own entity classes; give the 4,842
  unanchored CMDB records the `asset` class; migrate agent instances to
  relationships.
- Resolve together with the item above — if `v_device_current` lands and the
  typed tables retire, the copy step disappears rather than being rewritten.

## Unscoped (universal) entities — RETIRED, not deferred

**Do not implement this. ADR-0012's 2026-08-10 amendment retires this item by
name**, in its own consequences: "The `.work/backlog.md` item 'Unscoped
(universal) entities — nullable tenant, third scope_kind' is retired as
unnecessary rather than deferred: it existed to make software fit a store
software does not belong in."

The item proposed making `operations.entities.tenant_id` nullable, adding a
third `scope_kind`, and replacing the RLS policy, so that software, publisher,
product and CVE could be held as unscoped entities. Two amendments removed the
need:

1. **The referential mechanism was wrong.** §4 claimed a composite foreign key
   under `MATCH SIMPLE` stands down when the *referenced* row has a NULL
   tenant. PostgreSQL relaxes on a NULL *referencing* column instead. **29
   composite foreign keys** reference `operations.entities(tenant_id, id)`,
   including `entity_relationships`. A row `(NULL, id)` can never satisfy a
   lookup for `(1, id)`, so the migration would have produced entities nothing
   in the schema could reference — failing at the first relationship insert
   after deploy, not at migration time, because every DDL statement succeeds.
2. **The placement was wrong.** Software is not owned — a client owns a
   license, not the product. `publisher`, `product` and `software+version` are
   global reference data beside `intel.cves`, which ADR-0012 §7 already
   exempts from the entity model.

Consequently: no nullable `tenant_id`, no third `scope_kind`, no RLS policy
replacement, and the 29 composite foreign keys are untouched. Verified
2026-08-12: `operations.entities.tenant_id` is still `NOT NULL`, which is now
correct by decision rather than an outstanding gap.

Retained only so the proposal is not rediscovered and re-planned. A **license**
is a scoped asset and does belong in `operations.entities` under the `asset`
class; that is separate work and carries no unscoped-entity requirement.

## 33 devices carry a form factor with no supporting evidence

- Surfaced by the first live run of `device_cache_projector` (2026-08-05,
  commit `7e57ba3`), which reported `device_type_evidence_missing = 379`. That
  number was wrong: the counter demanded a selected `is_virtual_machine` claim
  and ignored the fact that a `vm.guest` / `vm.host` / `network.device`
  observation is *also* evidence of form factor. Measured split: **346 of the
  379 were evidenced by entity type** and only **33 genuinely unevidenced**.
  The counter is corrected to require the absence of both.
- Remaining real gap: 33 devices have a known `device_type` with neither an
  asset-nature observation nor a selected `is_virtual_machine` claim. Their
  values are retained rather than downgraded to `unknown`, because a mapping
  gap is not evidence of absence.
- Work: find why `is_virtual_machine` is unselected for these 33. Likely a
  claim-projection gap rather than missing source data — `device_type` was
  correct for all of them (zero projector changes on that column).
- Lesson worth keeping: the metric was invisible until the projector ran, and
  it was wrong in the direction of alarm. A counter that overstates a gap by
  10x trains operators to ignore it.

## Source disagreement is resolved silently (`conflict = false`)

- Measured 2026-08-05 on `os_name`. Of 21 devices where the cache and the
  effective value differ, five have **two sources asserting different strings**
  for the same attribute — e.g. ScreenConnect `Microsoft Windows 11 Pro` versus
  SentinelOne `Windows 11 Pro`. Authority picks one and
  `entity_attribute_effective_current.conflict` is set to **`false`** on every
  one of them; `selection_reason` records `source_authority`.
- The defect: `selection_reason` records *how* the winner was chosen, never
  *that there was anything to choose between*. A disagreement with a clean
  authority ordering is still a disagreement, and today it leaves no
  operator-visible trace. This is the "nothing hidden or silently ignored"
  rule, and the effective layer is currently violating it.
- These particular five are cosmetic (a `Microsoft ` prefix). The mechanism is
  not: the same code path resolves any attribute, including ones where the
  sources genuinely disagree about fact rather than formatting.
- Direction: set `conflict = true` whenever the selected value differs from any
  other active claim, independent of whether authority resolved it cleanly.
  Then decide separately whether a persistent conflict warrants a FindingType
  or only a surface on the existing conflicts view (168 rows today, so the
  volume of a corrected flag needs measuring before wiring alerts).
- Distinguish from the other 16 of the 21, which are **stale cache** — one
  source claims, the cache holds an older value no source asserts anymore
  (e.g. `Windows 11 Business` where SentinelOne now reports `Windows 11 Pro`).
  Those are fixed by the E5.3 projector and are not a conflict problem.
- Not an E5.3 blocker. The projector moves every value toward what sources
  actually claim.

## Remaining hardcoded domain mappings (ADR-0012 section 6)

- Status: deferred. The ratchet test
  `ingest/tests/test_no_hardcoded_domain_mappings.py` blocks *new* module-level
  domain mappings in `ingest/` and `operations/apps/`, so this backlog no
  longer grows on its own. That is what makes deferral safe.
- Baseline at 2026-08-05: 128 candidates — 20 marked MIGRATE, 48 EXEMPT, 58
  recorded as not individually reviewed. `_OS_FAMILY_PATTERNS` (done, c3dcd9d)
  and the node_class taxonomy (in progress) come off the MIGRATE list.
- Largest remaining item is `_BUILTIN_ALIASES` in `ingest/normalize.py`. It
  already has the right shape — a documented bootstrap fallback behind
  `load_platform_aliases()` reading `operations.platform_aliases` — so the work
  is auditing the built-in list against the table, not building a mechanism.
- Also outstanding: `_JUNK_SERIALS` / `_JUNK_MACS`, `VOLATILE_FIELDS`,
  `_EXCLUDED_LAYOUTS`, `_INTEGRATED_VENDORS`.
- Note on the 58 unreviewed entries: the ratchet certifies nothing about them.
  Reviewing that tail is its own task and should not be assumed done.
- Trigger: pick up when the MIGRATE list is otherwise clear, or when a
  specific mapping needs an operator to change it without a deploy.

## Root backlog rules

- Do not duplicate Operations-only items here.
- Do not retain completed milestone checklists.
- Move an item into `.work/plan.md` only when approved as active cross-service
  work.
