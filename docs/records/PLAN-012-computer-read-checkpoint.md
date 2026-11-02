# PLAN-012 — Computer reads and inventory checkpoint

This record holds the PLAN-012 checkpoint. The original consumer ledger and
slices were lost on 2026-10-26; the ledger below was reconstructed from
current source on 2026-11-02 and replaces it.

## Active checkpoint — 2026-11-02

**Status:** Stage 1 committed locally (not released). Item 4 migration 0400
drafted, uncommitted. Approved 2026-11-02: 0400 rehearsal on a production
schema clone and Stage 2 read-only measurements.
**Decision (2026-11-02, owner delegated):** A read model/projection is not a
goal in itself. Stage 2 production measurements decide among an ordering
index, a read model, or neither; any migration needs its own approval. This
supersedes the earlier "design the read model" resume gate.
**Changed files:** `operations/apps/core/device_status.py`,
`operations/apps/core/views.py`, `operations/templates/device_detail.html`,
`ingest/computer_listing.py`, `ingest/evaluator.py`, tests
`operations/apps/core/tests/test_plan012_computer_reads.py`,
`operations/apps/core/tests/test_coverage.py` (fixture column),
`ingest/tests/test_computer_listing_window.py`, and
`docs/reference/source-contact-semantics.md`.
**Validation (local):** Operations non-Postgres suite 577 passed, 8 failed —
the same 8 fail at HEAD `4c9fcc15`. Ingest non-Postgres suite 644 passed,
7 failed — the same 7 fail at HEAD. `manage.py check` clean; changed templates
load; Ruff error count for `views.py` unchanged (97, pre-existing). Tests ran
in a scratch virtualenv with `shared` on `PYTHONPATH` (no pytest in the dev
containers). Postgres-backed tests, browser checks and live data were not run.
**Next action:** run the approved 0400 rehearsal and Stage 2 measurements.

### Completion gate status

1. **Done locally.** One effective offline rule: `device_status.py`
   (`get_client_device_status_policy`, `recent_contact_sql`,
   `stale_contact_sql`) applies `clients.offline_after_days`, falling back to
   the tenant `active_device_days`, on Home, Computers (tiles, filter, row
   label), Coverage, Patching, the client hub and client devices — matching
   ingest. The `computer_listing` "reporting" window now uses the tenant
   `retire_review_days` (default 30, so default behavior is unchanged).
2. **Done locally.** Computer-page requirement rows and the client
   `?missing=` drill-down read `device_requirement_state`. The client hub's
   `platform_coverage` (three queries, its own rule copy, unrendered since
   the 2026-07-22 workspace overview) was removed. Remaining
   `coverage_requirements` reads are configuration (exemption choices).
3. **Done.** `docs/reference/source-contact-semantics.md`.
4. **Design chosen 2026-11-02 (owner approved "A"); migration drafted, not
   applied.** See "Item 4 design" below.
5. **Closed 2026-11-02.** `assets` and `agent_instances` have no reader in
   Operations Python, templates, SQL views or repo bootstrap; the identity
   resolver is their only writer. Metabase was retired by PLAN-008 (runtime
   removed, `metabase_ro` dropped by `0359` in 0.130.0), so no Metabase
   reader remains. OS installations have named readers (Computer page,
   Issue review). Retirement of the two tables is proposed in `TODO.md`,
   not approved.
6. **Stage 2.** Re-measure Source Records and Computers in production.
7. **Done locally.** Demonstrated from the view definition:
   `v_cmdb_inventory_evidence_current` has one row per relayed card, so
   `_device_source_records` listed a multi-card Hudu asset once per card on
   the Computer page and merge review. It now reads one row per record. The
   Computer-page Hudu panel and Coverage already grouped by record.
   Production count of multi-card assets is a Stage 2 check.

### Item 4 design — association change refreshes Computer values

**Problem (from code).** Claims are keyed by record
(`uq_attr_claim_current_member`: tenant, observation, definition, member) but
carry a copy of the record's Computer (`entity_id`), refreshed only when the
claim projector runs in `refresh_after_collection`. Since 0374 the real
association changes immediately in `set_source_association`. A new
Computer is created with placeholders (`os_group = 'Unknown'`,
`device_role = 'unknown'`); the resolver's cache projection cannot fill them
because the Computer has no effective values yet, so platform evaluation
opens an `os_unknown_coverage` finding and applies the wrong requirement tier
until the next cycle. Operator merge, split and move have the same lag.
Record-level findings (ADR-0050 row 1) are unaffected.

**Decision.** The association procedure refreshes the values it changed, in
the same transaction, reusing the existing projectors (one copy of each rule):
1. `sync_entity_attribute_claims_from_observations(batch_size, uuid[])` and
   `sync_entity_attribute_effective(batch_size, uuid[])`: scoped variants of
   the current bodies (0397 and 0108 text plus one filter). The existing
   one-argument functions become wrappers, so ingest callers and grants are
   unchanged. The claim step already queues both the old and the new
   Computer (`effective_groups_to_queue`).
2. `device_cache_targets(tenant, uuid[])` and `project_device_cache(tenant,
   uuid[])`: the `device_cache_projector` target SQL moved into the database;
   the Python projector calls them (legacy inline SQL only until the
   migration is present).
3. `refresh_association_values(tenant, subject, entity[])`: scoped claims for
   the record and its companions → effective values for the old and new
   entity → cache columns for their Computers.
4. `set_source_association` calls it after a real change (no-op calls skip
   it).

**Concurrency.** Both projectors take a try-advisory-lock. If the periodic
projector holds it, the refresh returns `deferred` and the next collection
fixes the values as today; it never blocks or aborts the association
(waiting could deadlock with a periodic batch on `projection_state`).
Deferrals raise a database warning. **Decided 2026-11-02 (owner delegated):**
no operator-visible record. A deferral happens only while a collection refresh
holds the projector lock; that refresh loops claims and effective values until
empty and the resolver then projects every Computer, so the running chain
completes the deferred work.

**Cost.** Proportional to association changes (one record, two entities, two
Computers per call), not fleet size. To measure on the dev database at
smallest scope before proposing release; bulk resolver runs call it once per
moved record.

**Draft (uncommitted):**
`operations/apps/core/migrations/0400_association_refreshes_computer_values.py`
(functions only), `ingest/device_cache_projector.py` (uses the database
function when present), corrected comments in `ingest/identity/resolver.py`
and `ingest/derived.py`, tests `operations/apps/core/tests/test_migration_0400.py`.
**Validated 2026-11-02:** forward and reverse SQL applied and rolled back on
the dev database (at 0391); `device_cache_targets` matched the Python target
on all 4,960 dev Computers (0 differences); Operations suite 584 passed and
ingest 644 passed, failures identical to HEAD.
**Not yet validated:** a real association change calling the refresh, its
per-call cost, and function ownership on production. The owner ruled out the
local dev stack (2026-11-02).
**Release gates.** Rehearsal on a schema-only clone of production on the host,
as PLAN-038 did for 0397 (needs approval): move, no-change, busy-deferral and
reverse checks as `operations_migrate`/`ninja_ingest`, per-call timing, and a
read-only EXPLAIN of the scoped claim scan on real data; then release with
explicit migration approval.

### Consumer ledger (reconstructed 2026-11-02, `views.py`)

Population readers using the shared current-Computer selector
(`current_computers` / `current_computer_sql` or an explicit retired
exclusion): `home`, `devices_page`, `org_index`, `org_devices`,
`inventory_clients`, `patching_queue`, `search`, `admin_data`,
`_installation_filters` (and `_installation_csv` through it), Coverage
(`fleet_coverage`), and `patch_evidence_page` OS choices (fixed 2026-11-02).
Explicit exceptions — single-Computer or workflow lookups that must still
reach retired Computers: `device_detail`, `device_merge`,
`merge_candidate_group_review`, `finding_review`, `findings_queue`,
`_entity_issue_rows`, `targeted_refresh`, `_automatic_promotions`,
`device_lifecycle_set`, `_retire_selected_computers`.

## Goal and boundaries

Reconcile every platform inventory consumer's Computer, Device, Entity, and
source-record counts and destinations. Reuse `operations.v_device` for current
Computer membership. Keep Computer, source-record, and display-row units
distinct; the count, filtered destination, and CSV must agree. Keep search and
history exceptions explicit. Do not add a projection or migration without
measurements that justify it. PLAN-014 owns requirement applicability, finding
cover, and stored verdict writing; preserve PLAN-013 authentication behavior.

## Confirmed decisions and evidence

- The shared current-Computer selector is the membership boundary. Domain
  readers may apply narrower eligibility filters, but unlinked source evidence
  and presentation rows do not become Computers.
- Source Records use observation/record grain, including unlinked records.
  Computer attachment, client attribution, and parent association remain
  separate facts.
- Inventory evidence should be bounded by the Computer population that can
  render. Keep source and Hudu evidence separate from canonical Computer
  totals.
- Consumer coverage spans Dashboard, Clients, Computer overview, inventory,
  Patching, software readers and drill-throughs, Sources, Source Records,
  entity/admin counts, and search/history exceptions. Patching and software
  remain domain-specific subsets. Counts and destinations retain their stated
  grain rather than being forced to match across unlike populations.
- The 2026-10-23 read-only measurement found 5,506 current Computers and
  37,094 current observations. The Source Records count took about 959 ms; its
  unfiltered first page took about 4.9 s because tenant/last-seen ordering was
  unsupported by an index. The Computer count took about 67 ms. This supports
  investigating the ordered read path, not adding a projection. These are
  dated measurements, not current production state.
- The 2026-10-21 baseline (from the earlier compact checkpoint, commit
  `b636df92`): deployed 0.128.15 measured a 4.740-second Computers browser
  first response, of which 3.154 seconds was database wait across 15 fleet
  reads and 1.209 seconds template rendering, before `cc5d936` stored
  evaluator requirement verdicts (ADR-0035, migration 0332). After the first
  verdict pass (2026-10-21 17:48 UTC), 19,012 verdicts were present and Hudu
  Missing on the page fell from 4,208 to 260. A drift check found 582 open
  findings with no matching verdict, explained by PLAN-014's separate resolver
  rule copy. `453c41c` and `ccae6da` were requested page fixes, not
  read-model progress. Each prerequisite run had only the eight failures also
  present on `3091a47`. These are dated measurements, not current state.
- An index draft was withdrawn; migration number 0343 is occupied. Any index
  requires a newly reviewed migration and separate approval.

## Recorded implementation checkpoint

The 2026-10-23 root checkpoint recorded Slices 0–5 as implemented locally:
Slice 0 established a consumer ledger; Slice 1 migrated Dashboard, Computer
overview, and Admin Data; Slice 2 covered Clients; Slice 3 covered Computers
inventory and Source Records; Slice 4 covered Patching/software populations
and destinations; Slice 5 covered source/entity/search surfaces. The
checkpoint also recorded current-Computer scoping for software summaries,
complete pagination, distinct source/entity grains, and card semantics. Slice 6
measured full-fleet serving cost and left optimization conditional on evidence.
Some work was committed locally and some remained uncommitted at that
checkpoint. Reconcile current files and Git before treating any slice as
complete now.

Acceptance requires one canonical Computer counted once; unlinked evidence
never presented as a Computer; count, filter, destination, and complete CSV
membership agreement before pagination; and explicit exceptions for historical
search. Preserve stored-verdict authority, Hudu/current/withdrawn distinctions,
tenant access boundaries, and rebuildability/freshness reporting for any future
projection. The old 500-row destination caps were specifically in scope.

Validation recorded at that time included focused reader/coverage checks,
`manage.py check`, Python compilation, registry validation, Ruff checks, and
scoped whitespace checks. Data-backed membership comparisons were not locally
available; Django/pytest and database configuration limitations were recorded
for the relevant workstation environment. Production read results above were
aggregate-only and made no data changes.

## Completion gate

PLAN-012 remains incomplete until each item is fixed or closed with evidence:

1. Define one effective operational-status reader for online state, contact,
   lifecycle, and client `offline_after_days`; reconcile the 30-day
   `computer_listing` window.
2. Migrate requirement readers to `device_requirement_state`; PLAN-014 owns
   applicability and verdict policy.
3. Record per-source contact semantics and label presence versus lifecycle
   evidence.
4. Reconcile effective-attribute promotion, failure/retry behavior, and the
   unverified one-cycle lag.
5. Audit SQL-view and Metabase readers of `assets`, `agent_instances`, and
   `os_installations`; retain with named readers or propose approved retirement.
6. Re-measure Source Records and relevant Computer/inventory paths; decide on
   ordering index, bloat, and heartbeat-writer work from evidence.
7. Verify whether multi-card Hudu evidence duplicates Computer-page source
   rows; correct only if demonstrated.

Production reads, schema changes, migrations, writes, deployments, commits,
and pushes retain their separate authorization gates. See the PLAN-012 section
in the root blueprint and `docs/records/PLAN_REGISTRY.md` for the current
resume gate and owner routing.
