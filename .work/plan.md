# Active root work plan

Track: **Unified entity ecosystem — database, ingest, and admin surface**

**Status: `0.102.0` INVENTORY METABASE RETIREMENT DEPLOYED AND VERIFIED;
GENERIC NINJA CUTOVER AND NATIVE AVAILABILITY IMPLEMENTATION IN PROGRESS.
Releases `0.101.4`/`0.101.5` and migration `0099` are deployed. The exact
162-row pinned correction is applied, its repeated invocation is a verified
no-op, and canonical devices, links, raw evidence, and daily rollups are
preserved. The approved presence/session refresh completed with the measured
325-to-283 presence-row reduction, seven devices with no remaining active
presence, exact affected-session parity, and no lifecycle transition or audit
event. Deployed release `0.102.0` archives only the Inventory Metabase surface
and removes its three normal refresh triggers. On 2026-08-03 the user
subsequently authorized the bounded implementation slice recorded below.**

Revised 2026-08-03.

## Goal

Build one source-agnostic ecosystem with this shape:

```text
Tenant (MSP)
  └── Client
        └── Entity (device, user, peripheral, certificate, service, ...)
              ├── typed canonical attributes
              ├── related entities
              └── source evidence from one or more source instances
```

Every record learned from a source is retained as source evidence. It is not
automatically a canonical entity. Sources may independently corroborate the
same entity, disagree about its attributes, or make second-hand claims. Weak
or second-hand evidence remains visible but cannot create, merge, or silently
change a canonical entity unless an explicit policy grants that authority.

Adding a source means implementing its connector and declaring how its data
maps into the common contract. It must not require edits to shared identity,
reconciliation, lifecycle, relationship, health, or UI-registration logic.

## Definitions

- **Source record:** what one source says exists, in that source's namespace.
- **Claim:** one normalized attribute or relationship asserted by a source
  record, with provenance and authority.
- **Canonical entity:** the durable Operations record accepted as representing
  a real client, device, user, peripheral, or other managed concept.
- **Effective value:** the value selected from source claims and operator
  decisions for use by Operations. Selecting it never discards competing
  claims.
- **Peripheral:** a canonical entity in its own right, linked to a parent by a
  typed relationship. It may be rendered like parent detail, but is not stored
  as a parent attribute.
- **Source instance:** one tenant/client connection to an external system.
- **Source binding:** the collector transport currently used to collect a
  source instance. It is provenance, not identity.

## Non-negotiable invariants

1. Tenant scope is present and enforced on every tenant-owned row and foreign
   key. Client-scoped entities have one enforceable client owner; explicitly
   MSP-scoped entities may have none.
2. Nothing an operator can change in a source is part of source-record
   identity. The stable identity tuple is:
   `(tenant_id, source_instance_id, external_namespace,
   parent_external_namespace, parent_external_id, external_id)`.
3. `source_binding_id`, `native_record_type`, Operations `entity_type`, and
   canonical class are mutable metadata, never identity components.
4. Canonical entities survive source disappearance. Reconciliation withdraws
   evidence; it does not delete canonical entities or operator decisions.
5. Raw evidence, normalized claims, effective values, and operator decisions
   are separate layers. No refresh may collapse or overwrite those layers.
6. Identity authority, canonical-creation authority, attribute authority,
   relationship authority, lifecycle contact, license consumption, and
   coverage eligibility are independent policies. No flag proxies for another.
7. Unknown types, attributes, incomplete references, and ambiguous matches are
   retained and surfaced as findings. They are never guessed or discarded.
8. Existing `Device`, `Client`, and ADR-0005 `Asset` / `OSInstance` /
   `AgentInstance` semantics remain typed. The generic layer connects them; it
   does not flatten them into JSONB.
9. Existing `devices.id` and `clients.id` remain stable. Existing foreign keys
   are not repointed during expansion.
10. A new registered source appears on generic admin surfaces without a source
    name being added to Python, SQL, or templates.

## Scope

In scope:

- The database contract for entities, client ownership, observations, source
  links, claims, effective values, relationships, policies, history, and
  generic read models.
- The connector contract and shared ingest pipeline.
- Migration of Ninja, SentinelOne, ScreenConnect, LogMeIn, and Hudu onto that
  contract.
- Generic admin surfaces for source health, candidates, entities, evidence,
  conflicts, effective values, and relationships.
- Additive backfill, dual-write, comparison, cutover, rollback, RLS, audit,
  performance, and compatibility work.
- Correcting the deployed observation identity and the `vm.guest` lifecycle
  contact defect.
- Disconnecting the Inventory-domain Metabase bootstrap and refresh calls while
  preserving its legacy relations for rollback, and continuing generic
  Operations capabilities independently of that accepted retirement.

Out of scope:

- Installing arbitrary connector code through the UI.
- Runtime editing of deployment-controlled registries. They are visible but
  read-only until a separately audited editing workflow is approved.
- Write-back to source platforms.
- Hudu People or other newly introduced PII-bearing layouts.
- Retiring legacy compliance schemas, retiring other Metabase domains, or
  physically deleting Inventory's legacy reporting storage.
- Redesigning class-specific device matching, patching, software, or
  ADR-0005's layered device model.

## Design authorities

The accepted design authorities are:

- `docs/decisions/0005-operations-first-metabase-retirement.md` for the
  Operations destination, prohibition on Metabase investment, phased domain
  cutover, and bounded rollback contract.
- `operations/docs/decisions/0009-stable-source-observation-identity.md` for
  stable-namespace observation identity and concurrent snapshot
  reconciliation. ADR-0007 v5 remains the deployed authority until ADR-0009
  is implemented and cut over.
- `operations/docs/decisions/0010-unified-entity-source-ecosystem.md` for the
  completed database, authority, claim, effective-value, relationship,
  ingest-contract, and read-model design.
- `operations/docs/decisions/0011-lifecycle-evidence-and-immutable-audit.md`
  for Corrective Track A's evidence hierarchy, fail-closed policy, atomic
  audit, inert schema landing, and separate activation contract.

ADR-0010 does not block the isolated lifecycle correction or the ADR-0009
observation-identity correction. Those corrective tracks have their own
approval and validation boundaries below.

The accepted ADRs agree with this plan. If later review creates a conflict,
implementation stops until the documents are reconciled; the plan is not
permission to choose one silently.

## Track 1 — Database structure

The database is the durable contract used by both ingest and the admin UI.

### DB1. Registry governance and semantic registry

- Bring the raw-SQL `entity_types`, `platform_aliases`, and
  `sources.entity_type` objects into Django model state.
- Revoke application DML on deployment-controlled registries.
- Add `entity_classes`, typed relationship definitions, source defaults,
  instance overrides, and version/audit metadata.
- Give `entity_types` independent lifecycle-evidence mode, license,
  requirement-eligibility, and identity-signal capabilities.
- Keep classification separate from authority. Absence of an authority policy
  means denied.

### DB2. Correct observation identity and reconciliation

- Use accepted ADR-0009 as the authority before changing the deployed identity
  key.
- Add the stable namespace identity columns to observation current/history.
- Derive `source_instance_id` from the existing binding; retain the binding as
  nullable `last_seen_binding_id` provenance.
- Keep `native_record_type`, `entity_type`, and canonical class as material,
  historical attributes.
- Rebuild current/open-history uniqueness, advisory locks, upserts, history,
  retention, RLS, snapshot runs, seeds, and dependent views around the stable
  tuple.
- Advance each current row's run marker in place. Only complete runs may
  withdraw evidence; partial or failed runs withdraw nothing. Do not retain a
  separate member row per identity per poll.
- Serialize reconciliation by tenant, source instance, and snapshot scope.
- Preserve rows disputed by overlapping complete runs, raise a finding, and
  allow the next non-overlapping complete run to resolve it automatically.

Affected-surface inventory, verified against Git revision `65f05d5` on
2026-07-31:

| Surface | Verified location |
| --- | --- |
| Current unique constraint | `operations/apps/core/models.py:1024`, `uq_obs_current_identity` |
| Open-history unique constraint | `operations/apps/core/models.py:1064`, `uq_obs_hist_open_identity` |
| Identity tuple and advisory-lock key | `ingest/observations.py:93-115` |
| Locked prior read and upsert target | `ingest/observations.py:125-175`, `:255` |
| History close and open | `ingest/observations.py:290`, `:334` |
| Complete-run reconciliation | `ingest/observation_runs.py:41-77` |
| Snapshot-run model and namespace | `operations/apps/core/models.py:1069+` |
| Dependent matview/read migrations | `0068`, `0071`, `0076`, `0077` |
| Seed and history maintenance | `seed_observation_history.py`, migration `0074` |
| Observation RLS | migration `0066` |
| Writer and retention tests | `test_observations.py`, `test_retention_observations.py` |
| Architectural authority | deployed ADR-0007 plus accepted ADR-0009 |

This inventory is a verified starting point, not permission to trust stale
line numbers. Re-run repository-wide reference discovery at the start of DB2
and reconcile any additions or movement before editing.

### DB3. Canonical entity anchor and ownership

Implement ADR-0010 **Entity topology and client ownership** as one additive
slice. Gate: tenant/client scope constraints pass under RLS, existing typed IDs
are unchanged, and every backfilled typed row has exactly one valid anchor
before any new reference becomes required.

### DB4. Generic source links and observation attachment

Implement ADR-0010 **Source records and generic links**. Gate:
`entity_source_links` is the sole current attachment authority,
`entity_source_link_history` reproduces attachment-at-time, and every legacy
link is migrated or explicitly deferred before shadow comparison and read
cutover.

### DB5. Attribute claims, authority, and effective values

After the required scale measurement, implement ADR-0010 **Attribute claims
and effective values**. Gate: single/set semantics, deny-by-default authority,
operator decisions, conflict policy, sensitivity enforcement, per-value
provenance, and the single-writer typed projector all pass behavioral and
scale tests before any typed consumer cuts over.

### DB6. Relationships and peripherals

Implement ADR-0010 **Relationships and peripherals** plus its operator-decision
rules. Gate: class/cardinality enforcement, unresolved endpoints,
multi-source evidence, include/exclude precedence, and withdrawal behavior are
verified without deleting endpoints.

### DB7. Generic read models and materialized views

Implement ADR-0010 **Generic read models and admin behavior** and **Security
and materialized views**. Gate: generic source/type counts work without new
columns; typed device views retain their semantics; wrapper-only tenant access,
the fail-closed SQL tenant helper, visible sensitivity redaction, refresh
ordering, and concurrent-refresh indexes pass role and performance tests.

## Track 2 — Ingest design

### IN1. Connector and source-registration contract

Each connector supplies:

- Authentication, pagination, rate-limit, retry, and vendor parsing code.
- A source manifest describing configuration fields, secret references,
  supported namespaces, snapshot scopes, connector/schema versions, and the
  versioned material projection for each namespace.
- `SourceRecord` values in vendor terms: stable namespace/id, optional parent
  identity, mutable native type, raw payload, normalized identity evidence,
  attributes, relays, and relationships.
- A `FetchResult` declaring complete or partial snapshot status plus explicit
  skips and errors.
- Registry rows for classification, attribute definitions/mappings, authority,
  and relationship types. These declarations are the definition of making
  source data usable, not limitations on source extensibility.

### IN2. Generic source-evidence storage contract

- Keep exactly one current raw row per complete stable source identity and
  update its payload, source/collection timestamps, run provenance, and hashes
  on every successful collection.
- Compute a deterministic `raw_hash` over the complete payload and a versioned
  `material_hash` over deliberately selected meaningful state. Exclude
  heartbeat, polling, receipt-time, and other declared collection noise from
  the material projection.
- Store an initial material history version, then append only when material
  state changes or a complete snapshot withdraws evidence. Raw-only changes
  update current provenance without appending another full raw copy; partial
  or failed snapshots withdraw nothing.
- Store long-term reporting facts in compact, typed daily rollups without raw
  JSON. The rollup grain retains source namespace and reporting date.
- Finalize physical tables, indexes, retention, and partitioning only after the
  approved aggregate 30/90/365-day sizing measurement.
- Reuse the deployed Operations material-projection/hash pattern rather than
  creating a second change-detection mechanism.

### IN3. Shared processing pipeline

All sources use the same ordered stages:

1. Validate source context, schema version, and record contract.
2. Upsert current raw evidence by stable observation identity and calculate
   versioned raw/material hashes idempotently.
3. Classify native type; unknown maps to `unknown` plus a finding.
4. Normalize and persist attribute and relationship claims.
5. Reconcile only within the completed source-instance snapshot scope.
6. Resolve tenant/client scope without guessing.
7. Match an existing source link or run the entity-class resolver strategy.
8. Attach to an entity, create a review candidate, or leave observed-only.
9. Derive canonical relationships and effective values under policy.
10. Recompute affected typed state, health, findings, audit records, and daily
    reporting rollups.

The orchestrator is generic; matching algorithms remain entity-class
strategies. A new source reporting an existing class does not add resolver
branches. A genuinely new canonical class may add a typed table and matching
strategy without changing the source/observation platform.

### IN4. Authority and candidate behavior

- `may_establish_identity` and `may_create_canonical` are distinct and scoped
  to source instance, native type, and resulting entity type.
- Second-hand sources default to observation-only/candidate behavior. Their
  claims remain searchable and visible.
- Relay references attach only by exact lookup of an existing target source
  link; they never gain identity authority from the surrounding record.
- Reclassification changes history and future authority but never silently
  splits, merges, or deletes an established canonical entity.
- Candidate workflows support accept/create, attach, reject, reconsider,
  merge, and split with an audit trail.

### IN5. Existing connector migration

- Migrate all five current sources to the same record contract.
- Split Hudu's flat `cmdb.asset` classification without changing its stable
  observation identity; close/open history intervals for real transitions.
- Preserve Hudu records that cannot yet be accepted as observed-only or
  candidates.
- Resolve existing relay/card references through generic links.
- Do not add source-specific exceptions to shared lifecycle, coverage,
  reconciliation, health, or UI code.
- During the Ninja cutover, migrate `/devices-detailed` and `/device-health`
  through the common contract as distinct logical source-record namespaces.
  They may link to the same Device but must retain independent raw payloads,
  hashes, timestamps, and withdrawal state.
- Preserve current device consumers through compatibility projections for
  latest offline/contact/reboot/maintenance state; preserve fresh
  `latest_device_health` patch/troubleshooting signals; preserve Operations
  session reboot/boot-time state; and move the daily active-device trend to a
  compact daily rollup.
- Agent Compliance is out of scope. Do not disable, redesign, clean up, or
  spend implementation effort on it in this work.

Ninja affected-surface inventory, verified from the working tree on
2026-07-31 and mandatory to re-run before implementation:

| Responsibility | Current surface |
| --- | --- |
| `/devices-detailed` writer | `ingest/core/devices.py` |
| `/device-health` writer and health refresh | `ingest/core/device_health.py` |
| Legacy raw snapshot tables | SQL migrations `001` and `013` |
| Current/active device projections | SQL migrations `004`, `005`, `007`, `009`, `010`, `011`, and `015` |
| Ninja presence compatibility | `ingest/connectors/ninja_presence.py` |
| Operations session/reported-state projections | Operations migrations `0040`, `0076`, and `0077` |
| Health/patch/troubleshooting projections | SQL migrations `013` through `018` |
| Operations latest-user lookup | `operations/apps/core/views.py` |
| Metabase current signals and daily active trend | `ingest/metabase_bootstrap.py` |

The inventory names logical dependencies, not permission to trust stale line
numbers or omit newly added readers. Repository-wide SQL/Python reference
discovery is a required first step of the Ninja cutover.

## Track 3 — Admin surface

This is the cohesive destination for Operations administration. Narrow
corrective tracks may deliver bounded read-only status panels, but those panels
must use the shared **Admin → System** information architecture and fold into
this track; they must not introduce parallel administration navigation or a
source-specific UI framework. Navigation and landing-page consolidation remain
deferred Operations UI work in `operations/.work/backlog.md`.

### UI1. Automatic source discovery and health

- Source and source-instance pages query registrations, instances, runs, and
  generic health rows; no fallback list is authoritative.
- A newly deployed and registered source appears automatically with connection
  state, last run, last observation, errors, snapshot completeness, and counts
  by entity class/type.
- Deployment-controlled mappings and authority policies are visible read-only.
  Runtime editing remains out of scope.

### UI2. Generic entity and evidence surfaces

- Provide a generic entity directory/detail shell driven by entity class and
  registry metadata, with typed class-specific panels where needed.
- Show tenant/client ownership, all source identities, first/last seen,
  missing/withdrawn evidence, permitted raw source records, normalized claims,
  selected effective values, competing values, and selection reasons. Apply
  ADR-0010 sensitivity redaction and audited restricted-access rules; show
  withheld counts/placeholders so restricted evidence never looks absent.
- Render arbitrary registered attributes from definitions; source-specific
  templates are not required for basic visibility.
- Render peripherals and other linked entities through typed relationships,
  including direction, status, and supporting sources.

### UI3. Review and operator workflows

- Unified queues cover unresolved clients, observed-only entity candidates,
  ambiguous identity, attribute conflicts, incomplete relationships, and
  reconciliation conflicts.
- Operator actions are permission-checked, tenant-scoped, reasoned, audited,
  and separate from source evidence.
- Weak-source-only records are visible and clearly labeled; the UI never
  implies they are accepted canonical assets.
- Unknown types/attributes remain inspectable and lead to actionable findings.

### UI4. Other consumers

- APIs, CSV exports, evaluators, findings, notifications, and remaining
  reporting queries consume the same effective read models.
- Existing device URLs and views remain compatible through cutover.
- No consumer independently reimplements source precedence or effective-value
  selection.

## Cross-track delivery sequence

Each corrective track and ecosystem phase has a separate approval boundary.
Commit, push, database query, migration execution, and deployment remain
separately authorized.

Model guidance is advisory and should be revisited at each gate: Luna or Terra
is sufficient for Track A and aggregate measurements; use Terra for routine
Track B, ingest, and admin implementation; use Sol to review identity cutover,
physical claim/RLS design, backfill, and contract migrations. A model change is
never automatic.

### Corrective track A — lifecycle contact defect

This track is governed by ADR-0011 and does not depend on ADR-0009 or ADR-0010.

1. Obtain separate implementation approval for the narrow lifecycle-evidence
   correction. `lifecycle_evidence_mode` is the single normalized lifecycle
   capability and defaults to deny-by-default `none`.
2. With explicit read-only database approval, determine contact semantics for
   `network.device` and `monitor.target` and capture the exact device transition
   set, including verification of the reported 229-device `vm.guest` effect.
3. Bring the existing registry into model state; revoke application
   INSERT/UPDATE/DELETE on `entity_types` and `platform_aliases`; retain
   runtime SELECT and migration-role ownership; add and seed lifecycle-evidence
   eligibility and interpretation for every existing type; and switch only
   lifecycle evidence selection.
4. Validate the captured transition set and prepare data rollback before a
   separately approved migration/deployment.

The proposed evidence policy is:

- Direct agent contact is the highest-fidelity guest-OS signal.
- A recent explicit `reported_online` or VM power-state measurement is valid
  lower-fidelity evidence when no recent direct contact exists. Hypervisor
  power state is authoritative for the VM's power dimension and is retained
  even though it does not prove guest-OS health.
- A fresh powered-on/online state may support `active`; a fresh explicit
  powered-off, suspended, or offline state supports `offline_aging`, not
  `active`. The observation timestamp qualifies only as the measurement time
  of that explicit state; collection time alone is not contact.
- The newest qualified evidence wins. Direct contact wins only on an exact
  timestamp tie; contradictory evidence remains visible rather than discarded.
- `network.device` and `monitor.target` are lifecycle-evidence-capable, but
  their explicit reported state must be interpreted; a configured or freshly
  polled target is not automatically proof of successful contact.
- Unknown/unmapped states produce no transition and a data-quality finding.
  No qualifying evidence leaves the current lifecycle status unchanged.
  `retired` remains operator-owned. The user approved the deployed three-state
  automatic policy, and `operations/DESIGN.md` is reconciled to that decision.

Track A's model-state, grant, and lifecycle-evidence-mode work is the first
completed subset of DB1. The ecosystem track verifies and reuses it, then adds
only the remaining DB1 registries/capabilities; it does not replay or replace
Track A's migration.

### Corrective track B — stable observation identity

This track depends on ADR-0009 but not ADR-0010. The defect is deployed code
risk; whether duplicate active state already exists is determined by the
measurement rather than assumed.

1. Use accepted ADR-0009 as the design authority.
2. With explicit read-only database approval, measure bindings per source
   instance, derive and review namespaces for every source, identify
   parent-scoped IDs, and detect existing duplicate active identities.
3. Revalidate the DB2 affected-surface inventory against the then-current
   revision.
4. Expand, backfill, shadow/dual operate, compare, cut over, and retain legacy
   columns until rollback and full accounting are proven.

Tracks A and B are independently approvable but **serialized operationally**.
Track B's production cutover cannot begin until Track A's validation is
accepted and its rollback window is formally closed. Invoking Track A rollback
blocks Track B cutover until lifecycle state is stable and recaptured.

### Ecosystem track — database, ingest, and admin

This track depends on accepted ADR-0009 and ADR-0010. It need not delay either
corrective track above.

1. **Measure before physical claim-schema approval:** using authorized
   aggregate-only queries, measure source records by type, attributes per
   record (median, p95, maximum), observed material-change frequency, and
   current/history retention volumes. Project claim rows, index size, write
   amplification, WAL, and storage at 30/90/365 days. Include current Ninja
   raw-snapshot size/growth and projected generic current/change-history/daily-
   rollup footprints. Do not expose attribute values or customer data in
   results.
2. **Complete registry governance:** add the remaining semantic registries,
   independent capabilities, mappings, and policies.
3. **Expand the database:** add entity ownership, links, claims, policies,
   relationships, evidence, and generic read models without changing readers.
   Use the scale measurement to settle indexes, partitioning if justified,
   retention, and refresh strategy before creating the physical claim tables.
4. **Migrate ingest:** dual-write existing connector output through the common
   pipeline while legacy behavior remains authoritative. Ninja dual-write
   includes distinct `/devices-detailed` and `/device-health` namespaces and
   their compact daily rollup; it is not deferred until after generalization.
5. **Backfill and compare:** account for every observation and legacy link as
   migrated or explicitly deferred; compare identity, claims, attachments,
   relationships, lifecycle, and health over a complete collection cycle.
6. **Enable generic admin reads:** shadow-compare existing device/source pages,
   then expose candidates, evidence, attributes, and relationships.
7. **Cut over by consumer:** ingest authority first, then admin/API/evaluators;
   keep compatibility views until every named consumer is verified.
8. **Contract separately:** remove legacy columns/tables/branches only after a
   separately approved backup, restore rehearsal, rollback point, and deploy.

## Existing-data guarantees

- Current canonical client/device IDs and their foreign keys do not change.
- Existing raw payloads, current observations, and history are retained.
- Backfills are additive and resumable; no row is guessed into a namespace,
  source instance, client, entity, or relationship.
- Unmigratable rows remain on the legacy path and raise findings until resolved.
- Shadow-path failures roll back their savepoint and do not block the legacy
  write until the new path is promoted.
- Canonical entities are not deleted because evidence is reclassified,
  withdrawn, weak, or temporarily missing.
- Destructive contract work occurs only after read cutover, full accounting,
  backup/restore validation, and separate approval.
- The generic deployment does not delete, archive, truncate, or compact legacy
  Ninja snapshot history. That disk-reclamation phase starts only after Ninja
  cutover and named-consumer verification, with separate operational approval.
- Agent Compliance is unchanged and excluded from design, migration, cleanup,
  validation effort, and storage-reclamation scope for this work.

## Acceptance and validation

### Generic-source proof

Build a fixture connector with a new source name and no shared-code edits. Its
registration must cause it to:

- collect complete and partial snapshots safely;
- appear automatically in source health and admin navigation;
- produce observed-only records, candidates, and accepted links according to
  policy;
- display permitted/redacted raw evidence, normalized attributes, conflicts,
  effective values, and relationships under sensitivity policy;
- participate in reconciliation, findings, history, and audit;
- report arbitrary entity types in row-based health counts; and
- pass without adding its name to shared Python, SQL, templates, or tests.

### Data and migration validation

- Baseline and post-backfill counts/hashes for current observations, open
  history, source links, canonical attachments, and relationships.
- Every legacy row classified as migrated or explicitly deferred with a
  finding; zero unexplained loss.
- Stable identity tests for collector replacement, reclassification, parent
  namespaces, concurrent bindings, partial snapshots, and out-of-order data.
- Storage-contract tests prove one current row per stable identity, current raw
  refresh on every collection, deterministic raw hashing, versioned material
  hashing, no history row for volatile-only changes, history on material
  change/withdrawal, and no withdrawal after partial/failed collections.
- Ninja cutover tests prove endpoint provenance remains distinct and compare
  compatibility outputs for offline/contact/reboot/maintenance, health/patch/
  troubleshooting, session reboot/boot-time state, and the daily active-device
  trend across a complete collection and rollup cycle.
- Full-cycle shadow comparison before each read or write cutover.
- Attachment migration proves the current source link is the sole authority,
  link history reconstructs every reassignment, and compatibility observation
  entity IDs never diverge during shadow operation.
- Reverse migration or restore rehearsal for every reversible phase; explicit
  restore-only declaration for irreversible contract phases.

### Semantics and UI validation

- Capability-isolation tests prove each policy affects only its named consumer.
- Attribute tests cover competing authority, both single-value conflict
  policies, set union across one/all eligible tiers, per-value withdrawal,
  operator replace/add/remove/clear, weak-only evidence, reappearance, and
  equality between the effective projection and every typed cache.
- Relationship tests cover unresolved/ambiguous endpoints, cardinality,
  multiple-source corroboration, operator include/exclude precedence,
  withdrawal, and peripheral navigation.
- Candidate tests cover one-open-candidate uniqueness, create/attach/reject,
  material-change reopen, merge/split link history, and append-only audit.
- Tenant/RLS tests run under non-superuser application and read-only roles.
- Matview tests prove direct runtime-role reads fail, wrapper reads cannot cross
  the current tenant, the view-owner lacks login/`BYPASSRLS`, and refresh
  functions have a fixed `search_path`; refresh order and concurrent indexes
  are also verified.
- SQL tenant-helper tests cover missing, empty, malformed, non-positive, valid,
  and cross-tenant contexts; invalid context must raise rather than return zero
  rows. Migration ordering proves the helper exists before wrapper creation.
- Sensitivity tests cover default-restricted unknown fields, visible withheld
  counts/placeholders, the authorized classification path, UI/API redaction,
  audited restricted access, export exclusion, and absence of values from logs
  and finding text.
- Existing device/client pages, APIs, exports, evaluators, findings, and
  notifications receive regression tests.
- Representative scale tests validate identity lookups, entity/client
  navigation, claim retrieval, health aggregation, and refresh duration.
- SQL-aware and Python checks reject new hardcoded source/type membership
  tests, backed by behavioral tests rather than scans alone.
- Repository validation includes relevant pytest suites, Django checks, Ruff,
  migration-plan review, template smoke tests, and `git diff --check`.

## Affected areas

- `operations/apps/core/models.py`, migrations, RLS/grants, effective views,
  matviews, refresh functions, views, forms, URLs, templates, APIs, commands,
  and tests.
- `ingest/observations.py`, `observation_runs.py`, `source_observations.py`,
  identity/resolver modules, source registration, the in-scope source
  connectors, and ingest tests. Agent Compliance is excluded.
- Ninja writers in `ingest/core/devices.py` and
  `ingest/core/device_health.py`; legacy `ninja_core.device_snapshots`,
  `device_health_snapshots`, and `latest_device_health`; their SQL,
  Operations/session, connector-presence, views, and Metabase consumers.
- Accepted Operations architecture/decision records after approval.
- Compatibility consumers in findings, notifications, exports, and reporting.
- Root `VERSION` and `CHANGELOG.md` only when an approved release is prepared.

## Confirmed existing foundation

Already deployed and to be preserved: Hudu collection; generic observation
current/history; canonical clients/devices and class-specific links; source,
source-instance, and binding records; Hudu CMDB findings/relay work; ADR-0005
typed device layers; and the initial `entity_types` / `platform_aliases`
registry migration.

## Current checkpoint

The implementation is divided into three coordinated tracks: database
structure, ingest design, and admin surface, joined by one controlled migration
sequence. The prior stable-identity, generic-link, relationship-evidence, and
resolver-orchestration decisions are retained. Client ownership,
attribute-level claims/authority/effective values, generic read models, and
automatic admin behavior are now explicit requirements.

The user approved this design on 2026-07-31. The obsolete `.work` ADR drafts
were replaced by accepted ADR-0009 and ADR-0010 in the official Operations
decision directory. Both are accepted designs and remain unimplemented.
ADR-0007 was left unchanged so it remains a truthful record of deployed v5
behavior until ADR-0009 is implemented and cut over. No production state was
queried and no implementation file was modified.

Corrective track A (lifecycle contact) and corrective track B (ADR-0009
observation identity) are independently approvable and do not wait for the
ADR-0010 ecosystem. DB2 carries the affected-surface inventory verified at
`65f05d5`, with mandatory revalidation at implementation start. Aggregate
claim-volume measurement is now a pre-schema input for the ecosystem track,
not a post-cutover performance test.

The user then approved a generic source-evidence storage addition to the
ecosystem design. The supplied production baseline is 7.55 million rows /
13.39 GiB for `ninja_core.device_snapshots` (about 126,000 rows/day) and 7.09
million rows / 6.87 GiB for `ninja_core.device_health_snapshots` (about 125,000
rows/day), approximately 20.26 GiB total and 353 MiB/day estimated growth. This
turn did not independently query production; the figures remain a reported
baseline to be corroborated by the already-required aggregate-only sizing
gate.

ADR-0010 and Track 2 now require one refreshed current raw record per stable
source identity, deterministic raw and versioned material hashes, history only
for material change/withdrawal, and compact daily reporting rollups. Ninja's
`/devices-detailed` and `/device-health` records will use distinct logical
namespaces during connector cutover, with explicit compatibility gates for
current device, health/troubleshooting, Operations session, and daily trend
consumers. Agent Compliance is excluded. Legacy Ninja history cleanup and disk
reclamation are recorded in `.work/backlog.md` as a separately approved
post-cutover operational phase. No implementation, database query, migration,
production change, commit, push, or deployment was performed for this design
update.

Tracks A and B are operationally serialized: B cannot cut over until A's
rollback window closes. Track A's registry/model/grant work is the first DB1
subset and is reused, not repeated. DB3-DB7 now point to ADR-0010 and retain
only slice gates. ADR-0010 selects the current/historical attachment
authorities, effective-value and typed-cache ownership, set-valued claim
semantics, generic candidate and relationship-decision storage, sensitivity
enforcement, the fail-closed SQL tenant helper, visible redaction, and the
concrete tenant-safe matview wrapper boundary.

### Corrective Track A measurement and revised proposal — 2026-07-31

Authorized read-only aggregate queries were run through the documented shared
external-validation helper. No customer identifiers, payload values, or
timestamps were returned.

- `network.device` has 2 current-presence devices and `monitor.target` has 1;
  all carry contact clocks. Their explicit reported states are 1 online and 2
  offline. Both types are lifecycle-evidence-capable, but these measurements
  disprove the assumption that every fresh row is positive contact.
- `vm.guest` has 861 current-presence devices: 590 powered on, 253 powered off,
  and 18 suspended. The projected policy retains all of these authoritative
  power measurements while preferring recent direct agent contact for guest-OS
  liveness.
- The reported 229-device effect is confirmed: 229 persisted `active` devices
  project to `offline_aging` because the best current fallback evidence is a
  fresh powered-off guest state and there is no recent higher-fidelity direct
  contact.
- Preserving the deployed three-state automatic transition behavior produces
  an aggregate rollout set of 254 devices: 229 `active -> offline_aging` from
  fresh powered-off guest state, 20 `active -> offline_aging` from other aging
  evidence, 3 `offline_aging -> active` from direct contact, 1
  `offline_aging -> pending_cleanup` from stale evidence, and 1
  `pending_cleanup -> active` from a fresh powered-on guest state.
- For comparison, the former `operations/DESIGN.md` downgrade-only rule would
  have yielded 249 automatic transitions: the 229 powered-off guest cases plus
  20 other aging-evidence cases. The user instead approved preserving deployed
  three-state automation, and the detailed design is reconciled accordingly.

The earlier guest-exclusion projection was based on an incorrect semantic
assumption and is superseded by the state-aware figures above. Implementation
uses one normalized `lifecycle_evidence_mode`; `none` is the safe default and
the other modes explicitly interpret direct contact and reported state. No
migration, production data change, commit, push, or deployment has occurred.

The user approved and accepted this revised lifecycle-evidence policy and its
corrected aggregate measurements into the design plan on 2026-07-31. This
approval does not authorize implementation or any production-affecting action.
The user also approved a bounded, read-only lifecycle policy/status panel under
**Admin → System**. It is the first compatible slice of the larger Track 3
admin surface, not a separate administration area; broader navigation, landing
page, and generic entity/evidence UI work remain outside Track A and deferred
in the Operations backlog.

### Track A implementation — local work approved

**Goal and boundary.** Correct only the lifecycle-evidence selection defect.
Do not change canonical identity, source collection, observation identity,
device-session views, coverage, or operator retirement semantics. The approved
finding changes are the data-quality signals for an unknown lifecycle state
and for equally recent contradictory reported states.
Preserve the deployed `active` / `offline_aging` / `pending_cleanup` automatic
state machine for this track; `retired` remains operator-only. The user
approved this authority choice on 2026-07-31, and `operations/DESIGN.md` is
reconciled to it before implementation.

**Lifecycle decision table.** The registry gets one non-null
`lifecycle_evidence_mode` of `none`, `direct_contact`, `reported_state`, or
`direct_then_reported_state`. The database default is `none`, so a new or
unknown type cannot affect lifecycle until explicitly classified. Initial
seeds are:

| Entity type | Eligible | Interpretation |
| --- | --- | --- |
| `agent.rmm`, `agent.edr`, `agent.remote_access` | yes | `direct_contact` |
| `vm.host` | yes | `direct_then_reported_state` |
| `vm.guest` | yes | `reported_state` |
| `network.device`, `monitor.target` | yes | `reported_state` |
| `cmdb.asset`, `software`, `org`, `unknown` | no | `none` |

`direct_contact` uses a source-provided contact time, never collection time.
`reported_state` uses an explicitly recognized online/power state and the
source-observation time as the time of that state. The newest qualified evidence
wins: a newer direct contact projects `active`; a newer explicit powered-on or
online state may project `active`; and a newer explicit powered-off, suspended,
or offline state projects `offline_aging`. Direct contact wins only on an exact
timestamp tie. Otherwise qualifying evidence ages to `offline_aging` at seven
days and `pending_cleanup` at 30 days. Contradictory evidence remains visible.
An unknown/unmapped state produces no lifecycle transition and a data-quality
finding; it is never guessed as online or offline. With no qualifying evidence,
the evaluator leaves the existing lifecycle status unchanged. `retired` is
never changed automatically.

**Affected implementation surfaces.**

- `operations/apps/core/models.py`: model `operations.entity_types`,
  `operations.platform_aliases`, and `sources.entity_type`; define the
  lifecycle-evidence-mode choices.
- New Django migration after `0092`: use `SeparateDatabaseAndState` to bring
  the existing raw-SQL registry objects into Django state without recreating
  them; add and seed `lifecycle_evidence_mode`; add a check constraint for the
  allowed modes with a database default of `none`; and revoke
  `INSERT`, `UPDATE`, and `DELETE` on both registries from
  `operations_app` while retaining runtime `SELECT` and migration-role
  ownership. Its reverse restores the prior grants and removes only the new
  columns/constraint, never the pre-existing registry tables.
- `ingest/evaluator.py`: replace the identity-type timestamp maximum in
  `_sync_lifecycle_status` with deterministic newest-evidence selection and
  exact-tie fidelity precedence. Update lifecycle state and append an
  `operations.audit_log` event in the same transaction. The event is tied to
  the Device, carries before/after status, evidence reason/time, evaluator-run
  correlation, and policy version, and contains no raw source/customer values.
  Do not alter the presence or session materialized-view definitions unless
  strict unknown-state handling cannot be implemented without correcting the
  existing projection; any such dependency rebuild requires explicit review.
- `operations.audit_log` and its admin surface: reuse this generic tenant- and
  entity-scoped event stream as the permanent lifecycle audit landing. Make it
  append-only for runtime roles, grant the evaluator insert-only access, keep
  RLS, and expose lifecycle policy/status and lifecycle audit read-only under
  **Admin → System**. Reuse the shared admin shell and permissions; do not add
  parallel navigation or pull the broader Track 3 UI into this correction. The
  future unified entity anchor extends these events with the generic entity ID
  rather than moving them to a lifecycle-specific table.
- Finding registry/evaluator path: add a data-quality finding for an unknown
  lifecycle state, deduplicated by device/source evidence and automatically
  resolved once the state becomes recognized.
- New lifecycle evaluator tests under `ingest/tests/`: cover direct contact,
  powered-on, powered-off, suspended, network/monitor online and offline,
  newer/older/equal contradictory evidence, unknown state, multiple reported
  sources and deterministic ties, 7/30-day boundaries, no evidence, and retired
  devices. Add PostgreSQL integration tests proving atomic audit writes, RLS,
  append-only audit permissions, and read-only application access to both
  registries.

**Deployment and rollback.** The migration only changes schema, registry
metadata, findings, and grants; it must not bulk-update device lifecycle rows.
Immediately before the separately approved release, pause lifecycle evaluation,
rerun the aggregate transition query, and capture a restricted per-device
pre-change status backup outside Git. The first policy-driven evaluator run
atomically records immutable generic audit events. Rollback restores only a
recorded transition whose current status still equals that event's after-state
and which has no later lifecycle event, then rolls the evaluator and registry
logic back. Resume evaluation only after transition/audit counts and protected
statuses reconcile. The backup remains available until the agreed rollback
window closes. No customer values or backup contents enter repository files or
the release report.

**Validation gate.** Run `python manage.py check`, `python manage.py
makemigrations --check`, targeted lifecycle tests, applicable Ruff checks,
migration-plan review, and `git diff --check`. With explicit external approval,
verify registry grants, recapture aggregate transition counts before and after
the first evaluator pass, confirm backup/transition/audit counts reconcile,
verify unknown states open findings rather than transition, and confirm no
`retired` row changed. Deployment, migration execution, backup, evaluator
activation, rollback, commit, and push remain separately authorized.

### Track A local implementation checkpoint — 2026-07-31

The approved local implementation draft is complete. It adds Django state for the
existing registries; migration `0093` for the deny-by-default
`lifecycle_evidence_mode`, registry/audit grants, and lifecycle finding types;
deterministic evaluator selection with atomic generic audit events; and the
read-only **Admin → System → Lifecycle policy** surface at
`/admin/lifecycle/`. Its intended evaluator policy uses raw power state as an
exact allowlist, uses reported online only when power is absent, does not fall
back from direct contact to collection time, preserves the three-state
lifecycle model, leaves conflicts/unknown states unchanged, and records visible
data-quality findings. The approval review below identified a case where the
draft does not yet meet that intended policy.

Local validation passed: Python compilation, `python manage.py check`,
`python manage.py makemigrations --check`, focused lifecycle tests (7 passed),
targeted Ruff checks/formatting for new tests and migration, generated
migration-SQL review, and `git diff --check`. An opt-in PostgreSQL container
test covers migration grants, RLS, append-only audit access, and rollback of a
lifecycle update when its audit insert is denied. With explicit user approval,
it passed against a disposable PostgreSQL 16 container on 2026-07-31; Docker
Engine 29.6.2 was verified locally. Full Ruff on legacy Operations modules still
reports pre-existing violations outside this track. No migration was executed
and no external, production, commit, push, or deployment action occurred.

### Track A implementation approval review — 2026-07-31

**Result: changes required; do not approve migration execution yet.** The
checkpoint was reverified against Git status, diffs, and current files. The
review confirmed the following blockers and required corrections:

- Fail-closed power-state handling has a null-value hole. The existing presence
  projection maps a present but null VM `power_state` key to
  `reported_online = false`; the evaluator then treats that legacy projection
  as qualified offline evidence because it cannot distinguish a missing power
  field from a present null field. This can transition a future unknown VM
  state instead of opening the required finding. Carry raw power-field presence
  into selection, treat present null/unrecognized values as unknown, and allow
  the online fallback only when the power field is absent.
- Lifecycle finding upserts deduplicate only `open` and `acknowledged` rows,
  while lifecycle resolution also treats `investigating` and `suppressed` as
  active. Re-evaluation can therefore create a second open row for the same
  device/source condition. Define and test the intended operator-status
  behavior before approval.
- The Admin lifecycle endpoint uses authentication only instead of the shared
  admin permission, and the transition list omits the audited Device identity.
  Restrict the route with the existing admin authorization and make each row
  traceable to its tenant-scoped Device without placing raw source/customer
  values in audit payloads or logs.
- The seven focused tests do not cover the full approved matrix. Add coverage
  for the null/unknown power case, newer direct evidence, combined evidence
  mode, exact 7/30-day boundaries, no evidence, retired devices, finding
  create/deduplicate/resolve behavior, both registry read-only grants,
  append-only access for both runtime roles, and the Admin permission/response
  path.
- Migration `0092` documentation still says `is_identity_signal` controls
  lifecycle contact. Reconcile it with the accepted rule that
  `lifecycle_evidence_mode` is the sole lifecycle capability.

No implementation code, migration, external system, production data, commit,
push, or deployment was changed during this review. The two plan files were
updated solely to preserve the confirmed review checkpoint.

### Track A bounded correction pass — 2026-07-31

The user approved this local-only correction pass. It is limited to the five
review findings: preserve raw power-field presence through lifecycle selection;
refresh one existing lifecycle finding in any active operator status instead of
creating a duplicate; apply the existing shared Admin permission and show the
audited Device ID; expand the decision-matrix, PostgreSQL permission/RLS, and
request tests; and correct migration `0092` documentation. Active lifecycle
findings retain their `open`, `acknowledged`, `investigating`, or `suppressed`
operator state when refreshed; resolved and `wontfix` rows remain history and a
later recurrence opens a new row. No migration execution, external system,
production data, commit, push, or deployment is authorized.

### Track A correction validation and rereview — 2026-07-31

**Result: local implementation review passed; migration execution remains
separately unapproved.** The correction carries raw `power_state` field
presence into evaluator selection, so a present null value now opens the
unknown-state finding and cannot fall back to the legacy offline projection.
Lifecycle findings refresh one existing row across `open`, `acknowledged`,
`investigating`, and `suppressed` without overriding operator status; resolved
and `wontfix` rows retain historical recurrence behavior. The read-only Admin
surface now requires the shared admin permission, displays the audited Device
ID, and the audit event records non-sensitive evidence entity type/platform.

Actual local validation passed:

- 12 lifecycle unit tests;
- the opt-in disposable PostgreSQL 16 test for null-state handling, finding
  deduplication/resolution, retired-device preservation, registry grants,
  runtime append-only/RLS behavior, and update/audit atomic rollback;
- 3 Django Admin lifecycle permission/template tests;
- `python manage.py check` and `python manage.py makemigrations --check`;
- targeted Ruff checks and formatting checks for new tests/migration, and
  `git diff --check`.

The evaluator retains its established surrounding formatting to avoid an
unrelated file-wide rewrite; full Ruff on legacy Operations modules continues
to report pre-existing violations outside Track A. No migration, external
system, production data, commit, push, or deployment was performed.

### Track A authorized aggregate preflight — 2026-07-31

The user authorized a fresh aggregate-only production preflight. The documented
helper confirmed that Operations, ingest, and Postgres are healthy. No pause,
backup, migration, evaluator run, production write, commit, push, or deployment
occurred. The final read-only projection used the accepted fail-closed policy
and returned only aggregates:

| Metric | Aggregate result |
| --- | ---: |
| `active → offline_aging` from direct contact aging | 38 |
| `active → offline_aging` from reported state | 255 |
| `active → pending_cleanup` from direct contact aging | 47 |
| `offline_aging → pending_cleanup` from direct contact aging | 1 |
| `pending_cleanup → active` from reported state | 1 |
| `pending_cleanup → offline_aging` from reported state | 1 |
| Total projected transitions | 343 |
| Unknown reported-evidence rows (no transition) | 99 |
| Equal-time reported-state conflict devices (no transition) | 0 |
| Eligible devices without qualified evidence (no transition) | 20 |

The first read-only attempt exposed a new local blocker before any data query:
the implemented evaluator orders the latest raw observation by `o.id`, but the
deployed table key is `o.observation_id`. A projection using the deployed key
completed successfully; the current local evaluator would instead fail at this
query after migration. Do not approve migration execution. A narrow local code
and disposable-test fixture correction is required, followed by the same
focused checks and rereview.

The user approved that narrow local-only correction. It changes only the
evaluator lateral-query tie-break from `o.id` to `o.observation_id` and aligns
the disposable PostgreSQL fixture with the deployed table key. No migration,
production data change, or further external action is authorized by this
approval.

### Track A observation-key correction validation and rereview — 2026-07-31

**Result: local implementation review passed again; migration execution remains
separately unapproved.** The evaluator now orders raw observations by the
deployed `observation_id` key. Python compilation, targeted Ruff, all 12
lifecycle unit tests, the disposable PostgreSQL test using the deployed-shaped
key, and `git diff --check` passed. No migration, production data change,
external action, commit, push, or deployment occurred during the correction or
rereview.

### Track A lifecycle-evaluator pause assessment — 2026-07-31

The user authorized a controlled pause of **lifecycle evaluation only** before
the next read-only aggregate recapture. A read-only inspection of the running
ingest service confirmed that it is healthy and runs `python -m ingest.main`
with an `unless-stopped` restart policy. The currently deployed scheduler ran
the platform evaluator once in the preceding six hours. The implementation has
one in-process `platform_evaluate_cycle` and a manual run endpoint, but no
durable lifecycle-only pause switch, scheduler-control endpoint, or documented
safe external pause procedure. The available operational action would pause or
stop the entire ingest service and therefore also interrupts unrelated ingest
cycles; it is outside the authorization and must not be substituted silently.
No pause, recapture, backup, migration, evaluator activation, production data
change, commit, push, or deployment occurred.

The user accepted the cleaner cutover approach: do not pause the whole ingest
service. Instead, when separately authorized, take the final aggregate
recapture and restricted pre-change backup in one short, transactionally
consistent operational window. This preserves a defensible before-state without
interrupting unrelated ingest cycles.

The user then authorized that window. Three safe attempts made no production
data or schema change and produced no retained backup: two stopped before the
measurement completed because of local query/marker defects, and the corrected
attempt completed the aggregate statement within a read-only exported snapshot
but could not create the protected dump because the approved SSH account cannot
write `/amr-ch-01_data/ninja-dashboard/backups`. The directory is root-owned;
noninteractive sudo is unavailable. The temporary artifact was removed and the
snapshot transaction closed without a backup or returned measurement output.

The host owner then created the approved private Operations backup location.
The corrected repeat completed: a restricted custom-format PostgreSQL backup
was retained in that protected directory (two copies are retained because the
first successful dump accompanied a measurement-query duplication defect; the
later copy is the authoritative measurement/backup pair). The later pair
returned this exact aggregate transition set: 38 `active → offline_aging`
direct; 254 `active → offline_aging` reported; 47 `active → pending_cleanup`
direct; 1 `offline_aging → active` direct; 1 `offline_aging → pending_cleanup`
direct; 1 `pending_cleanup → active` reported; and 1 `pending_cleanup →
offline_aging` reported — **343 total**. There were 0 equal-time reported-state
conflicts and 18 eligible devices without qualified evidence. The temporary
projection initially reported 4,884 unknown rows; a follow-up
evaluator-equivalent live query reconciled the correct value to **99 rows
across 99 devices**, all present-null `vm.host` power fields. The higher value
was a projection-query defect, not a production data change.
No migration, evaluator activation, production data change, commit, push, or
deployment occurred.

### Track A independent migration-readiness review — 2026-07-31

**Result: do not approve the current release shape yet.** Code and migration
validation passed, the authoritative protected backup checksum matches and its
`pg_restore` catalog parses, production is at prerequisite migration `0092`,
and `operations_migrate` owns both tables whose grants change. Focused results:
15 unit/UI tests and the disposable PostgreSQL integration test passed;
Django system and migration-state checks, targeted Ruff/format checks, Python
compilation, and `git diff --check` passed.

The blocking issue is cutover control. Migration `0093` both creates the safe
default column and immediately changes the approved entity types to active
lifecycle evidence modes. The same release ships an ingest evaluator that runs
automatically on its four-hour scheduler (and can also be invoked manually).
There is no lifecycle-only runtime pause. Consequently, migration execution and
evaluator activation cannot be separate approval gates in the current package.
The safest correction is to keep `0093` schema/grants/finding types with every
mode at the database default `none`, then add the policy-seeding update as a
later migration in a separately approved activation release. No implementation
was changed during this review.

The user approved that local-only correction. Migration `0093` now leaves every
existing and future entity type at safe default `none`; the PostgreSQL test
asserts that inert post-migration state before applying a test-only policy so it
can continue proving evaluator behavior. The later policy-seeding migration is
recorded in `operations/.work/backlog.md` and must not be bundled into the
schema-landing release. Validation passed: 15 focused unit/UI tests, the
disposable PostgreSQL integration test, Django system and migration-state
checks, targeted Ruff/format checks, Python compilation, and `git diff --check`.
No migration, production change, commit, push, or deployment occurred.

### Track A inert-release rereview — 2026-07-31

**Result: technically passed; one operational consequence requires explicit
acceptance.** No production activation seed exists outside the test-only
fixture, Docker packaging includes the changed runtime/migration/UI files, and
the focused validation passed again: 15 unit/UI tests, the disposable
PostgreSQL test, Django checks and migration-state check, targeted Ruff/format,
and `git diff --check`. Because the new evaluator fully replaces the legacy
lifecycle sync, deploying it while every mode is `none` pauses automatic
lifecycle-status updates until the later activation release. It does not pause
ingest, observations, coverage, or other evaluator work, and it changes no
existing lifecycle status. This scoped pause is the mechanism that makes schema
landing and policy activation genuinely separate gates. No implementation or
external state changed during rereview.

The user explicitly accepted the scoped pause. The inert schema release may
temporarily pause automatic lifecycle-status updates; ingest, observations,
coverage, findings outside the new lifecycle types, and other evaluator work
continue, and existing lifecycle statuses are unchanged. The next gate is one
local Track A schema-landing commit. Unrelated documentation, decision records,
probes, and existing dirty work remain excluded. No files were staged,
committed, pushed, deployed, or migrated while preparing this gate.

The user then approved and the repository now contains local commit `434f24d`
(`feat(operations): add inert lifecycle evidence policy`). It contains only the
Track A runtime, migration, UI, focused tests, Operations continuity record,
and deferred activation entry; mixed root-plan and unrelated dirty work remain
outside the commit. Validation immediately before commit passed. No push,
deployment, migration, or production change occurred.

The separately approved `origin` push was confirmed on 2026-07-31: remote
`origin/master` resolves to `434f24d`. The secondary mirror was not touched.
No deployment, migration, or production validation was requested or performed.

The separately approved secondary-mirror push was then confirmed on
2026-07-31: `a-m-rose/master` advanced from `0557afe` to `434f24d`, matching
`origin/master`. No deployment observation, migration, or production validation
was requested or performed.

The user then authorized read-only deployment observation and live
migration-readiness verification. Ingest and Operations had been rebuilt and
were healthy; Postgres remained healthy and was not recreated. The running
Track A migration/template artifacts matched the local commit byte-for-byte,
and the evaluator matched after normalizing the Windows checkout's CRLF line
endings to the Linux image's LF. Django migration status showed both `0092`
and `0093` applied.

This exposed two process/documentation defects. First, `VERSION` remains
`0.98.5` and `CHANGELOG.md` contains no Track A release entry even though the
commit shipped runtime behavior, a migration, and a user-visible Admin page.
Second, the documented production path couples an `origin` push to Portainer
redeployment and the Operations entrypoint applies Django migrations at
startup. Deployment and schema application therefore were not achievable as
later independent gates after the push; prior plan wording to that effect was
incorrect. The migration remained inert by design, but release metadata and
the approval/runbook model must be reconciled before continuing. No write,
migration command, policy activation, or production-data change was performed
during the read-only observation.

The user approved a local-only release/documentation correction. The prepared
correction advances the stack release authority from `0.98.5` to `0.98.6`,
adds the missing Track A changelog entry, records the durable lifecycle/audit
decision in ADR-0011, and reconciles root/Operations instructions and runbooks
with the coupled `origin` push → Portainer redeploy → startup-migration path.
Version `0.98.6` is local only until separately committed and pushed; the
currently running images were built from commit `434f24d` while the repository
still declared `0.98.5`. No implementation code, external state, production
data, migration, commit, push, or deployment changed during this correction.
Documentation validation passed: root `VERSION` matches the first changelog
entry, the active instructions/runbooks consistently describe the coupled
GitOps boundary, scoped files have no trailing whitespace, and
`git diff --check` reports no whitespace errors (line-ending warnings only).

The user separately approved and local commit `18c8d05`
(`docs(release): record Track A lifecycle release 0.98.6`) was created from
only the nine scoped release/documentation paths. Mixed root-plan,
generalization, audit-redesign, probe, and other unrelated changes remain
outside the commit. No push or external/production action occurred.

The authorized read-only inert-state verification then passed all immediately
observable checks. All 11 entity types remain at mode `none` and 0 have an
active mode; both lifecycle finding types exist; lifecycle transition audit
count is 0; the mode column is non-null with default `none`; audit RLS is
enabled; application registry access is SELECT-only; application audit access
is SELECT/INSERT without UPDATE/DELETE; and ingest audit access is INSERT-only.
Operations health returned 200, the unauthenticated lifecycle route returned
the expected 302 authorization redirect, and ingest readiness returned 200.

No `platform_evaluator` run had completed since the containers were recreated.
The scheduler registered the four-hour job at approximately 18:17:29 UTC, so
its first ordinary post-deployment run is due around 22:17 UTC. A manual trigger
was not initially used because the full evaluator writes normal role/finding
outputs outside the initial read-only authorization. Executed-inert verification
therefore remained a safe time-based observation until broader approval.

The user then explicitly authorized one full production platform-evaluator run
and aggregate outcome measurement. A pre-run snapshot recorded 11/11 modes at
`none`, lifecycle states of 4,473 `active`, 205 `offline_aging`, and 539
`pending_cleanup`, no Track A lifecycle findings, 0 lifecycle transition audit
events, and no prior post-deployment evaluator run. Exactly one manual run was
scheduled; it completed successfully with 4,347 aggregate row effects across
the evaluator's full role/finding pipeline and no failed run.

The post-run Track A aggregates were identical: 11/11 modes remained `none`;
the lifecycle distribution remained 4,473 / 205 / 539; Track A lifecycle
findings remained absent; and lifecycle transition audit events remained 0.
This closes executed-inert verification. The 4,347 row-effects count belongs
to the evaluator's other normal pipelines and is not represented as 4,347
distinct state changes. No customer-level data was returned.

The user then separately approved pushing `18c8d05` to `origin`, explicitly
including the automatic Portainer redeploy and startup migration runners; the
reviewed pending migration set was empty. The push completed and
`origin/master` resolves to `18c8d05`. The secondary mirror was not touched,
and no post-deployment observation was performed under this approval.

The user separately approved the required secondary-mirror push.
`a-m-rose/master` advanced from `434f24d` to `18c8d05` and now matches
`origin/master`. No post-deployment observation, migration command, policy
activation, or production-data action was performed with the mirror push.

## Next action

Follow `operations/.work/plan.md` for Track B's stable-key marker cutover.
Expansion and dual-write are deployed and verified. The permanent membership
table proposal was rejected before implementation; the approved direction is
one current row per stable identity, compact run summaries, and history only
for material or presence transitions. Release `0.100.0` and migration `0096`
are locally validated and committed as `fc1d482`; the next gate is explicit
`origin` push approval covering automatic Portainer deployment and startup
migration.

The Docker-build validation blocker was traced to workstation HTTPS
inspection: Windows trusts the local Geder Filter root, while Linux build
containers receive only its re-signed PyPI leaf. Both application images now
build with TLS verification through an optional local BuildKit CA secret. The
root was not committed or retained in either final image; normal production
builds do not require the secret. See the active Operations plan for hashes and
validation details.

Deployment of `fc1d482` applied migration `0096`, but post-migration source
reruns exposed a raw-SQL/default mismatch: `begin_run()` omitted the new
non-null `observed_identity_count`, while the local PostgreSQL fixture's
artificial `DEFAULT 0` masked the deployed Django schema. Corrective Track B
now includes a bounded `0.100.1` hotfix to insert zero explicitly and make the
fixture production-faithful before source verification resumes.

The `0.100.1` hotfix is locally validated: focused unit and disposable
PostgreSQL tests pass without a database default, along with Ruff, compilation,
diff checks, and the secure ingest image build. It adds no migration or design
change. It is committed as `30c460c`; the next required gate is one combined
two-remote push approval.

Corrective Track B is complete. Both remotes and production now run hotfix
`30c460c` / `0.100.1`; migration `0096` is applied. Three post-hotfix source
runs completed with 8,304 writes and matching distinct-identity counts.
Aggregate validation found zero incomplete identities, stable collision groups,
presence mismatches, ingest errors, or Operations HTTP 500s; all 25 recent
history closures carry deciding-run provenance. The next action is to select
the next approved root ecosystem slice, not to remove legacy rollback fields or
perform historical cleanup.

For future releases, one explicit push approval may cover both remotes as a
combined operation: push `origin` first, push `a-m-rose` immediately, and run
deployment validation after both pushes. The durable procedure is recorded in
`docs/operations.md` and should ride the next substantive commit rather than
triggering a documentation-only redeploy.

## Ecosystem sizing gate — confirmed findings (2026-08-03)

The user authorized aggregate-only, read-only production sizing. No payload
values, record identities, client names, or Agent Compliance measurements were
returned.

- Ninja raw snapshots now hold 7,917,609 device rows and 7,444,016 health
  rows. Their combined total size is 21.27 GiB (18.09 GiB heap and 2.24 GiB
  indexes). The last 30 days averaged 130,749 device and 127,007 health rows
  per day, or 363.7 MiB/day including indexes (325.4 MiB heap only). Linear
  retained-size projections are 10.66/31.97/129.64 GiB at 30/90/365 days,
  including indexes.
- The device endpoint made 718 collections in 30 days; its daily active-device
  count is p50 5,480, p95 5,520, maximum 5,556. Health made 702 collections
  in the same interval. Consumer audit corrected the provisional rollup grain:
  the existing trend applies current client, device-type, and patching-scope
  filters by device, so compatibility requires one compact source-identity row
  per UTC day (about 2.0 million rows/year), not one fleet total per day. It
  still eliminates repeated hourly rows and contains no raw JSON.
- Generic current observations contain 24,293 rows (23,880 active) and occupy
  153.2 MiB including indexes; material history contains 39,290 rows (23,880
  open) and occupies 64.7 MiB. Current raw-record key counts range from p50/p95
  7/7 for LogMeIn hosts through 25/35 for Ninja devices, 43/43 for
  ScreenConnect sessions, and 85/85 for SentinelOne agents. This confirms that
  a source-defined material projection, rather than every raw key, is required.
- Of the history rows, 24,293 are first-seen baseline intervals and 14,997 are
  later material transitions. The data covers only 22 calendar days; the recent
  seven-day transition rate is 328 rows/day (2,293 rows), but it is not yet a
  steady-state retention basis. Its provisional physical-size projection is
  only 16.2/48.6/197 MiB at 30/90/365 days, before future source growth.
- A PostgreSQL WAL baseline was captured (3,999,558,938,275 cumulative bytes),
  but a single sample cannot establish a WAL rate. A later aggregate-only delta
  is required before setting a write/WAL budget.

**Implementation recommendation.** Preserve the approved generic contract:
one current raw record per stable namespace identity, material/withdrawal-only
history, and a compact daily active-device rollup. Do not partition generic
current or material-history tables initially: their measured footprint is small
and the history sample is still bootstrap-biased. Reassess after at least 30
days of steady material-change and WAL-delta measurements. Ninja's legacy raw
snapshot retention and deletion remain a separately approved post-cutover
operational phase; do not carry their hourly append pattern into generic ingest.

**Next approval gate.** Before a physical claims/rollup schema is finalized,
authorize a second aggregate-only WAL and material-transition sample after a
meaningful interval (preferably 24 hours, then confirm at 30 days) and a
Sol/high review of ADR-0010's physical design. No migration, backfill,
retention change, or historical deletion is approved by this measurement.

## Ninja snapshot cutover audit — complete proposal (2026-08-03)

The user authorized a design-and-consumer audit only. Repository inspection was
read-only apart from this continuity update; no implementation, migration,
production write, deletion, commit, push, or deployment occurred.

### Confirmed current behavior and gaps

- `/devices-detailed` writes the typed `ninja_core.devices` current dimension,
  a full raw row to `device_snapshots` every collection, and a generic current
  observation in the already-deployed `device` namespace. The generic current
  row has the full raw payload, but its canonical projection omits several
  compatibility fields: normal-device boot time, explicit offline state,
  reboot state, last user, and maintenance state. `ninja_core.devices.data`
  is also a second current copy of the same endpoint raw payload.
- `/queries/device-health` writes only `device_health_snapshots` and refreshes
  `latest_device_health`; it does not yet use generic observations. Keep the
  accepted `device` namespace for `/devices-detailed` to preserve deployed
  stable identities and add the distinct `device-health` namespace for the
  health endpoint under the same Ninja source instance. Health must use its own
  complete-snapshot scope so one endpoint can never withdraw the other.
- The shared writer currently applies one global volatile-field exclusion list.
  This contradicts the accepted material policy: it excludes `power_state`,
  boot time, and offline state even where they are meaningful source state. It
  also trusts caller-computed raw hashes made from Python object string output,
  rather than centrally hashing deterministic complete JSON. This must be
  corrected before the Ninja cutover, not copied into the health writer.
- The active direct consumers are the current definition of
  `ninja_core.v_active_devices`; `operations.device_session_current`;
  Agent Compliance's Ninja presence reader (behavior remains out of scope);
  Operations software-user risk; three Metabase reads for troubleshooting,
  last contact, and the daily trend; and `latest_device_health`, which feeds
  troubleshooting/patch signals and their dashboards. Historical migration
  files are lineage, not additional live readers, but new migrations must
  recreate the current dependent views in dependency order.
- The daily trend does not prove that each device contacted Ninja on the day.
  It counts a device when `/devices-detailed` returned it at least once that
  day, then applies today's client/type/patching-scope filters. The compatible
  rollup is therefore one stable `device` source-identity presence row per UTC
  day, inserted once after a successful complete collection. A fleet-total row
  would lose required filters; hourly updates or raw JSON are unnecessary.

### Approved-contract implementation recommendation

1. Extend the shared observation contract with centrally computed canonical
   JSON `raw_hash` and a centrally registered material projection selected by
   stable record namespace plus entity family. Keep one shared hash algorithm;
   do not place ad hoc hashing in connectors. Store a separate material
   projection version on current and history because ADR-0010 requires both
   hash-algorithm and projection versions. Projection upgrades require an
   explicit reproject/backfill path, not an unexplained source transition.
2. Enrich `device` canonical current data with typed `offline`,
   `last_contact_at`, `last_boot_time_at`, `needs_reboot`, reboot reasons when
   actually supplied, `last_user`, maintenance fields, VM power state, and VM
   parent identity. Current always refreshes all of them. Material history
   includes identity/classification fields plus explicit offline state,
   reboot state and boot time, maintenance state, and VM power/parent state;
   it excludes collection time, contact timestamps, derived `is_online`, and
   last-user heartbeat-like churn. Direct agent contact remains the
   higher-fidelity current lifecycle evidence; hypervisor power state remains
   a valid material measurement for its own power dimension.
3. Write each `device-health` record to generic current/history with all typed
   health counts, status, pending-reboot reason, explicit offline/parent state,
   and product-installation statuses in its material projection. Store the
   endpoint's complete raw record only in generic current. A zero or incomplete
   collection must fail closed and withdraw nothing; only a successful complete
   health snapshot may reconcile the `device-health` scope.
4. Add a compact generic daily presence rollup keyed by the full stable source
   identity and UTC day, with optional resolved canonical IDs but no raw JSON.
   Populate `device` identities with `INSERT ... ON CONFLICT DO NOTHING` after
   successful complete runs. At measured p50 this is about 164,400/493,200/
   2,000,200 rows at 30/90/365 days. Validate the physical row/index/WAL size
   with a disposable PostgreSQL scale test before finalizing retention or
   partitioning; do not partition by default without that evidence.
5. Introduce compatibility projections rather than making consumers parse raw
   JSON independently: a latest `device` projection with the existing snapshot
   column contract; `latest_device_health` with its existing name and columns;
   and a Ninja daily-presence projection for the trend. Rebuild
   `v_active_devices` on the current projection, repoint Operations session and
   software-user reads, repoint the three direct Metabase reads, and repoint
   Ninja presence without changing Agent Compliance logic. Preserve refresh
   ordering and verify all dependent troubleshooting/patch views.
6. Treat generic current as the eventual sole raw authority.
   `ninja_core.devices.data` may remain as a bounded duplicate during the
   rollback window. The legacy snapshot tables continue their temporary
   poll-driven growth only through dual-write, then are frozen at read/write
   cutover; none is a second permanent raw contract. Removing the duplicate
   `devices.data` contract is a later compatibility cleanup after all readers
   use generic current.

### Safe cutover and approval gates

- **Expand/dual-write release:** add versioned shared hashing, the health
  namespace, rollup, and shadow compatibility projections; continue legacy
  writes. Backfill only the latest health state and distinct device/day rollup,
  not hourly raw history. Any production migration/backfill needs explicit
  deployment approval.
- **Compare gate:** require at least two successful complete runs and aggregate
  parity for identity counts, every compatibility field, withdrawal state,
  hashes/versions, current freshness, daily counts under every dashboard filter,
  material-history growth, run provenance, errors, and Operations HTTP 500s.
  Partial/zero-run tests, out-of-order tests, and rollback rehearsal must pass.
- **Read/write cutover release:** only after comparison approval, move every
  named reader to compatibility projections and stop both legacy hourly snapshot
  inserts. Keep legacy tables intact and read-only as rollback evidence; no
  deletion or disk reclamation is bundled.
- **Contract cleanup and operational cleanup:** removal of duplicate current raw
  compatibility, archive/delete of legacy snapshot history, and disk reclamation
  remain later, separately approved phases after the rollback window and named
  consumer verification. Agent Compliance redesign remains excluded.

**Next approval gate.** Approve or revise this physical/cutover proposal before
any implementation. The safest implementation is two releases: first
expand/dual-write, then a separately reviewed read/write cutover that stops the
legacy growth. Before preparing the first migration, take the planned 24-hour
aggregate WAL/material-transition delta and run the disposable PostgreSQL
rollup scale test. No code, migration, backfill, or production action is yet
approved by this completed audit.

The user approved this proposal on 2026-08-03. Pre-implementation validation is
in progress: capture a precisely timestamped aggregate-only production baseline
and delta, and measure the proposed 365-day per-identity/day rollup shape in a
disposable local PostgreSQL container. This approval does not yet authorize
implementation, migrations, production writes, commit, push, or deployment.

### Pre-implementation measurement checkpoint (2026-08-03)

The first external command failed in remote-shell parsing before PostgreSQL ran
and made no query or state change. The corrected query ran inside an explicit
read-only transaction and returned aggregates only. The earlier WAL value had
no recorded capture time, so its 23,018,942-byte (21.95 MiB) difference cannot
be represented as a rate. A defensible new baseline is:

- captured `2026-08-03T14:46:58.959022Z`;
- cumulative WAL `3,999,581,957,217` bytes (statistics reset
  `2026-06-02T20:24:25.222173Z`);
- current observations 24,293 total / 23,880 active;
- material history 39,290 total / 14,997 later transitions, unchanged from the
  prior sample; 402 later transitions fall inside the moving preceding 24-hour
  window;
- legacy rows in the preceding 24 hours: 131,063 device and 120,139 health.

The qualifying 24-hour delta may be taken no earlier than
`2026-08-04T14:46:58.959022Z`. Until then, no WAL rate is confirmed.

A disposable local PostgreSQL 16 container tested 2,000,200 rows, matching the
measured p50 365-day population. The conservative table repeated the full
stable identity tuple in each daily row and used a primary key plus day/device
and device/day indexes. It loaded in 32.55 seconds, generated 1,270,322,504
bytes (1.18 GiB) of WAL, and occupied 688.3 MiB: 208.1 MiB table and 480.2 MiB
indexes. A repeated 5,480-row same-day collection inserted zero rows, generated
zero WAL, and completed in 112 ms. A filtered 90-day client/type/scope trend
completed in 9.7 ms.

A second lossless shape stored the stable current source-record UUID plus
namespace/date in each rollup row, leaving the complete unique identity tuple
on the referenced current record. Its primary key was
`(tenant_id, source_record_id, rollup_day)`; it used one
tenant/namespace/device/day index and a small BRIN date index. It loaded in
21.89 seconds, generated 885,882,840 bytes (844.8 MiB) of WAL, and occupied
513.4 MiB: 192.9 MiB table and 320.4 MiB indexes. Duplicate behavior remained
zero-row/zero-WAL in 110 ms, and the same trend completed in 9.4 ms. This saves
175.0 MiB (25.4%) retained storage and 366.6 MiB (30.3%) initial WAL without
using a probabilistic identity hash or losing namespace/date provenance. The
source-record UUID is already stable across current-row updates and resolves to
the enforced full identity tuple. The disposable container was removed after
measurement.

**Physical-design recommendation and approval gate.** Prefer the compact
source-record-reference rollup over repeating the full identity tuple in every
daily row, with an enforced foreign key and the current row retained through
withdrawal. This is a material refinement of the just-approved physical shape
and requires explicit approval before implementation. After that decision and
the measurement gate, implementation may be planned as the already approved
two-release expand/dual-write then read/write-cutover sequence. The accelerated
conclusion below supersedes the initially proposed 24-hour wait. No code,
migration, production write, commit, push, or deployment occurred.

### Accelerated sizing conclusion (2026-08-03)

The user rejected waiting 24 hours and required an accelerated answer. The
24-hour gate is replaced by four independent measurements already available:
the actual 30-day legacy growth sample, a 21-complete-day material-history
distribution, the database-wide WAL window since its June 2 statistics reset,
and the disposable 365-day physical scale test.

The aggregate-only production follow-up remained read-only. Across the latest
21 complete days, later generic history transitions totaled 14,909: median
214/day, average 710/day, p95 3,651, and maximum 8,276. The mean is dominated by
bootstrap/cutover outliers. Database-wide WAL since the statistics reset
averages 64,748,061,392 bytes/day (60.3 GiB/day), a conservative all-workload
ceiling rather than a rollup-specific budget. In contrast, the compact rollup
scale load generated about 2.3 MiB of WAL per retained device/day population
day, and duplicate hourly batches generated zero WAL.

A proposed-projection simulation over seven days was canceled by its 60-second
read-only statement timeout and made no state change. A narrower full-fleet
comparison used the preceding day only for `LAG` context and completed in 51
seconds. For the latest complete day it found 2,482 material device-detail
transitions among 136,525 poll rows and 1,311 material health transitions among
120,640 poll rows: 3,793 material changes from 257,165 source rows. This is a
98.5% reduction in history inserts while retaining explicit offline, reboot,
boot, maintenance, VM power/parent, and health-state changes.

The proposed material payloads are compact: device average/p95 240/283 bytes
and health average/p95 257/280 bytes. Existing generic history averages 406
material-payload bytes and 1,728 total physical bytes per row including table
and index overhead, so using the larger existing physical average is a
conservative projection. At the measured 3,793 transitions/day plus the compact
daily rollup, estimated retained storage is 0.22/0.67/2.73 GiB at 30/90/365
days versus the legacy 10.66/31.97/129.64 GiB projection: approximately 97.9%
less. Fixed current-state storage adds only one bounded row per source identity
and does not change this conclusion materially.

**Conclusion.** The reduction is sufficient, and a further 24-hour wait is not
required for physical-design approval. The only remaining pre-implementation
decision is explicit acceptance of the compact foreign-keyed rollup refinement.
Once accepted, implementation can start with the expand/dual-write release;
commit, push/deployment, read/write cutover, and cleanup retain their separate
documented gates.

## Ninja snapshot expand/dual-write implementation — in progress

The user approved the compact foreign-keyed rollup after the accelerated sizing
conclusion. Scope is the first, additive release only: centralized deterministic
raw hashing and versioned record-contract material projections; additive
projection-version and daily-rollup schema; enrichment of Ninja `device`
current evidence; `device-health` generic current/history dual-write in a
separate complete-snapshot scope; shadow compatibility projections; and a
dry-run-by-default, resumable operator backfill of legacy daily device presence.
Legacy snapshot writers and readers remain authoritative. The read/write cutover,
legacy-write stop, duplicate-current cleanup, historical deletion, and disk
reclamation are not part of this release.

The measured physical policy for this expansion is: reuse the existing generic
90-day default for closed material-history intervals; never purge an open
current interval; retain compact daily presence without automatic deletion;
and do not partition the rollup initially. Its primary key plus BRIN date index
is sufficient at the measured 30/90/365-day sizes. Reassess daily-rollup
retention and partitioning after 30 days of steady-state write/WAL evidence;
any deletion remains separately approved.

Expected affected files: `ingest/observations.py`, `ingest/core/devices.py`,
`ingest/core/device_health.py`, focused ingest tests, Operations observation
models/migration, the operator backfill module, `VERSION`, `CHANGELOG.md`, ADR-0007/
ADR-0010 implementation status, and the root/Operations continuity plans.

Implementation sequence:

1. Add the projection-version and compact rollup schema with tenant-safe
   constraints, RLS/grants, retention-supporting indexes, and shadow views.
   Legacy rollup backfill records are explicitly identified and do not invent
   snapshot-run provenance.
2. Centralize deterministic raw hashing and namespace/entity-family material
   projection selection without changing existing non-Ninja contracts.
3. Enrich Ninja detail current data, populate the daily rollup idempotently,
   and dual-write health current/history with zero/partial fail-closed behavior.
4. Add focused unit and disposable PostgreSQL tests for hashes, projection
   changes, distinct scopes, duplicate-day zero growth, withdrawal safety,
   compatibility-field parity, out-of-order behavior, and resumable daily
   backfill behavior.
5. Run Operations checks, focused tests, Ruff/compilation, migration-order and
   packaging review, Docker builds, scale/parity checks, HTTP 500 smoke checks
   where locally available, and `git diff --check`.
6. Rereview the complete diff. Stop for separate commit approval; a later push
   approval must cover `origin` then the mirror and coupled deployment.

No production write, migration, commit, push, or deployment is authorized by
this implementation start.

### Implementation checkpoint — locally validated 2026-08-03

- The generic observation writer now owns deterministic raw hashing and
  namespace-specific material projections. Ninja `device` projection v2 keeps
  offline/reboot/boot/maintenance/VM state material while contact timestamps
  and last-user heartbeat noise update current only. Ninja `device-health`
  uses a separate namespace and typed material projection.
- Migration `0097_ninja_snapshot_expand` adds projection versions, the compact
  tenant/RLS daily-presence table, explicit run-backed versus legacy-backfill
  provenance, and security-invoker device/detail, health, and daily shadow
  views. Legacy tables and readers are unchanged.
- Device collections update one generic current raw row per stable identity,
  append generic history only on material/presence transitions, and insert at
  most one run-backed daily presence row per device/day. Health collections
  shadow-write distinct current/history evidence and fail without withdrawing
  evidence when zero known rows are returned. Legacy snapshot writes remain
  authoritative in both paths.
- `ingest.backfill_ninja_daily_rollup` is operator-invoked, dry-run by default,
  bounded to explicit completed UTC days, one transaction per day, aggregate-
  only, idempotent, and fail-closed on missing/ambiguous stable mappings. Apply
  rows explicitly identify legacy provenance without fabricated run IDs.
- Focused tests: observation unit tests passed (30; one optional dependency
  skip), the complete ingest suite passed (57; seven opt-in/dependency skips),
  and Operations core passed (26; one opt-in PostgreSQL skip). The opt-in
  disposable PostgreSQL set then passed separately (4), covering migration
  forward/reverse, constraints, actual tenant RLS, compatibility fields,
  stable identity, run-backed daily writes, legacy backfill, duplicate-day
  zero growth, fail-closed unmatched mappings, and UTC boundaries under a
  non-UTC session.
- Django `check` and `makemigrations --check --dry-run` passed; `0097` is the
  next migration. Focused Ruff checks, formatting, Python compilation, and
  `git diff --check` passed. A whole-tree Ruff audit still reports 74 unrelated
  pre-existing findings; none is in the new backfill/migration or changed
  ingest paths after focused validation.
- Both production images built with the approved optional workstation CA
  secret. In-image imports/version/backfill help, device-health projection,
  Django checks, migration-state checks, and a root HTTP smoke request passed;
  the root returned the expected `302`, not a 500. The new operator module is
  included by the ingest image's existing directory copy.
- Expansion `434cf72` was pushed to both approved remotes. Portainer deployed
  `0.101.0`, migration `0097` applied, both application containers became
  healthy, readiness passed, and the Operations root returned its expected
  `302` with no HTTP 500s. No historical backfill or cleanup occurred.

### Post-deployment full-cycle finding and hotfix

The user approved one normal production full ingest cycle. Device current/
history completed, 5,461 active device records moved to projection v2, and
exactly 5,461 unique run-backed daily rows landed. Legacy device health then
completed for 5,461 received records, but the additive health shadow rolled
back with `uq_obs_hist_open_identity`. Aggregate verification showed all 5,461
legacy health rows had distinct device IDs. The actual collision was between
device detail and device health: both used the same binding, entity type,
parent key, and legacy `entity_key`, while the retained rollback-era constraint
does not include the new `external_namespace`. Stable identity correctly
distinguishes the `device` and `device-health` namespaces. No partial health
shadow data landed, and the authoritative legacy health write remained
successful.

Release `0.101.1` namespace-qualifies only health's mutable legacy compatibility
key as `device-health:<external ID>`. The stable namespace/ID, raw provenance,
canonical device link, and legacy health tables remain unchanged. This lets the
two endpoint records coexist under both legacy and stable constraints without
dropping rollback protection. Scope is limited to
`ingest/core/device_health.py`, focused unit/PostgreSQL regression coverage,
`VERSION`, `CHANGELOG.md`, and this checkpoint. No migration, data repair, or
contract change is required because the failed health shadow transaction left
zero rows.

Local validation passed: the complete ingest suite reported 73 passed with five
expected opt-in skips; the focused disposable-PostgreSQL tests passed with both
the retained legacy and stable current/open-history uniqueness constraints; and
focused Ruff, formatting, compilation, and `git diff --check` passed. The
workstation-CA build path produced the `0.101.1` ingest image, whose embedded
version and compatibility-key assertions passed. Aggregate-only production
follow-up confirmed the authorized `0.101.0` full cycle reached its completion
marker, both application containers remained healthy, ingest had zero restarts,
and Operations logged zero HTTP 500s. The one health-shadow error was the known
rolled-back compatibility-key collision; no second production cycle was
started before the repair is deployed.

### Post-`0.101.1` full-cycle finding

Commit `31de068` was pushed to `origin` and the secondary mirror. Portainer
deployed `0.101.1`; both application containers became healthy and the running
ingest image passed the compatibility-key assertion. One explicitly authorized
production full cycle then wrote 5,463 device-detail records and successfully
wrote 5,463 legacy plus 5,463 generic device-health records with zero
health-shadow errors.

The cycle later failed before its completion marker while refreshing
`operations.device_agent_presence_current`. That projection groups by
`subplatform` but its required unique key is per tenant/device/entity type/
platform. Once health evidence could land, the `device` and `device-health`
records for the same Ninja device produced two grouped rows for one unique key.
The refresh transaction rolled back, so the previously valid derived views
remain in place; health current/history committed independently and remain
available. No ingest module run was marked failed, and the application
containers remained healthy.

The approved contracts already assign Ninja presence/contact and VM power to
the device-detail record while retaining device health for patching and
troubleshooting. Release `0.101.2` therefore rebuilds the existing derived-view
chain with `device-health` excluded only from the device-presence projection.
It does not delete or unlink health evidence and does not change current,
history, compatibility views, stable identity, or legacy health storage.

Expected affected files are migration `0098`, its focused test, `VERSION`,
`CHANGELOG.md`, and this checkpoint. Validation must include a representative
PostgreSQL projection containing both namespaces, migration order/state,
Django checks, focused Operations tests, image builds, and an aggregate-only
production projection simulation. A later push gate must explicitly include
automatic deployment and migration `0098`; after deployment, one full cycle
must complete with health parity, derived refresh success, and zero HTTP 500s.

### `0.101.2` validation checkpoint

- A representative PostgreSQL 16 test applied the complete migration SQL over
  the existing derived-view chain with linked `device` and `device-health`
  observations for the same VM. Migration `0098` recreated presence, session,
  effective-device, and source-health read models; the result had one presence
  row, retained explicit online and `poweredon` evidence, and passed the
  production unique key.
- The full Operations core suite passed (27, with two expected opt-in skips),
  and the focused PostgreSQL migration tests passed separately (2). Django
  `check` and `makemigrations --check --dry-run` passed; migration order shows
  `0098` immediately after deployed `0097`.
- Focused Ruff, formatting, compilation, and `git diff --check` passed. Both
  workstation-CA image builds passed; the Operations image contains and imports
  `0098`, and the ingest image reports `0.101.2` while retaining the deployed
  compatibility-key repair.
- Aggregate-only production measurement found 5,456 per-platform presence-key
  collisions with both namespaces included and zero with `device-health`
  excluded. Health evidence itself is complete: 5,463 active current rows,
  5,463 open history rows, 5,463 distinct external IDs, all compatibility keys
  namespace-qualified, and the latest health snapshot run is complete at
  5,463 expected/written. Both application containers remain healthy;
  Operations health returns `200`, its root returns the expected `302`, and no
  Operations HTTP 500s were logged during the validation window.

### `0.101.2` deployment and full-cycle verification

Commit `81a67c3` was pushed to `origin` and the secondary mirror. Portainer
deployed `0.101.2`; migration `0098` applied once, the rebuilt presence view
contains its health-namespace exclusion, and the production presence key has
zero duplicates. Both services returned healthy with zero restarts;
Operations health returned `200`, its root returned the expected `302`, and no
Operations HTTP 500s were logged.

Exactly one authorized full production cycle started and reached exactly one
completion marker. Device detail and device health each completed at 5,463
legacy writes and 5,463 generic writes; the latest health snapshot run is
complete at 5,463 expected/written. Active generic current, open history, and
legacy health all match at 5,463 distinct device IDs. The legacy latest-health
view also retains 614 older inactive devices by design. Daily presence remained
idempotent at 5,463 rows/distinct records for the UTC day. Patches completed at
17,533 and activities at 2,421. The final derived coordinator completed;
`device_session_current` contains 5,247 rows and was refreshed during the
cycle. There were zero health-shadow errors, tracebacks, or recent failed
module runs.

### Daily-rollup backfill measurement

The authorized aggregate-only dry run measured the complete available legacy
range, 2026-06-02 through 2026-08-02. Across 62 completed UTC days it found
335,647 distinct device/day rows: 330,134 mapped, 5,513 unmatched historical
device/day occurrences, and zero ambiguous mappings. The gaps affect 260 unique
historical devices across the first 41 days, ending 2026-07-12; the maximum was
200 missing mappings in one day. No rows were inserted.

A second dry run confirmed the continuous clean range from 2026-07-13 through
2026-08-02: 21 completed days, 115,297 device/day rows, all 115,297 mapped,
with zero unmatched or ambiguous mappings. This range is safe and idempotent
to apply under the documented one-day-per-transaction process.

### Historical identity gap audit

Aggregate-only follow-up confirmed that all 260 unique gaps are historical-only
Ninja devices: all 260 remain in `ninja_core.devices`, all are noncurrent with
`missing_since` populated, and all retain a raw source record. None has a Ninja
canonical device link, canonical device, or device-health observation. The gap
is therefore not ambiguity or data loss; these devices disappeared before the
generic current-evidence population and were never assigned a stable source
record row.

The complete repair should restore one inactive generic `device` source record
per historical Ninja identity, without creating or linking a canonical device.
Each restored identity must preserve raw provenance and stable namespace/ID,
represent its observed interval as closed history, and leave current evidence
inactive at the recorded withdrawal boundary. The full 62-day daily rollup can
then reference those identities without weakening the foreign key or silently
dropping history.

### Historical identity restoration implementation

Approved scope is a dry-run-by-default operator tool, focused PostgreSQL and
unit coverage, the operational runbook, and this checkpoint. The tool selects
only legacy Ninja device identities required by an explicit completed UTC-day
range that lack generic `device` evidence. It must fail closed if any selected
identity is still current, lacks raw evidence or a withdrawal boundary, or has
a canonical Ninja device link. Identities with existing generic current
evidence are measured and left unchanged; an orphaned history-only identity is
a blocker rather than a state the tool silently repairs.

Apply mode will create no source run, canonical device, client mapping, source
link, candidate, or finding. It will restore one stable inactive current row
per eligible identity using the retained latest raw `/devices-detailed`
payload, the last real observation timestamp, and the recorded
`missing_since` withdrawal boundary. It will also create one closed active
history interval from the earliest retained observation to that withdrawal
boundary. Both rows retain null canonical IDs and null snapshot-run provenance.
Deterministic IDs and conflict checks make the operation idempotent without
silently accepting a changed target.

Validation must prove read-only default behavior, aggregate-only output,
fail-closed blockers, no canonical side effects, current/history consistency,
hash/projection parity with normal Ninja writes, idempotency, UTC range bounds,
packaging, and a new aggregate-only full-range production dry run. No schema
migration is expected.

The `0.101.3` implementation and rereview are complete. The tool sets an
explicit read-only transaction unless `--apply` is supplied; apply uses one
serializable transaction and a scope advisory lock. It derives deterministic
record IDs, rechecks eligibility under the lock, uses the shared raw/material
hash contract, inserts inactive current plus closed active history, and masks
unexpected database details from operator output. All blocker categories,
including orphaned history-only evidence, are aggregate-only and fail closed.

Focused unit coverage passed (3). The disposable PostgreSQL 16 test passed,
covering zero-write measurement, apply shape and timestamps, VM power/material
projection, raw/material hashes, null canonical/run provenance, daily-rollup
referential use, idempotency, no source-link creation, and each fail-closed
blocker category. The complete ingest image suite passed (76; six expected
opt-in/dependency skips). Focused Ruff, formatting, compilation, and
`git diff --check` passed. Both images built; the ingest image reports
`0.101.3` and contains the operator. Django `check` and
`makemigrations --check --dry-run` passed. There is no pending schema
migration.

The authorized aggregate-only production preflight over 2026-06-02 through
2026-08-02 found 6,087 legacy identities, 5,827 with existing generic current
evidence, and the same 260 missing identities. All 260 are eligible: source and
collector provenance each resolve exactly once, with zero current-legacy,
withdrawal-boundary, raw-evidence, canonical-link, history-evidence, or
interval blockers. No production rows were written.

The reviewed implementation was released as `0.101.3`; production data writes
remain outside that deployment and require the gates below.

### `0.101.3` deployment verification

Commit `56662bb` was pushed to `origin` and the secondary mirror. Portainer
deployed the `0.101.3` ingest image with no pending Django or ingest schema
migration. The ingest container is healthy and ready with zero restarts; both
ingest health/readiness endpoints and Operations health returned `200`, and
the Operations root returned its expected `302`. Since deployment there are
zero traceback, exception, ERROR-level, migration-failure, or restoration-
failure log entries and zero Operations HTTP 500s. Broad `failed`/`error` text
matches were all INFO-level Metabase reporting labels, not failures.

The packaged operator imported successfully and its production read-only
default completed over 2026-06-02 through 2026-08-02 with `apply=false` and
zero inserts. It measured 6,087 legacy identities, 5,827 existing generic
identities, 260 missing/eligible identities, zero blocked identities, and zero
counts in every individual blocker category.

### Ninja deletion-event evidence refinement

An authorized read-only production correlation used the API's effective
`status=NODE_DELETED` filter and the nested
`data.message.params.nodeId` identity. The existing connector's documented
`statusCode` query parameter does not filter this event, and the configured
activity allowlist does not include it. Over the restoration range, 84 delete
events were available and 51 matched the 260 eligible historical identities
exactly; 209 had no matching event. Every match supplied a node display name.
The next missing-poll boundary followed deletion by a median 0.5 hours: 48 of
51 were within two hours, with a maximum of 33.494 hours. No rows were written
and no customer values were reported.

The accepted generic contract now retains source-native deletion as immutable
source-event evidence, including vendor event/time, stable node identity,
source/client scope, result, and source actor identifier plus protected actor
display metadata. Ninja supplies node ID/name, client ID/name, and deleting
application-user ID/name/email, but not a complete device inventory. Actor
names and email addresses are customer-sensitive and must not enter findings
text, logs, or aggregate validation output.

A validated delete event is higher-fidelity withdrawal confirmation than the
later complete poll: the source record closes at the event time with reason
`source_deleted`, while the missing poll remains corroboration. It may open or
refresh an idempotent finding when deletion is unexpected or additional action
is required. It never creates, deletes, or retires a canonical device and is
not an Operations decommissioning approval. Future decommissioning may use it
to auto-confirm source removal while separately auditing the source actor and
the Operations decision actor. ADR-0010 records the durable contract; the
connector/event implementation and full workflow are deferred in
`.work/backlog.md`. They are not prerequisites for this restoration. The
deployed restoration operator remains unchanged and uses the corroborated
`missing_since` boundary for all 260 identities.

### Production historical-identity restoration

The separately approved production apply completed atomically for all 260
eligible identities. Its SSH wrapper timed out before returning the operator's
final output, but the container process completed and no database transaction
remained active. Independent aggregate verification proved the committed
result: all 6,087 legacy identities now have generic current evidence and zero
remain missing.

The restored set contains exactly 260 inactive current rows and 260 closed
history rows. Every current row has a withdrawal boundary and raw/material
hashes; every history boundary matches current `withdrawn_at`; all intervals
are valid; and there are zero missing or open history rows. All current/history
canonical references and snapshot-run provenance are null, and zero Ninja
canonical source links were created. Six identities have one retained
observation, so their valid closed interval has
`last_seen_at = effective_from < effective_to`.

The post-apply read-only operator run found 6,087 existing generic identities,
zero missing/eligible identities, zero blockers, and zero inserts. Both
application services remained healthy with zero restarts; ingest health and
readiness and Operations health returned `200`, the Operations root returned
the expected `302`, and the post-write window contained zero application error
or HTTP-500 signals.

The required full daily-rollup dry run then completed all 62 UTC days from
2026-06-02 through 2026-08-02. All 335,647 legacy device/day facts matched
stable generic evidence, with zero unmatched, zero ambiguous, and zero rows
written.

### Production daily-rollup backfill

The separately approved production apply completed all 62 UTC days from
2026-06-02 through 2026-08-02 using one transaction per day. It inserted
exactly 335,647 compact source-record/day facts, matching every measured legacy
device/day occurrence, with zero unmatched or ambiguous mappings.

Independent database parity found exactly 335,647 expected and stored facts in
the range, 62 completed days, zero missing or unexpected facts, zero duplicate
source/day keys, and zero invalid provenance rows. All range rows are marked as
legacy backfill with null snapshot-run provenance. The whole table contains
341,110 rows after including 5,463 facts written by normal current collection;
its measured heap plus indexes total 45,481,984 bytes (about 43.4 MiB).

The post-write read-only full-range rerun again completed 62 days and measured
335,647 matched facts, zero unmatched, zero ambiguous, and zero inserted rows.
Both application services remained healthy with zero restarts; ingest health
and readiness and Operations health returned `200`, the Operations root
returned the expected `302`, and the validation window contained zero
application error or HTTP-500 signals.

**Next gate:** the historical restoration/backfill milestone is complete.
Separately review and approve reader cutover before any dashboard or
compatibility consumer treats the generic projections as authoritative.
Legacy-write shutdown and historical snapshot archive/deletion/disk
reclamation remain later gates after consumer parity. No deletion-event
implementation, decommissioning workflow, cleanup, or Agent Compliance change
is included.

### Reader-cutover initial audit

The user authorized the reader-cutover review after restoration and rollup
completion. Initial static audit confirms this is a cross-service release, not
a single dashboard query change:

- `ingest/core/devices.py` still inserts every device poll into
  `ninja_core.device_snapshots`, refreshes `ninja_core.v_active_devices`, and
  only then writes generic `device` evidence. Cutover must stop the snapshot
  insert and reorder generic write before compatibility refresh.
- `ingest/core/device_health.py` likewise inserts
  `device_health_snapshots`, refreshes `latest_device_health`, and only then
  writes generic `device-health` evidence. Cutover must stop the legacy insert
  and reorder the generic write before health compatibility refresh.
- The deployed `v_active_devices` definition still reads
  `device_snapshots`. The deployed `latest_device_health` definition still
  reads `device_health_snapshots`; compatibility under that stable name feeds
  troubleshooting/patch projections introduced by SQL migrations 014 through
  018.
- Remaining direct runtime readers are Ninja presence in
  `ingest/connectors/ninja_presence.py`, Operations software-user risk in
  `operations/apps/core/views.py`, and three Metabase definitions for current
  troubleshooting context, patch-coverage contact, and daily devices seen.
  The daily trend must use `operations.ninja_device_seen_daily_shadow`.
- The Operations presence projection was rebuilt from generic observations by
  migration `0098`, but deployed `device_session_current` still reads legacy
  snapshots for reboot and boot time. Historical migration references other
  than the latest deployed definitions are not runtime dependencies.
- `ninja_core.devices.data` remains the approved bounded current duplicate for
  rollback. Legacy snapshot tables stay intact; archive, deletion, and disk
  reclamation remain prohibited in the cutover release.

The next reviewer must re-read the actual deployed view definitions, enumerate
all database dependents, and run aggregate field/filter parity before editing.
The implementation needs one coherent migration plus writer/reader refresh
ordering, focused PostgreSQL and Django/Metabase tests, rollback rehearsal,
release metadata, and full image validation. No code, migration, production
change, commit, push, or deployment has been authorized or performed for this
cutover review.

The handoff review used `gpt-5.6-sol` with high reasoning and completed the
read-only deployed-definition, dependency, and aggregate parity audit below.

### Reader-cutover deployed audit and correction gate

The deployed database dependency graph is exact:

- `device_snapshots` directly feeds `v_active_devices` and
  `operations.device_session_current`; the latter feeds `operations.v_device`.
- `device_health_snapshots` directly feeds `latest_device_health`.
- `v_active_devices` and `latest_device_health` directly feed
  `device_troubleshooting_signal`.
- Ninja materialized views are owned by the ingest database owner; Operations
  session/effective views and the three shadow views are owned by
  `operations_migrate`. The cutover therefore requires an ingest SQL migration
  and a separate Django migration. They must be independently forward-
  compatible because the two services start and migrate concurrently.

The latest completed production collection wrote 5,466 device records and
5,465 health records. Against the authoritative `Ninja` device scope and
projection v2, generic device current has exact identity, observation time,
raw payload, offline/contact, reboot, last-user, and maintenance parity. The
candidate active-Windows population also matches all 4,014 legacy IDs exactly.
The previously verified 335,647 historical device/day facts are set-equal to
the legacy distinct set; because both trend forms join the same active-device
rows and filters, this proves parity for every current dashboard filter.

Two blockers and three intentional withdrawal corrections were confirmed:

1. The broad detail shadow includes 162 active projection-v1 records from the
   retired `ninja_main` snapshot scope. All 162 source devices are legacy
   noncurrent, have valid `missing_since` boundaries, and retain open generic
   history. Of them, 154 rows are linked to 95 canonical devices; 88 of those
   devices have other active evidence and seven do not. All rollup references
   remain valid if the current rows are withdrawn. These rows must close at
   their existing `missing_since` boundaries; canonical devices and links must
   remain.
2. The current shadow cannot scan all broad Ninja rows because 144 of those
   retired-scope records contain projection-v1 epoch boot strings. Narrowing
   the current shadow to the authoritative source instance, snapshot scope,
   and projection version excludes them, but the stale rows still require the
   source-withdrawal correction above.
3. On 834 current `vm.guest` and 99 current `vm.host` records, generic
   `last_boot_time_at` replaces the OS boot value with Ninja's top-level VM
   boot value. Legacy and raw `os.lastBootTime` agree on every one of these 933
   records, while generic agrees with the distinct top-level value. Preserve
   OS boot as the compatibility/session value and retain the VM-reported value
   under a separately named canonical field; power state remains separate and
   unchanged.
4. Generic health is field- and raw-payload-exact for all 5,465 active health
   identities. One current device has a roughly two-hour-old legacy health row
   but correctly withdrawn generic health evidence from the latest complete
   snapshot. Promotion intentionally changes that stale health signal to null.
   The other 615 legacy-only health rows belong to noncurrent devices and are
   not current troubleshooting inputs.
5. Existing session selection considers 4,932 linked canonical devices. The
   active generic candidate has 4,866: all 66 omitted selections use a
   noncurrent Ninja identity. Among devices with evidence on both sides, 321
   select a different Ninja identity because multiple links share collection
   timestamps and the legacy query has no fidelity tie-breaker. Reboot and OS
   boot match exactly whenever the selected identity matches. Cutover must use
   deterministic newest-evidence selection with direct-agent precedence on an
   exact tie; deleted identities must not continue supplying session state.

The Operations latest-user reader's historical fallback initially appeared to
require retained state, but bounded aggregate measurement disproved that need:
4,481 current records have a nonempty user, and all 985 with an empty current
user also have no historical nonempty user. Generic current therefore preserves
the result while eliminating a legacy query that exceeded two minutes during
validation. Two attempted broad read-only parity queries were cancelled after
the external wrapper timed out; the first briefly blocked one normal refresh,
so only its exact validation backend was cancelled. The lock cleared, no
application transaction was cancelled, and all later measurements used bounded
indexed queries or statement timeouts.

#### Proposed corrective preparation release

Before reader/write cutover, prepare one bounded patch release that leaves all
legacy readers and snapshot writes authoritative:

- Fix Ninja canonical normalization so `last_boot_time_at` remains OS boot
  time. Retain the VM top-level boot measurement under an explicit separate
  field; do not change hypervisor power-state evidence.
- Add a Django migration that narrows the detail and health shadow views to the
  configured Ninja source instance and their authoritative snapshot scopes;
  preserve the daily shadow's inactive historical identities and rollup facts.
- Add a dry-run-by-default, fail-closed operator that selects only the 162
  active `ninja_main` rows proven noncurrent with valid withdrawal boundaries,
  marks current evidence inactive, and closes open history at
  `missing_since`. It must preserve canonical devices, source links, rollups,
  raw evidence, and operator decisions; apply remains a separate production
  data approval.
- Add focused unit/PostgreSQL coverage for scope isolation, boot-field
  separation, withdrawal shape, idempotency, and derived-presence effects;
  update release metadata and validate both images. No read promotion or
  legacy-write shutdown belongs in this release.

After deployment, require one complete device/health cycle, exact shadow
parity, a zero-blocker operator dry run, healthy services, and zero HTTP 500s.
Then separately approve the 162-row source-withdrawal apply and controlled
presence/session/lifecycle refresh. Measure every projected lifecycle change
before allowing it, and verify canonical/link/rollup preservation afterward.

#### Later read/write cutover release

Only after the corrective release and apply verify cleanly:

- An ingest SQL migration rebuilds `v_active_devices`,
  `latest_device_health`, and `device_troubleshooting_signal` from the promoted
  projections while preserving names, columns, indexes, grants, and owners.
- A Django migration rebuilds `device_session_current`, `v_device`, and its
  dependent refresh chain from active generic detail evidence with
  deterministic direct-agent tie precedence.
- Collector code writes generic current first, refreshes compatibility views
  afterward, and stops both legacy hourly snapshot inserts. Device current raw
  compatibility remains during rollback.
- Ninja presence, Operations software-user risk, and the three direct Metabase
  readers move to the promoted projections. Agent Compliance logic is not
  redesigned; only its required Ninja presence input is repointed.
- Full-cycle parity, saved-dashboard replacement, migration/refresh ordering,
  image packaging, rollback rehearsal, health/readiness, and HTTP-500 checks
  must pass before the cutover is accepted. Legacy tables remain intact and
  no archive, deletion, or disk reclamation is included.

The user approved implementation of only this corrective preparation release
on 2026-08-03. This approval does not authorize commit, push, deployment, the
162-row production apply, reader promotion, or legacy-write shutdown.

#### `0.101.4` corrective-preparation validation checkpoint

The approved local implementation and review pass are complete. A final
writer-invariant review found that a projection-only v2-to-v3 upgrade could
otherwise update current evidence while leaving its open SCD-2 history row on
v2. The generic writer now treats a material-projection version change as an
explicit history boundary even when the material hash is equal. ADR-0010 and
the changelog identify this as a contract boundary, not a source-state change.
The first successful v3 Ninja device collection after deployment will
therefore create one bounded history transition for each collected existing
v2 device identity (approximately 5,466 at the last aggregate production
measurement). The 933 measured VM identities are expected to carry the newly
separated hypervisor boot measurement; other identities transition solely to
keep current and open history on the same material contract. This happens once
per identity for this projection upgrade, not on later unchanged polls.

Implementation scope is confined to the Ninja device normalization and
historical-restore canonicalization, generic material writer, migration `0099`
shadow definitions, the retired-scope operator, focused tests, Operations
entrypoint packaging, operator runbook, ADR-0010, `VERSION`, `CHANGELOG.md`, and
this plan. Existing unrelated worktree changes and probe files remain
untouched. No production query, write, migration execution, commit, push, or
deployment occurred in this implementation phase.

Confirmed local validation:

- focused unit coverage passed, including boot separation, projection v3,
  stale-scope safety, and the projection-only boundary;
- the full ingest suite passed in disposable PostgreSQL 16 containers: 89
  tests passed;
- focused PostgreSQL coverage proved a v2 row with an unchanged material hash
  becomes one closed v2 interval plus one open v3 interval while current is
  v3;
- all 12 changed Python files passed compilation, focused Ruff checks, and
  Ruff formatting; `git diff --check` passed;
- both deployment images built through the documented BuildKit workstation-CA
  secret path; the ingest image imported the changed modules and reported
  `0.101.4`;
- the Operations image passed `manage.py check` and
  `makemigrations --check --dry-run` (with the expected warning that the local
  validation container has no `postgres` hostname), and its default entrypoint
  executed and failed closed on missing database credentials as designed.

The broader repository Ruff check remains unsuitable as a release gate because
it reports pre-existing failures and formatting drift in unrelated Agent
Compliance, intelligence, Metabase, and local probe files. Changed-file checks
are clean.

**Next approval gate:** request separate approval to commit this one logical
`0.101.4` corrective-preparation change while staging only its intended hunks.
After that commit, request a distinct combined push approval for `origin` first
and the secondary mirror immediately afterward; that approval must explicitly
cover automatic deployment, migration `0099`, and the one-time v3 history
transitions. The 162-row retired-scope apply remains a later independent
production-data approval after a post-deployment aggregate-only dry run.

#### `0.101.4` deployment and `0.101.5` hotfix checkpoint

Commit `b0c7e53` was pushed to `origin` and the secondary mirror under the
combined approval. Portainer built and recreated the stack; ingest reports
`0.101.4`, migration `0099_ninja_shadow_scope_correction` is applied, and both
changed containers are healthy. An explicitly authorized normal full cycle
completed device and health collection successfully with 5,469 rows each.
Aggregate read-only validation found 5,469 active projection-v3 detail rows,
5,469 open projection-v3 history rows, zero current/open-history mismatches,
zero OS-boot mismatches against the same-cycle legacy snapshots, and exact
detail/health shadow counts of 5,469 each. All 933 current VM records retain a
non-null hypervisor-reported boot measurement; Ninja supplied no non-null
`os.lastBootTime` for those VM records in this cycle, so the distinct OS claim
correctly remains null rather than being replaced. The daily shadow contains
341,119 retained rollup facts. No ingest error-level log, traceback, exception,
or failed-row signal was observed.

The full cycle's Inventory refresh ran from `19:51:26Z` through `20:00:08Z`
while multiple refresh workers used substantial PostgreSQL CPU and temporary
I/O. During that interval, the Operations Software surface produced one HTTP
500 and two Gunicorn worker timeouts. The final Operations derived refresh and
the full cycle subsequently completed successfully; both containers are
healthy, and a three-minute post-refresh window contained zero further 500s or
worker timeouts. This is not caused by projection v3 or migration `0099`, but
it means the strict zero-500 full-cycle cutover criterion is not satisfied.
The broader concurrent/serialized refresh correction is recorded in the root
backlog and remains a separate design/implementation approval before reader
cutover.

The deployed dry-run operator made no changes and safely returned 162 blockers,
all in withdrawal-boundary validation. Diagnosis confirmed a bounded defect:
restored historical rows have `last_received_at` after their historical
`missing_since`, because receipt is restoration provenance rather than source
evidence time. The open-history contract already validates the correct source
interval (`effective_from < missing_since`), but the Python blocker and final
apply predicate additionally compared `missing_since` with receipt time.

The local `0.101.5` hotfix removes `last_received_at` only from those two
source-ordering comparisons and changes no selection scope, pinning,
transaction, preservation, or apply behavior. Its PostgreSQL regression now
models a receipt after `missing_since` and proves the row remains eligible and
the pinned apply is atomic and idempotent. The full ingest suite passes 89
tests in disposable PostgreSQL 16; focused compilation, Ruff, formatting, and
`git diff --check` pass; and the secure workstation-CA build produces an ingest
image that imports the operator and reports `0.101.5`.

#### `0.101.5` deployment and dry-run checkpoint

Commit `01a98c2` was pushed to `origin` and the secondary mirror under the
combined approval. Portainer rebuilt the stack and recreated ingest; the live
image reports `0.101.5` and is healthy. Operations remained healthy. The
post-deployment window contained zero ingest error-level lines, zero ingest
tracebacks, and zero Operations HTTP 500 responses.

The packaged operator was run without `--apply`, inside its explicit read-only
transaction. It changed zero current rows and closed zero history rows. Its
aggregate result is:

- active retired-scope records: 162;
- eligible records: 162;
- blocked records: 0 (zero shape, provenance, missing/current legacy device,
  withdrawal-boundary, and open-history blockers);
- already-corrected records: 0;
- approved-selection candidate digest:
  `b807231cbc7c5dc02af7ec0abed01ce6240a319863806a404d2c2834f2d593e3`.

**Next approval gate:** a separate production-data approval may authorize one
operator apply pinned to count 162 and digest
`b807231cbc7c5dc02af7ec0abed01ce6240a319863806a404d2c2834f2d593e3`.
If approved, run the atomic apply once; verify 162 current rows updated and 162
open history rows closed, a repeated pinned invocation is a verified no-op,
canonical devices/source links/daily rollups remain unchanged, and the shadow
views exclude the corrected retired scope. Derived presence/session/lifecycle
refresh and lifecycle-effect application remain separately controlled; reader
cutover also remains blocked by the recorded Inventory-refresh availability
item.

#### Retired-scope apply and projected derived effect

The separately approved operator apply ran once with exact count 162 and digest
`b807231cbc7c5dc02af7ec0abed01ce6240a319863806a404d2c2834f2d593e3`.
It updated exactly 162 current rows and closed exactly 162 open history rows.
The approved repeated invocation recognized all 162 as already corrected under
the same digest and wrote zero current/history rows.

Aggregate post-apply verification confirmed all 162 current rows are inactive,
all 162 carry the exact legacy `missing_since` withdrawal boundary, zero target
history intervals remain open, and 162 matching historical intervals close at
that boundary. The stable raw-record digest remained
`eb4abe0cf1d372cd15161e67803405ed`. All 154 canonical-device references, 154
source links covering 95 distinct canonical devices, and 1,739 target daily
rollup facts remain unchanged. Detail/health shadows remain 5,469/5,469, the
daily shadow remains 341,119, and no corrected retired identity appears in the
detail shadow. Both services are healthy with zero new ingest errors,
tracebacks, or Operations HTTP 500s. The failed first verification statement
was a read-only syntax error and rolled back without changing data.

The authorized read-only next-effect simulation compared the still-materialized
presence/session state with the active generic evidence after correction. For
the 95 linked canonical devices, the next presence refresh projects 325 rows
to 283: 42 stale rows removed, zero added, and 53 retained aggregate rows
updated. Seven devices have no remaining active presence evidence. Exactly 39
device-session rows change. Applying the deployed lifecycle selection and
aging policy to the projected presence produces an empty transition set: zero
lifecycle-status changes, zero reported-state conflicts, and zero unknown-
state findings for affected devices. Current affected lifecycle states are 60
active, 33 offline-aging, and two pending-cleanup, all unchanged by projection.

#### Controlled derived refresh checkpoint

The separately approved dependency-order calls to
`operations.refresh_device_agent_presence_current()` and
`operations.refresh_device_session_current()` completed in independent
transactions. Aggregate verification found 283 affected presence rows, down
from the measured 325-row baseline: the projected 42 stale rows are removed,
the projected 53 retained aggregates are refreshed, and seven of the 95
affected canonical devices have no remaining active presence. All 95 affected
devices retain a session row, with zero mismatches across the presence-derived
session fields; this confirms the projected 39 changed session rows were
published. The affected lifecycle-state distribution remains 60 active, 33
offline-aging, and two pending-cleanup. No lifecycle evaluator was run, and
zero `lifecycle.transition` audit events occurred after the session refresh.

The current presence definition, including migration `0098`'s exclusion of
device-health evidence, converged to the same 283 aggregate rows. A transient
single-row reported-online difference observed during verification disappeared
under the normal refresh cadence; a final aggregate check found zero presence-
to-session mismatches. Both containers remained healthy. The 15-minute
post-refresh window contained zero Operations HTTP 500 responses, zero
Gunicorn worker timeouts, and zero ingest error, exception, or traceback lines.

#### Availability design review (complete proposal)

The user approved this read-only design review on 2026-08-03. No refresh,
production write, code/schema change, migration, reader cutover, commit, push,
or deployment was performed. Aggregate-only production measurements through
the approved helper confirmed four coupled causes.

1. `ninja_inventory.refresh_current()` refreshes seven materialized views
   non-concurrently and sequentially in one transaction. This preserves atomic
   publication but takes reader-blocking locks until the entire chain commits.
   None of the seven views has a unique index, so PostgreSQL cannot use
   concurrent refresh. All seven current outputs have an aggregate-unique,
   non-null candidate key; their combined stored result is small (30,458 rows
   and approximately 36 MiB).
2. Migration `063` renamed the original live views, preserving their OID
   dependencies. Dependent `_live` views therefore continue to expand earlier
   live definitions instead of reading the newly materialized stages. The
   final eight-row summary has an estimated plan cost of 10.67 million because
   it recomputes much of the hierarchy. The seven current live plans total
   26.46 million estimated cost. Rebinding each dependent stage to the prior
   materialized stage reduces the estimated total to 4.53 million, an
   approximately 83% reduction before any source-query improvement.
3. The first stage still obtains 13,256 current rows from the 8.03 GiB,
   approximately 2.76-million-row legacy Agent Compliance observation table.
   Its wide `DISTINCT ON` sorts raw JSON. A bounded latest-ID-only measurement
   completed in 13.13 seconds but read 315,042 shared blocks and wrote 46,194
   temporary blocks; forcing the existing identity index exceeded the
   30-second read-only limit and was cancelled. The physical query must first
   select narrow latest observation IDs and only then fetch the 13,256 wide
   rows. Agent Compliance itself remains explicitly out of scope.
4. The Operations Software page independently groups the 1.46 GiB,
   approximately 467,000-row installation-current table on every request. Its
   central aggregate took 4.39 seconds while idle, read 147,685 shared blocks,
   and wrote 13,447 temporary blocks. Concurrent Inventory I/O pushed that
   request past Gunicorn's 60-second limit. The existing 20,559-row,
   5.38-MiB `v_software_safety` matview already carries the same fleet title
   counts, but its current refresh contract lags by two titles and 36 changed
   aggregates; it cannot silently replace the live query without a dependency-
   ordered freshness correction.

The run ledger also contains two full patch-module sequences beginning about
ten minutes apart in the incident window, plus 27 scoped software jobs.
`run_patching_once()` has no cross-entry single-flight guard: scheduler,
startup, and manual threads can each start it. The retained container logs do
not cover the pre-hotfix container, and `pg_stat_statements` is not installed,
so exact historical per-stage refresh duration and whether the two refresh
calls waited back-to-back cannot be recovered. The code and ledger prove the
duplicate-entry risk; the measured 8-minute-42-second second refresh and
resource-heavy plans prove the availability failure without that missing
detail.

The 612 legacy-only and 960 generic-only identities measured across the four
agent platforms are now an explicit generic-cutover classification set, not a
reason to preserve or optimize the legacy Inventory authority. The user
explicitly rejected further Metabase investment. Decision 0005 supersedes the
old split-surface destination in decision 0002: Operations is the destination,
and Metabase is retired by domain.

The repository consumer audit confirms that all direct consumers of
`ninja_inventory.v_*` are in `ingest/inventory/metabase_bootstrap.py`.
Operations has no direct dependency on those views. The only normal callers of
`ninja_inventory.refresh_current()` are the patch-ingest, Agent Compliance run,
and Agent Compliance evaluation paths. Therefore the seven legacy Inventory
materialized views will not receive new indexes, concurrent refresh, staging,
query rewrites, generation coordination, or other performance work.

##### Approved immediate Inventory retirement

The user explicitly retired all five Inventory Metabase dashboards on
2026-08-03 and waived them as parity gates. The bounded implementation is:

1. Stop provisioning Inventory dashboards during automatic or manually
   triggered Metabase bootstrap.
2. On bootstrap, idempotently archive the five known Inventory dashboards,
   their collection cards, and the Inventory collection. This is the only
   permitted Metabase mutation and exists solely to remove the legacy surface.
3. Remove the three normal calls to `ninja_inventory.refresh_current()` from
   patch ingest, Agent Compliance collection, and Agent Compliance evaluation.
4. Preserve the Inventory bootstrap source and all legacy database functions,
   materialized views, tables, grants, and data unchanged for rollback. Their
   physical cleanup remains a later, separately approved operational phase.
5. Continue generic Operations Source Records and serial evidence/data-quality
   work under decision 0010, but do not make either capability a prerequisite
   for this explicitly accepted retirement.

The implementation affects `ingest/main.py`, a bounded Inventory retirement
helper and test, `VERSION`, `CHANGELOG.md`, and the retirement documentation.
It adds no dependency, schema change, migration, or production-data write.

Independently protect native Operations availability in later implementation:
add a cross-process single-flight guard around the complete patch cycle, add
the compact `operations.software_title_current` read model, and refresh that
title model followed by safety/classifier derivatives once per software batch.
These solve current Operations behavior and are not Metabase improvements.

Agent Compliance remains untouched. Other Metabase domains follow as separate
retirement slices after their Operations capability is accepted or explicitly
retired; they receive no new feature or performance work.

##### Validation and acceptance

- Prove with focused tests that only the exact Inventory dashboards, cards,
  and collection are archived and that repeated retirement is a safe no-op.
- Compile changed Python, run focused ingest tests, and search every Python
  path to prove Inventory bootstrap and all normal refresh calls are detached.
- Build the ingest image and verify its imports/startup path. No migration is
  present in this release.
- After separately approved commit and push/automatic deployment, verify the
  five dashboards and Inventory collection are archived, no Inventory refresh
  executes during an accelerated full cycle, services remain healthy, and the
  post-change window contains zero HTTP 500s or worker timeouts.

All post-review checks found the database and three containers healthy, zero
waiting locks, zero Operations HTTP 500s or worker timeouts, and zero ingest
error/exception/traceback lines in the 30-minute window. The forced-index test
was read-only, hit its explicit 30-second statement timeout, and rolled back.

Local candidate `0.102.0` is implemented and reviewed. Two focused retirement
tests pass, including exact five-dashboard scoping, unrelated-content
preservation, card/collection archival, and the already-retired no-op. Changed
Python compiles and passes Ruff. Repository search confirms no Inventory
bootstrap import and no normal Inventory refresh caller; the sole remaining
`ninja_inventory.refresh_current()` Python reference is the deliberately
dormant rollback helper. `git diff --check` passes. The final ingest image
build passes, contains `0.102.0`, and imports the changed runtime with inert
placeholder settings. No SQL, migration, database data, or production service
was changed. A local Metabase runtime was not available, so actual API archival
and post-deployment HTTP/refresh behavior remain deployment validation.

Commit `45110f7` was pushed to `origin` and `a-m-rose`; both remote heads match.
Portainer deployed the image, and production reports `0.102.0`. Ingest,
Operations, Metabase, and PostgreSQL are healthy. Startup recorded exactly five
Inventory dashboards, 25 cards, and one collection archived. Independent
aggregate metadata verification found zero active and 5 archived dashboards,
zero active and 25 archived cards, and zero active and one archived collection.
The post-deployment window contains zero Inventory refresh executions, zero
ingest errors/tracebacks/exceptions, and zero Operations HTTP 500 or worker-
timeout matches. No manual full collection cycle was authorized or run.

The deployment procedure is also clarified by owner direction: after every
approved `origin` production push, invoke the configured private Portainer
redeploy mechanism immediately instead of waiting for repository polling. That
trigger is part of the push/deployment boundary; an unrelated standalone
redeploy remains separately gated.

**Next approval gate:** Inventory Metabase retirement is complete. No database
cleanup, Agent Compliance change, or other Metabase-domain retirement is
authorized by this checkpoint.

## Active implementation slice — Ninja generic cutover and native availability

**Status:** local candidate validated; release candidate `0.103.0` is approved
for commit and combined production/mirror push.

The user authorized this bounded slice on 2026-08-03. It does not authorize a
commit, push, deployment, production migration, production-data change, legacy
history cleanup, Agent Compliance redesign, or further Metabase investment.

### Goal and scope

- Make the already-deployed generic Ninja detail and health observations the
  authoritative current/raw writers; stop new hourly writes to the two legacy
  snapshot tables without deleting or rewriting historical rows.
- Repoint compatibility projections, Ninja presence, Operations session
  reboot/boot state, software last-user lookup, and the three remaining live
  Patching queries to generic current evidence or the compact daily rollup.
- Fail Ninja collection when its authoritative generic observation write
  fails; bounded legacy device rows remain a rollback/current compatibility
  copy, not the raw-history authority.
- Add a database advisory-lock single-flight guard around the complete patch
  cycle so scheduler, startup, and manual entry points cannot overlap.
- Add a compact, tenant-scoped `operations.software_title_current` materialized
  read model; refresh it and the software safety derivative once per completed
  software batch, and use it for Software overview fleet-wide aggregates.

### Affected files

- `ingest/core/devices.py`, `ingest/core/device_health.py`,
  `ingest/connectors/ninja_presence.py`, `ingest/main.py`, and software
  inventory queue/refresh paths.
- `sql/migrations/073_ninja_generic_reader_cutover.sql`.
- `operations/apps/core/migrations/0100_generic_ninja_and_software_read_models.py`
  and `operations/apps/core/views.py`.
- The three bounded Patching query definitions in
  `ingest/metabase_bootstrap.py`, focused tests, `VERSION`, and `CHANGELOG.md`.
- Root and Operations active plans plus the already-edited deployment
  procedure documentation.

### Implementation order and decisions

1. Recreate compatibility materialized views with their current public shapes,
   owners, grants, indexes, and downstream troubleshooting signal intact.
2. Recreate the Operations device session from the exact active Ninja detail
   observation contract and add the software title read model without changing
   canonical identity or tenant boundaries.
3. Cut writers and readers over only after the generic write succeeds; retain
   legacy tables and their data untouched for rollback.
4. Add and test patch-cycle single-flight and batch-scoped software read-model
   refresh ordering.
5. Bump `VERSION`/`CHANGELOG.md`, run migration and application validation in
   disposable PostgreSQL/Docker, review every changed hunk, and stop at the
   separate commit approval gate.

### Validation and acceptance

- PostgreSQL migrations apply in deployment order and preserve relation
  columns, indexes, owners, grants, tenant scoping, and current aggregate
  parity.
- Focused tests prove generic writes are mandatory, legacy snapshot inserts no
  longer occur, all direct production readers are cut over, and daily trend
  reads the compact rollup.
- Competing patch-cycle entry points prove one winner and a clean skip; lock
  release is proven on success and exception.
- Software overview queries avoid fleet-wide aggregation of the installation
  table, refresh ordering is once per successful batch, and focused request
  behavior remains correct.
- Changed Python compiles and passes Ruff/format checks, relevant ingest and
  Operations tests pass, Docker images build, and `git diff --check` passes.
- Deployment and production migration remain a later explicit push gate. After
  approval they require immediate Portainer invocation, migration/version and
  aggregate parity checks, an accelerated full cycle, service health checks,
  and a zero-HTTP-500/worker-timeout observation window.

**Current checkpoint:** Git and the deployed checkpoint were reconciled at
`45110f7` / `0.102.0`; the reviewed local candidate is `0.103.0`. Existing
unrelated plan/backlog/design/probe changes remain preserved. The candidate
stops legacy detail/health snapshot appends, makes generic observations
authoritative and fail-closed, moves the identified readers to generic current
or daily-rollup evidence, adds patch-cycle single-flight, and adds the compact
software-title read model.

Validation completed against the candidate:

- Both Docker images build. Ingest reports/imports `0.103.0`; the full ingest
  suite passed with 90 tests and 7 opt-in skips. Operations passed 27 tests
  with 2 opt-in skips, `manage.py check`, and migration-drift checks.
- Focused disposable-PostgreSQL tests passed for generic snapshot expansion,
  withdrawal, the Operations migration, and stable identity. Migrations 0100
  and 073 applied successfully in PostgreSQL 16; their projections, indexes,
  grants, concurrent refresh, advisory-lock release, writer fail-closed
  behavior, and an actual Software overview request were exercised. A request
  smoke exposed one `latest_install` alias defect; it was fixed, the image was
  rebuilt, and the request then passed without an HTTP 500.
- Production read-only aggregate preflight found 5,473 generic detail and
  5,473 generic health current records. The projected active-device count is
  4,020, equal to the current view; measured detail and health field mismatches
  are both zero. No customer rows were returned and no production write ran.
- The generic session projection deliberately changes 306 reboot flags and
  307 boot timestamps under the approved direct-agent precedence. Seventeen
  projected-missing records currently retain stale legacy reboot/boot evidence;
  all 17 lack a current Ninja device and will correctly lose that withdrawn
  evidence. The prior lifecycle simulation found zero lifecycle transitions.
- The historic root migration chain still has a pre-existing fresh-install
  failure at migration 041; the candidate migrations were therefore rehearsed
  from the supported predecessor state. The host lacks `httpx`, so applicable
  host PostgreSQL tests were run separately; image-based suites passed.

**Approval recorded:** the user explicitly approved commit and push on
2026-08-03. The approved release set excludes unrelated changes and probe
files. Push `origin`, immediately invoke the private Portainer redeploy, push
the identical commit to the secondary mirror, then verify migrations, version,
aggregate parity, an accelerated full cycle, service health, and HTTP 500s.
