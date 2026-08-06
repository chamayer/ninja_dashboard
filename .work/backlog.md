# Root and cross-service deferred work

This is the proposed successor to the root-level open-work portion of
`TODO.md`. Operations-only items belong in `operations/.work/backlog.md`.

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
  schedule is already modelled in the database — this hardcodes in Python
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

## `whitelist_suggestion` fires 131,073 times

- Measured 2026-08-06 while profiling the software page: 131,073 open
  `whitelist_suggestion` findings, roughly half of every finding in the
  system, across 20,631 titles.
- A finding type at that volume is not an actionable queue, and it is what
  makes the software dashboard's distinct-title tile cost ~273 ms even with
  the expression index added in migration 0126 — PostgreSQL must read all
  131,073 entries because there is no index skip-scan for `DISTINCT`.
- Decide what the finding is for: if it is per (device, title) it should
  probably be per title with a device count, which is the pattern the
  recurrence-counter backlog item describes. That would cut it by roughly the
  average device-per-title factor and make the queue readable.
- Do not simply suppress it — per the fix-don't-remove rule, the detector is
  telling the truth; the granularity is wrong.

## Software ecosystem — work defined by ADR-0015

Ordered; each step depends on the one before. ADR-0015 applies ADR-0012 §5
(`publisher -> product -> software+version`, installation as a relationship)
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
   suppression to test *decided* rather than *labelled*. Functional categories
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
  promote peripherals/licences to their own entity classes; give the 4,842
  unanchored CMDB records the `asset` class; migrate agent instances to
  relationships.
- Resolve together with the item above — if `v_device_current` lands and the
  typed tables retire, the copy step disappears rather than being rewritten.

## Unscoped (universal) entities — nullable tenant, third scope_kind

- ADR-0012 section 4: ownership determines scope. Software, software+version,
  CVE and publisher are universal, not tenant property, so they should not
  carry a tenant. Today `operations.entities.tenant_id` is NOT NULL and
  `scope_kind` allows only `tenant` / `client`.
- **Not a blocker for E6.** Verified 2026-08-05: E6 concerns Client and Device
  anchors, both tenant-scoped, and both are already fully populated (0 NULL
  `entity_id` across 5,293 devices and 76 clients). This is parallel work.
- Measured state: `scope_kind` tenant 76 / client 5,293; PostgreSQL 16.14;
  `ck_entities_scope_owner` pairs scope_kind with client_id presence.
- **It is bigger than "make the column nullable".** Two findings from the
  2026-08-05 investigation:
  1. `tenant_id` is inherited from the `TenantScopedModel` abstract base shared
     by many models. `Entity` has to override the field; the column cannot
     simply be altered in isolation.
  2. `operations.entities` has **FORCE ROW LEVEL SECURITY**, and the
     `tenant_isolation` policy is `FOR ALL` with `tenant_id =
     current_setting('operations.tenant_id', true)::bigint` in **both** USING
     and WITH CHECK. A NULL tenant evaluates to NULL, so a global row would be
     invisible to every role including the table owner. The policy must be
     replaced in the same migration or the entities silently vanish — the exact
     failure class ADR-0012's "nothing hidden" rule exists to prevent.
- Shape that survived review: `USING (tenant_id IS NULL OR tenant_id =
  current_setting(...))`. Checked and clean: the unique indexes
  `(tenant_id, id)` and `(tenant_id, id, entity_class_id)` stay sound with a
  NULL tenant because `id` is already the primary key, so no
  `NULLS NOT DISTINCT` is required. Nullable `tenant_id` is also consistent
  with the MATCH SIMPLE composite-FK decision already taken.
- Open decision: the WITH CHECK half. Either any tenant's ingest may create a
  global entity (simplest, and software/CVE ingest is already tenant-agnostic,
  but one tenant then defines a universal record) or a dedicated role may,
  which does not exist yet. Default leaning is the former.
- Trigger: explicit approval. This is an RLS change on a forced-RLS table and
  deserves its own commit and its own deploy, separate from anything else in
  flight.

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
