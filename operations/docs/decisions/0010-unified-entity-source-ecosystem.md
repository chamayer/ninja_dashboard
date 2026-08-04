# 0010 — Unified entity and source-evidence ecosystem

Status: Accepted (engines and generic redacted read/admin implemented; audited
reveal implemented; named consumer cutover pending)
Date: 2026-07-31

The first additive Ninja ingest-storage slice shipped in release `0.101.0`:
distinct device/detail and health source records, deterministic raw hashes,
versioned material projections, material-change history, compact daily
presence, shadow compatibility views, and an operator-only resumable legacy
rollup backfill. Release candidate `0.103.0` promotes those generic records to
the Ninja current/raw authority, stops new legacy snapshot appends, and moves
the audited live consumers to generic compatibility projections. Historical
cleanup and the wider entity/claim ecosystem remain separate work.

Release `0.104.0` implements the first wider-ecosystem kernel: entity class and
scope registries, generic entity anchors for existing Clients and Devices,
generic source-link current/history, generic candidate/event foundations, and
an idempotent shadow projector from already-resolved observations. Typed
Client/Device records and compatibility links remain authoritative; this is an
expand phase, not the source-link cutover.

Release `0.105.0` implements the additive attribute-claim foundation:
deployment-controlled typed definitions and mappings, independent identity and
attribute authority policies, typed current claims with per-member SCD-2
history, restricted/count-only handling for unmapped fields, redacted evidence
views, and bounded projection/retention. Receipt and contact timestamps remain
on source current records and never create claim deltas. Existing typed readers
remain authoritative until the later effective-value and parity cutover.

## Context

Operations needs to represent an MSP tenant, its clients, and the entities it
manages: devices, users, peripherals, certificates, services, and future
classes. Multiple external sources may describe the same entity. Some sources
are authoritative, while others provide second-hand evidence that must remain
visible without automatically becoming an accepted asset.

The existing system has useful pieces—canonical clients/devices, observations,
source instances, class-specific links, and typed device layers—but new sources
have repeatedly required edits to hardcoded source/type lists. The earlier
proposal addressed identity and links but did not completely specify client
ownership, attribute-level provenance and authority, effective-value
selection, generic health/read models, or automatic admin behavior.

A production sizing report supplied on 2026-07-31 also shows that poll-driven
raw history is already material operating cost. It reports
`ninja_core.device_snapshots` at 7.55 million rows / 13.39 GiB and about
126,000 rows per day, and `ninja_core.device_health_snapshots` at 7.09 million
rows / 6.87 GiB and about 125,000 rows per day. Together they occupy about
20.26 GiB and are estimated to grow about 353 MiB per day. Both currently
append a full raw JSON payload for each device on every hourly collection even
when meaningful state is unchanged. These supplied aggregates are the design
baseline and must be independently remeasured through the authorized
aggregate-only sizing gate before physical storage is finalized. Agent
Compliance is also large but is intentionally outside this decision's storage
work.

The architecture must separate three coordinated concerns:

1. Database structure: the durable entity, evidence, claim, relationship, and
   read contracts.
2. Ingest: connectors translate vendor data; shared code applies platform
   semantics.
3. Admin and other consumers: generic discovery and evidence presentation,
   with typed class extensions where useful.

## Options considered

- **Continue class- and source-specific pipelines.** Rejected because every
  source creates an unbounded search for code branches and inconsistent rules.
- **Flatten every entity and canonical attribute into JSONB.** Rejected because
  canonical semantics, validation, indexing, constraints, and migrations would
  become implicit. JSONB remains appropriate for raw payloads and explicitly
  structured source detail.
- **One universal entity table containing every class field.** Rejected because
  unrelated classes do not share identity, lifecycle, or validation semantics.
- **Thin generic kernel with typed canonical classes and generic evidence.**
  Selected.

## Decision

### Entity topology and client ownership

`operations.entities` is a thin canonical anchor containing durable ID,
tenant, entity class, actual scope (`tenant` or `client`), optional client
owner, common audit fields, and deletion/retirement markers that are truly
common. Class-specific lifecycle remains on typed class records.

Allowed scopes are data-driven through an `entity_class_scopes` registry.
`entities(entity_class, scope_kind)` has a composite foreign key to that
registry. A check constraint requires `client_id` exactly when
`scope_kind = 'client'`, and the client reference is tenant-safe. This permits
new classes without adding class names to a check constraint.

- A Client canonical record is tenant-scoped and has a one-to-one entity
  anchor.
- Client-managed devices, users, and peripherals are client-scoped.
- An explicitly MSP-wide service may be tenant-scoped only if its class allows
  that scope.
- Existing `clients.id` and `devices.id` stay unchanged. Their typed tables
  gain nullable unique `entity_id` during expansion, are backfilled, and become
  required only after cutover.
- ADR-0005 `Asset`, `OSInstance`, and `AgentInstance` remain typed Device-layer
  concepts. This record does not repurpose or flatten them.

A peripheral is an entity in its own right. Parent attachment is a typed
entity relationship, not an attribute or nested canonical JSON document.

### Four distinct data layers

The following layers are never collapsed:

1. **Raw source record:** current raw vendor payload and collection provenance.
2. **Normalized claim:** a source's typed attribute or relationship assertion.
3. **Canonical/effective state:** durable entity identity plus rebuildable
   selected values derived under policy.
4. **Operator decision:** audited human override, acceptance, rejection,
   attachment, merge, or split that survives source refresh.

Source disappearance withdraws current evidence and closes history. It never
deletes a canonical entity or operator decision.

### Semantic registries and independent capabilities

Deployment-controlled registries define entity classes, allowed scopes,
entity types, attributes, relationship types, source defaults, and source-
instance overrides. The application and ingest roles receive read access;
runtime editing requires a later audited design.

`entity_types` contains separate capabilities:

| Consumer | Capability |
| --- | --- |
| Lifecycle evidence | `lifecycle_evidence_mode` |
| License/billing and duplicate licensed records | `consumes_license` |
| Coverage targeting | `requirement_eligible` |
| Resolver participation | `is_identity_signal` plus identity policy |
| Client/device/other dispatch | `entity_class` |

No capability may proxy for another. Classification resolves by exact
source-instance override, then source default, then `unknown` plus a finding.
Classification never grants authority by itself.

`lifecycle_evidence_mode` is the single normalized lifecycle capability. Its
allowed values are `none`, `direct_contact`, `reported_state`, and
`direct_then_reported_state`; the non-null database default is deny-by-default
`none`. A new or unknown type therefore cannot influence lifecycle until a
deployment-controlled policy explicitly classifies it. Direct agent contact is
higher-fidelity evidence of guest-OS liveness. Hypervisor-reported VM power
state remains authoritative for the power dimension and may provide
lower-fidelity lifecycle evidence. A fresh powered-on/online state may support
an active projection; a fresh powered-off, suspended, or offline state is valid
known-not-running evidence and must not project active. Collection time without
a qualifying contact or explicit state is not lifecycle evidence. The newest
qualified evidence wins, with direct contact winning only on an exact timestamp
tie. Unknown states produce no transition and a visible data-quality finding;
conflicting signals remain visible and lifecycle selection does not discard the
losing claim.

### Independent authority policies

Authority is explicit and deny-by-default.

- Identity policy distinguishes `may_establish_identity` from
  `may_create_canonical`, keyed by tenant, source instance, native record type,
  and resulting entity type.
- Attribute policy is additionally keyed by attribute definition and assigns
  an authority tier/priority. Unconfigured attributes are retained as visible
  evidence but cannot alter effective or typed canonical values.
- Relationship policy is keyed by source/native/resulting type and relationship
  type. Unconfigured relationships remain observed-only.
- Lifecycle contact, license use, and coverage remain entity-type capabilities,
  not consequences of identity or attribute authority.

Second-hand sources therefore remain fully observable while defaulting to
candidate-only or evidence-only behavior. An embedded relay to an authoritative
record resolves only by exact existing source-link lookup; it does not transfer
authority to the surrounding weak record.

An authority downgrade affects future matching and selection. It may raise a
finding about an existing attachment, but never automatically splits, merges,
detaches, or deletes a durable canonical entity.

### Source records and generic links

Connectors emit source-native `SourceRecord` objects containing:

- stable external namespace, ID, and optional parent identity;
- mutable native record type;
- raw payload and normalized identity evidence;
- normalized attribute claims;
- relays and relationship claims; and
- source timestamps and schema version; and
- a versioned material projection that deliberately excludes collection,
  heartbeat, and other non-semantic noise.

The shared pipeline adds Operations classification; connectors do not assign
canonical class directly.

`entity_source_links` associates one canonical entity with one stable source
identity from ADR-0009. It stores match method/confidence, first/last seen,
missing state, and nullable last transport binding. Tenant and entity class are
enforced through composite foreign keys.

`entity_source_links` is the **sole current authority** for canonical
attachment. An attached observation resolves to it by the complete stable
source identity; observation current/history do not own an independently
mutable canonical entity foreign key after contract. Existing observation
`device_id` / `client_id` columns remain compatibility projections during
migration and are removed only after all readers cut over.

`entity_source_link_history` is SCD-2 history for attachment, reattachment,
merge, and split decisions. It records the stable source identity, canonical
entity, method, confidence, deciding actor/process, reason/evidence, and
effective interval. Changing the current link closes the prior interval and
opens another in the same transaction. Historical observation reads resolve
the link interval effective at the observation time.

Unresolved, rejected, or ambiguous observations have no current source link;
they remain source evidence and may have a candidate. No second attachment
column is allowed to become a competing authority.

### Raw evidence current/history and reporting rollups

The generic observation store is change-driven, not poll-driven. For each
complete ADR-0009 stable source identity it keeps exactly one current raw
record. Every successful collection updates that row's latest raw payload,
collection/source timestamps, run provenance, `raw_hash`, and
`material_hash`, even when the material state is unchanged.

`raw_hash` covers a deterministic representation of the complete source
payload and is used for exact payload provenance and change detection.
`material_hash` covers a versioned, deliberately selected projection of
meaningful source state. Poll time, collector receipt time, heartbeat-only
fields, request metadata, and other declared volatile noise are excluded.
Hash algorithm and projection versions are stored so a projection change is
an explicit migration rather than a false source change. The deployed
Operations observation material-projection pattern is the implementation
starting point.

History stores the initial material version and is appended afterward only
when the material hash changes, the material-projection contract version
changes, or current evidence is withdrawn. A projection-contract boundary is
identified by its stored version and must not be interpreted as a source state
change merely because the version changed; it keeps current and open history
on the same contract even when their material hashes are equal. A complete
snapshot that no longer contains the source identity closes its open history
interval and records the withdrawal; reappearance opens a new interval. A
raw-only hash change updates current provenance but does not append another
full raw history copy. Partial or failed collections withdraw nothing.

Source-native lifecycle events are retained as immutable generic source-event
evidence keyed to the complete stable source identity. The event contract
preserves the vendor event ID, source event type and timestamp, source actor
identifier and supplied actor display metadata, source/client scope, outcome,
and a reference to the permitted raw event. Actor names and email addresses
are customer-sensitive: they are access-controlled and must not be copied into
finding text, aggregate validation output, or application logs.

An explicit source deletion event is higher-fidelity withdrawal evidence than
the later complete collection that first observes the record missing. When its
identity and ordering validate, it closes source evidence at the event time
with reason `source_deleted`; the later missing poll remains corroborating
evidence. An absent, malformed, conflicting, or out-of-order event cannot
weaken complete-snapshot reconciliation and instead produces an idempotent
finding where policy requires review.

Source deletion never deletes or retires the canonical entity and is not an
Operations decommissioning approval. It may automatically confirm the
source-removal step of a future decommissioning workflow. That workflow keeps
its operator approval, actor, reason, and state transitions in the generic
Operations audit stream and references the immutable source event, so the
source actor and the Operations decision actor remain distinct.

Long-term reporting reads compact, typed daily rollups rather than hourly raw
payload copies. Rollups record only the daily facts needed by approved
consumers, retain their source namespace and date grain, and are reproducible
from accepted current/change/run evidence. Raw JSON is not copied into a daily
rollup.

Physical current, history, and rollup tables are not final until an authorized
aggregate-only sizing exercise measures 30/90/365-day row, index, WAL, and
storage projections plus material-change frequency. Those measurements decide
retention and whether/how history and rollups are partitioned.

Ninja's `/devices-detailed` and `/device-health` records use distinct logical
source-record namespaces under the same Ninja source instance. The shared
external device ID may link both records to one canonical device, but neither
endpoint may overwrite the other's current raw payload, hashes, timestamps, or
withdrawal state. Agent Compliance storage and behavior are explicitly outside
this decision's ingest-storage migration.

Ninja device normalization keeps guest/host operating-system boot time and the
top-level hypervisor-reported boot measurement as distinct claims. Direct
`os.lastBootTime` is normalized as `last_boot_time_at` for OS session and reboot
consumers. The top-level VM value is retained as
`hypervisor_reported_boot_time_at`; it never overwrites the OS value.
Hypervisor `power_state` remains a separate, valid power-dimension measurement
under ADR-0011's evidence hierarchy.

### Attribute claims and effective values

`attribute_definitions` declares entity class, stable key, value type,
cardinality (`single` or `set`), sensitivity, validation, canonical-projection
eligibility, single-value conflict policy, and set merge policy. Definitions
are versioned deployment-controlled data.

Normalized current/history claim rows reference their observation and an
attribute definition. Claims use typed value columns (text, number, Boolean,
timestamp, entity reference) with a constraint allowing exactly the value
matching the definition's type. Each scalar or set member is one claim row,
identified by a normalized value fingerprint, so provenance and withdrawal
are per value. JSONB is permitted only for raw payloads and definitions
explicitly marked as structured detail; it is not the canonical attribute
store.

Claim no-op detection reuses the source record's versioned `material_hash` plus
attachment and claim-contract metadata; it does not re-hash full JSON at every
collection boundary. A deployment-controlled mapping that deliberately reads a
raw field is valid only when that field participates in the connector's
material projection. Adding such a mapping therefore requires the associated
material/claim contract version update.

Operator attribute decisions are separate audited rows. Single-value decisions
support replace/clear; set decisions support replace/add/remove. A rebuildable
`entity_attribute_effective_current` projection is the **sole authority for
selected source-derived values** and selects in this order:

1. explicit active operator decision;
2. eligible authoritative source claim;
3. eligible lower-tier claim.

For a single-valued attribute, conflicting equal-authority claims do not
silently overwrite one another: all claims stay visible, a finding is raised,
and the definition's required conflict policy is either
`retain_last_uncontested` or `unknown`. Source recency is not a hidden
tie-breaker.

For a set-valued attribute, the default policy selects the highest eligible
authority tier containing claims and unions distinct members within that tier.
A definition may explicitly choose `all_eligible_union`. Operator replace sets
the base set; operator add/remove then applies per member. Every effective
member retains all supporting claim references, and withdrawal removes only
the withdrawing source's support.

Frequently queried fields remain typed through class-specific derived tables
or effective views. The effective projection owns selection; a single shared
projector is the only writer allowed to copy selected values into typed
compatibility/cache columns. Connectors, resolvers, and UI actions never write
those cached source-derived fields directly. Consumers read effective views,
and cache/projection equality is validated until obsolete compatibility
columns are removed. Operator-owned canonical fields remain on their typed
canonical/decision tables and are not claim projections.

### Relationships and peripherals

Observed relationships preserve complete source-native endpoint identities
and may exist before either endpoint resolves. Incomplete external references
store exactly what the source supplied and a resolution state; missing
namespace, instance, or parent scope is never invented.

Canonical `entity_relationships` enforce registered source/target classes,
direction, and cardinality. A separate `entity_relationship_evidence` table
allows multiple observations and sources to support one canonical edge. An
edge remains while policy permits and supporting evidence remains; withdrawal
of one source does not erase corroboration from another.

`entity_relationship_decisions` stores an audited operator `include` or
`exclude` decision against the typed canonical endpoint tuple. `exclude`
suppresses the effective edge while preserving observed evidence; `include`
keeps the effective edge even without source evidence. In the absence of an
operator decision, eligible relationship evidence determines the edge.

### Candidate and operator-decision lifecycle

Every learned record reaches one of three explicit states:

- attached to an accepted canonical entity;
- awaiting review as a candidate; or
- observed-only because it is weak, unknown, rejected, incomplete, or
  ambiguous.

`entity_candidates` is the current generic review state keyed to the complete
stable source identity and proposed entity class/client scope. It records
status, current material hash, proposed/resolved entity, confidence, and latest
decision metadata. `entity_candidate_events` is the append-only audit of
create, attach, reject, reopen, merge, and split actions, including actor,
reason, before/after state, and affected evidence.

Accept/create or attach writes the authoritative `entity_source_links` row and
its history. Merge and split move source-link authority through the same
history path. Reject leaves source evidence intact and suppresses the same
candidate material hash; materially changed evidence may reopen the candidate
with a new event. There is at most one open candidate for a stable source
identity and proposed class.

### Generic read models and admin behavior

Shared read models expose entity summary, client ownership, source identities,
current/withdrawn evidence, normalized claims, conflicts, effective values,
candidates, and relationships. Typed effective views such as `v_device`
extend these for domain-specific behavior.

Source health is keyed by tenant and source instance. Entity counts are rows
grouped by class/type rather than fixed `device_count` columns. A source that
reports users or a future class therefore appears without a schema or template
change.

After connector deployment and registry seeding, the admin surface must
automatically show:

- source instance health, runs, errors, completeness, and per-type counts;
- source evidence and identities on entity pages;
- observed-only records and candidates;
- attribute claims, conflicts, effective values, and selection reasons; and
- relationships/peripherals and their supporting sources.

Basic visibility is registry-driven. Source-specific templates or source-name
branches are prohibited. Typed class panels may extend the generic entity
shell. Deployment-controlled registries are visible read-only.

APIs, CSV exports, evaluators, findings, notifications, and reporting readers
use the same effective contracts and do not independently implement source
precedence.

### Security and materialized views

Every tenant-owned table carries `tenant_id`, RLS, and tenant-consistent
composite foreign keys with matching unique targets. Global registries are
read-only to application and ingest roles. Tenant-scoped mappings and policies
use RLS.

PostgreSQL materialized views cannot enforce RLS. Tenant-bearing matviews keep
tenant keys, but no application or reporting runtime role receives direct
`SELECT`. They are owned by the migration role and refreshed only through
reviewed `SECURITY DEFINER` functions with a fixed `search_path`. Runtime reads
use `security_barrier` wrapper views owned by a dedicated view-owner role with
no `BYPASSRLS`, no login, and only the required underlying `SELECT` grants.
Every wrapper applies an explicit `tenant_id = operations.current_tenant_id()`
predicate and joins the appropriate tenant authority (`entities`, `clients`,
or `source_instances`) as defense in depth. The wrappers are intentionally not
`security_invoker`: that option would require the runtime caller to hold
underlying matview privileges and defeat the no-direct-access boundary. Grants
target only the wrappers, and privilege tests prove direct matview reads fail
for application, ingest, read-only, and reporting roles.

`operations.current_tenant_id()` is a new load-bearing SQL function, not the
existing Python helper with the same conceptual job. It is created before any
wrapper that references it, reads
`current_setting('operations.tenant_id', true)`, and returns a validated
positive tenant ID. Missing, empty, malformed, or non-positive context raises
a permission-style database error; it never returns NULL or silently produces
an empty result. The function is `STABLE`, is not `SECURITY DEFINER`, uses a
fixed `search_path`, revokes the default `PUBLIC` execute privilege, and grants
execute only to the roles that read tenant wrappers. Migration ordering and
rollback keep the function until its final dependent wrapper is removed.

Attribute sensitivity is enforced, not merely labeled. Definitions use
`public`, `internal`, `sensitive`, or `restricted`; unknown/unmapped fields
inherit the source manifest's default and default to `restricted` if none is
declared. Application roles do not receive unrestricted direct reads of raw
payload or claim tables. Generic views never silently hide the existence of
restricted evidence: they expose redacted placeholders and withheld counts,
source, and collection status without revealing protected keys or values.
Authorized operators receive a permission-checked, tenant-scoped, audited
route to inspect and classify the fields. Generic exports may include redacted
counts but exclude sensitive/restricted values. Findings may report that
classification is required and how many fields are withheld, but claim/raw
values may not enter exports, application logs, findings text, or measurement
output.

Device presence, session, patching, and software matviews remain typed because
their semantics are device-specific. Common source health and entity/claim
read models are generic. Refresh dependencies and concurrent-refresh indexes
are explicit.

### Migration and compatibility

All schema transitions use expand, backfill, shadow/dual operation, comparison,
consumer cutover, then separately approved contract work.

Before the physical attribute-claim schema is approved for implementation, an
authorized aggregate-only measurement must estimate records by source/type,
attributes per record (median, p95, maximum), material-change frequency, and
retained current/history volume. It must project claim rows, indexes, write
amplification, WAL, and storage at 30/90/365 days without exposing attribute
values or customer data. The result determines indexes, partitioning if
justified, retention, and refresh strategy. Claim-table scale is an early
schema input, not a late performance discovery.

- Existing canonical IDs and foreign keys remain stable.
- Existing raw/current/history evidence is retained.
- Every legacy link/observation is accounted for as migrated or explicitly
  deferred with a finding.
- Shadow failures do not block the authoritative legacy write before
  promotion.
- Compatibility views/readers remain until every named consumer is verified.
- Destructive cleanup requires separate approval, backup, restore rehearsal,
  and a tested rollback point.

During the Ninja connector cutover, both `/devices-detailed` and
`/device-health` move through the common current/change-history/rollup contract.
Compatibility projections preserve the latest offline/contact, reboot,
maintenance, boot-time, device-health, patch, and troubleshooting signals.
Operations session state continues to receive reboot and boot-time data, and
the daily active-device trend moves to the compact daily rollup. Legacy Ninja
snapshot deletion, archival, and disk reclamation are prohibited in the
generic deployment; they are a separately approved operational phase after
every named consumer has passed cutover verification.

The compatibility projections keep their established public relation names and
column shapes but read only exact active Ninja source-instance, namespace,
snapshot-scope, and material-projection contracts. The device session selects
direct RMM evidence before another Ninja record linked to the same canonical
device on an exact observation-time tie. Collection fails the affected source
module if its authoritative generic write fails; it never resumes legacy raw
appends as an implicit fallback.

### Implemented effective-value projection contract

The effective-value engine uses a durable dirty-key queue keyed by tenant,
entity, and attribute definition. Claim projection enqueues a key only when a
claim is inserted, changed, or withdrawn; an operator decision transaction
enqueues the same key. The effective projector therefore recomputes bounded
changed groups and an empty queue is an immediate no-op rather than a scan of
all current claims.

Operator decision headers and typed set members remain separate from source
claims. Database constraints enforce entity class, definition type,
cardinality, tenant, and set-operation compatibility. Database triggers append
redacted decision metadata to the existing generic `audit_log` and enqueue the
affected key in the same transaction, so this feature does not create a second
audit mechanism.

Effective scalar/set rows, supporting-claim references, and equal-authority
conflicts are rebuildable projections. The initial release exposes a redacted
tenant-scoped read model but leaves typed consumers authoritative until their
separately measured cutover.

### Implemented relationship, candidate, and source-event contract

Relationship types and source authority are deployment-controlled. Current
relationship evidence retains both complete source-native endpoint references,
including unresolved or partially resolved endpoints. Exact source-link
resolution is the only automatic attachment path. Change-driven SCD-2 history
retains material and presence intervals without writing heartbeat copies. A
durable changed-edge queue feeds one deterministic effective projector; audited
operator include/exclude decisions take precedence, and selected source
evidence retains support rows.

The generic candidate projector considers the complete stable source identity
and proposed entity class. It creates review state only for unattached current
evidence, reopens a rejection only when the material hash changes, and marks a
candidate attached when the authoritative source link exists. Operator attach
and reject services write candidate events and the existing generic audit log;
typed compatibility workflows remain until the generic E5 surface passes
parity.

Generic source events are immutable and idempotent by tenant, source instance,
and vendor event ID. Raw event and source-actor evidence is restricted from the
application role. A deletion event may withdraw current evidence only when it
supplies an exact stable subject ID and is not older than current source
evidence. It closes the matching open history interval and marks the source
link missing while retaining the canonical entity.

The aggregate production measurement preceding this contract found 228
retained Ninja `NODE_DELETED` events. All contained a source actor ID, none
contained a stable device ID, and the nested event object contained only a
message. Message or hostname parsing is not accepted as identity evidence.
Historical generic-event backfill remains a separately controlled operation;
if performed, these events remain unresolved. Future events automatically
confirm withdrawal only if Ninja supplies a stable subject ID; otherwise they
remain available for review and future decommissioning workflow evidence.

### Implemented generic read/admin slice

E5.1 adds security-barrier, tenant-filtered read models for entity summary,
source identities, redacted conflicts/effective values, relationships,
candidates, and source-instance/type health. The views are owned by a
dedicated no-login, non-BYPASSRLS role and granted only to Operations and its
read-only role. The Operations Admin entity list/detail and candidate workflow
are registry/class driven and reuse the existing atomic E4 decision services.
The Sources page now renders row-based entity-class/type counts instead of
fixed client/device columns.

E5.2 adds a default-denied restricted-evidence permission and POST-only reveal
functions for current observation payloads and claim/effective values. The
database verifies active operator, tenant, and permission and appends a
metadata-only event to the existing `audit_log` before returning a protected
value. Reveal responses are private/non-cacheable and are not exportable.

Ordinary Device identity GET requests no longer load raw payloads. Legacy
client-candidate and device-merge predicates now use a tenant-filtered
metadata view, allowing direct observation payload reads to be revoked while
preserving the approved write workflows. Direct application/read-only access
to protected effective/conflict projection tables is also revoked; redacted
views remain the default read contract. E5.3 performs the remaining named
API/export/evaluator/finding/notification/typed-reader cutovers.

## Rationale

- The generic kernel captures what sources and entity classes truly share
  without pretending their canonical semantics are identical.
- Claim-level provenance makes second-hand evidence useful without allowing it
  to silently control canonical state.
- Typed canonical storage preserves validation and query performance.
- Registry-driven health and admin reads make source extensibility observable,
  not merely ingest-compatible.
- Additive migration can fit the model onto existing data without changing
  current client/device identities.

## Consequences

**Easier**

- A new source for existing entity classes requires one connector, manifest,
  and registry/mapping data rather than shared platform branches.
- Multiple sources can corroborate or disagree without losing evidence.
- Peripherals and other child concepts use the same entity/relationship model.
- Operators can see why an effective value or canonical attachment exists.

**Harder or required**

- A genuinely new canonical class still needs an approved typed extension and,
  when its identity semantics differ, a resolver strategy.
- Attribute definitions and authority policies must be curated as part of
  source integration.
- Generic claim/history tables require the pre-schema aggregate measurement,
  then representative scale tests against the resulting physical design.
- Generic raw evidence must maintain versioned material projections and daily
  rollups; connector authors must distinguish semantic state from poll noise.
- Existing consumers require an audited, staged cutover.

**Prohibited**

- Treating every observation as an automatically accepted entity.
- A universal source trust score standing in for independent authorities.
- Canonical attribute JSONB bags as a substitute for typed domain models.
- Hardcoded source membership in shared Python, SQL, templates, or navigation.
- Appending a full raw source payload merely because another poll completed.
- Combining distinct source-record namespaces in a way that overwrites either
  endpoint's provenance.
- Deleting canonical entities or operator decisions because a source stops
  reporting them.

## Supersedes or superseded by

Depends on accepted ADR-0009. It does not block the independent lifecycle-
contact correction or ADR-0009's observation-identity correction. Extends
ADR-0001, ADR-0002, and ADR-0003. Preserves ADR-0005 and ADR-0006 typed
Device-layer semantics.

This record supersedes class-specific source-link infrastructure as the target
architecture. Legacy links remain compatibility authorities until the migration
plan's read cutover and contract phases are separately approved and completed.
