# 0012 — Entity model foundations

Status: Accepted
Date: 2026-08-05
Accepted: 2026-08-05

## Context

ADR-0002, ADR-0005, ADR-0010 and ADR-0011 each apply the same underlying
principle to a different domain — identity, attributes, lifecycle — but the
principle itself was never written down. Each was authored after a violation
surfaced in that domain, so every new area rediscovers it, and any area nobody
revisited keeps its pre-principle behaviour indefinitely.

The cost is concrete and measurable:

- `INGEST_ACTIVITY_TYPES_INCLUDE` was configured, documented, and inert for two
  months because the filter parameter name was wrong and nothing verified it.
- `source_failure` and `software_queue_stalled` were registered as finding
  types and never emitted, while the conditions they describe were true.
- `_upsert` carries a reopen branch that cannot execute, because the conflict
  target excludes the rows it would reopen.
- `DESIGN.md` permitted source-derived attributes to be written directly by the
  resolver, justified on churn rate, and that exception outlived the constraint
  that produced it.

Every one of those is a rule with no enforcement mechanism. This record states
the rules once and requires each to name how it is enforced.

Terminology collisions made this worse. "Layer" means storage tier (ADR-0003),
attribute-bucket entity (ADR-0005), and evidence pipeline stage (ADR-0010).
"Canonical" means a table in one record and a pipeline stage in another.
`docs/glossary.md` is the companion to this record.

## Options considered

- **Leave the principle implicit.** Rejected: demonstrably produces
  per-domain rediscovery and silent drift.
- **State the principle in DESIGN.md.** Rejected: DESIGN.md is the detailed
  implementation authority and is itself one side of the conflict this record
  resolves.
- **State it as a decision record with named enforcement per rule.** Selected.

## Decision

### 1. Structure

An **entity** has an **anchor**: a stable identifier and a record that it
exists. Information about an entity is either:

- an **attribute** of that entity, or
- a **relationship** to another entity.

**A relationship may carry its own attributes.** An installation, an agent
presence, a patch state and a user assignment all describe the pair rather than
either endpoint, and there is no volume threshold that exempts them from this.
Where such data is currently held in a typed store, that is a migration to
schedule, not an exception to sanction.

A **facet** is a coherent group of information about an entity — hardware, OS,
agent coverage. A facet is stored as attributes or as a relationship. The word
"layer" is not used for this, or for anything else, without qualification.

Not everything is an entity. Sources, observations, claims, events and
operator decisions are mechanism, not things the platform tracks.

### 2. Sources are a learning mechanism

**A source assertion is evidence, never state.** Entities exist independently
of any source. A source going quiet means we stopped learning, not that the
fact stopped being true.

**No evidence producer may write state.** Connectors, resolvers, evaluators and
UI actions never write a source-derived value directly. One shared projector
copies selected values into any typed store. This holds regardless of how
rarely the value changes; low churn is a performance argument, not an ownership
argument.

Evidence arrives in two shapes, and neither is an entity:

- **state observations** — what is (content-hashed current plus history), and
- **events** — what happened (immutable, no current/history semantics).

Relay status is a property of the individual claim, not of the source. A source
is never a template selector, a dispatch key, or an architectural category.

### 3. Origin and scope are orthogonal to structure

Three independent axes. Conflating them produces false conflicts.

- **Structure** — entity, attribute, relationship.
- **Origin** — learned from a source, derived by us, or authored by an
  operator. A finding is an entity that was created rather than learned; a
  coverage requirement is attributes that were authored. Neither is
  structurally special.
- **Scope** — see below.

### 4. Ownership determines scope

An asset or wholly-owned entity is **scoped** — to a client, or to the tenant
where the MSP owns it. Anything not owned is **unscoped**: publishers, software
products, software versions, CVEs and CPEs belong to nobody and must not be
given a tenant.

Referential rules across the boundary:

- A scoped entity may reference an unscoped one. Nothing leaks, because the
  referenced row contains no owned information.
- **An unscoped entity must never reference a scoped one**, or it becomes a
  cross-tenant leak channel. This is validated at relationship-type
  registration.
- ~~Tenant consistency applies only when the target is scoped. A composite
  foreign key under `MATCH SIMPLE` expresses this natively: a NULL tenant on
  the target stands the constraint down, while a plain foreign key still
  guarantees the row exists.~~ **Wrong — see the 2026-08-10 amendment. This
  paragraph describes a mechanism PostgreSQL does not have, and building
  against it produces entities nothing can reference.**

### 5. Software

**Superseded by the 2026-08-10 amendment: the hierarchy below is retained, but
these are global reference entities beside `intel.cves`, not rows in
`operations.entities`. Software is not owned; a licence is.**

`publisher → product → software+version` are entities joined by plain
relationships. Software+version is the entity that CVEs, EOL dates and safety
scores bind to; it is unscoped. An installation is a relationship between a
device and a software+version, carrying install path and date.

### 6. Mappings live in data

Any rule that maps one domain value to another — an OS name to a family, a
node class to a form factor, a source record type to an entity class, which
vendors are first-party — is **operator-maintainable data**, not a constant in
code. A hardcoded domain mapping cannot be corrected without a deploy, is
invisible to the operator it affects, and drifts silently from its data-driven
siblings.

The reference shape already exists: `os_group_mappings` carries pattern,
value and priority with first-match-wins. The counter-example sits beside it —
`os_name → os_family` is hardcoded in `ingest/normalize.py` *and* duplicated in
SQL in migration 0023, while its coarser sibling is a table.

Exempt: function dispatch, regexes used for normalisation, endpoint and timeout
configuration, and fail-closed bootstrap fallbacks that are documented as such.

### 7. Out of scope

This record governs entities and the evidence about them. It does not govern
global reference corpora (`intel.cves`, `intel.cpes`), legacy stores pending
retirement, or the evidence machinery itself.

## Enforcement

A rule with no mechanism is a description. Each rule names one:

| Rule | Mechanism |
| --- | --- |
| No evidence producer writes state | Revoke `UPDATE` on projector-owned columns from ingest roles, so a direct write is impossible rather than merely discouraged |
| Sources never reach the model | Test asserting no source-name literal in shared modules; source record type → entity class as registry rows, never a Python constant |
| **No domain mapping lives in code** | A ratchet check over `ingest/` and `operations/apps/` fails on any module-level collection of domain values not listed in a reviewed inventory. Dispatch tables, regexes and config are exempt; anything that maps one domain value to another is not. Applies to new code including projectors — the rule caught a form-factor pattern set being reintroduced into SQL on 2026-08-05 |
| Nothing is lost without when and why | `NOT NULL` reason columns beside every withdrawal, clearing and expiry timestamp |
| Unscoped entities carry no tenant | `CHECK` constraint: unscoped implies `tenant_id` and `client_id` both NULL |
| Unscoped never references scoped | Validated on relationship-type registration |
| A facet declares how it is stored | Column on the entity-class registry; undeclared fails closed |
| Every registered threshold is evaluated | A registry row that cannot be measured raises an operator-visible finding, never a silent skip |

Where a rule cannot be assigned a mechanism, that is worth knowing before it is
written down.

## Rationale

- Three accepted records already assert this principle in their own domains;
  stating it once removes the rediscovery cost rather than adding a constraint.
- Enforcement-by-mechanism is proven here: after revoking observation-payload
  grants in 0.109.0, the restriction held without relying on reviewer memory.
- Separating origin and scope from structure resolves what looked like model
  failures — findings, policy and CVEs each fit once tested on the right axis.

## Consequences

- **DESIGN.md** — the clause permitting source-derived attributes on canonical
  with the resolver as writer is removed. Its storage-tier model is unaffected.
- **Unscoped entities need schema work**: nullable `entities.tenant_id`, a third
  `scope_kind`, and an RLS review. Required soon — software, publisher and
  product entities cannot be created correctly until it lands.
- **Typed device attribute columns** become projector-written or derived. The
  producer writes in `ingest/identity/resolver.py` and `ingest/evaluator.py`
  are removed, and facet propagation reads the effective contract rather than
  the cache it currently reads.
- **`operations.assets` collides with the `asset` entity class** — a hardware
  facet of a device versus a top-level class. A rename is owed; the two are not
  the same thing.
- **Asset-class entities are unblocked.** Records that are not devices need no
  typed table and no inversion of `Device`; they need an anchor of the right
  class, which the existing candidate workflow already produces.
- Existing typed stores for high-volume associations remain until migrated.
  They are scheduled work, not sanctioned exceptions.

## Supersedes or superseded by

States the principle underlying ADR-0002, ADR-0005, ADR-0006, ADR-0010 and
ADR-0011; supersedes none of them. Supersedes the `DESIGN.md` low-churn
exception for source-derived attributes on canonical tables.

## Amendment — 2026-08-12: software capability needs dedicated evidence authority

The 2026-08-10 software amendment described product attributes as arriving
from one intelligence path with nothing to arbitrate. Capability recognition
does not satisfy that premise: vetted identities, narrowly tested rules,
publisher evidence, community tags, and global curator confirmation have
different authority. ADR-0018 therefore defines a dedicated capability
evidence model beside the global software catalog. It does not adopt the
generic tenant-scoped entity machinery, and it preserves this record's rule
that a source assertion is evidence rather than state.

## Amendment — 2026-08-06: merging is not a universal entity operation

Making the entity model generic invites the assumption that every operation on
it generalises too. Merging does not, and the reason is a property of the
identity model rather than of the abstraction.

**Merge decomposes into three layers, and only the middle one generalises.**

*Detection* is class-specific and shares no predicate: devices duplicate on a
normalized hostname within a client, software titles on title plus publisher,
users on email. There is nothing to abstract.

*Review and decision* is genuinely generic — a proposal listing members, the
evidence and confidence behind it, a status, an operator decision, an audit
trail. `merge_candidates` carries `entity_type` and `canonical_key` for exactly
this. It is also the layer currently **not** unified: device merges live in
`operations.merge_candidates` while software merges live in
`ninja_inventory.v_merge_candidates_current`, a different schema with different
operator actions. One decision, two surfaces, neither authoritative.

*Execution* is class-specific and asymmetric. Merging two devices repoints
observations, findings and software rows. Merging two clients would repoint
**20+ referencing tables including `devices` itself**, so it cascades into
every device beneath the client. Nothing about those cascades is shared.

**Whether merge is needed at all depends on how identity is established.**

- **Learned** identities need it. The resolver mints devices from observations,
  so two records for one machine is a normal outcome — 38 open collisions
  measured 2026-08-06.
- **Accepted** identities largely do not. Track C forbids auto-minting clients:
  every new name becomes a candidate an operator must accept, and the
  candidate queue's *map* action attaches a differently-named source group to
  an existing client before a second client can exist. Measured 2026-08-06:
  **zero** duplicate clients across 76.

So `merge_candidates` being device-only in practice is a consequence, not an
oversight, and the generic `entity_type` column is correct rather than
aspirational — software belongs in it, clients rarely will.

### Position

- Generalise the **review contract**; keep detection and execution per class.
- Do not build merge for an entity class before a duplicate exists in it.
  Client merging is parked on this basis: the preventive workflow is working,
  and a remedial cascade across 20+ tables is the riskiest change in the schema
  to build against a hypothetical.
- Consolidating software merge proposals into `merge_candidates` is the
  outstanding item in this area, not client merging.

## Amendment — 2026-08-10: the `MATCH SIMPLE` mechanism for unscoped entities is wrong

Section 4 stated that a composite foreign key under `MATCH SIMPLE` expresses
"tenant consistency applies only when the target is scoped", because "a NULL
tenant on the target stands the constraint down."

**PostgreSQL has no such behaviour.** `MATCH SIMPLE` relaxes a constraint when
a **referencing** column is NULL. A NULL on the **referenced** side relaxes
nothing — it makes the target row unmatchable, because the referenced key
`(NULL, id)` cannot satisfy a lookup for `(1, id)`.

The direction was inverted, and the error is load-bearing: it is the only
mechanism section 4 offered for how scoped rows may point at unscoped ones,
and it is what made "nullable `entities.tenant_id`" look sufficient.

### What this costs, measured 2026-08-10

**29 composite foreign keys** reference `operations.entities(tenant_id, ...)`.
The relationship tables — precisely the ones ADR-0012 §5 requires for software
installations — are among them:

```sql
entity_relationships:
  FOREIGN KEY (tenant_id, target_entity_id)
  REFERENCES operations.entities(tenant_id, id)
```

A device → software+version installation carries a non-NULL `tenant_id` and a
non-NULL `target_entity_id`. Neither referencing column is NULL, so the
constraint is enforced in full and demands `(tenant, software_id)` in
`entities`. An unscoped software entity holds `(NULL, software_id)`. The
insert fails.

So making `tenant_id` nullable does not unblock software instantiation. It
creates entities that **nothing in the schema can reference** — the failure
appearing not at migration time, when every DDL statement succeeds, but at the
first relationship insert after deploy.

### Position

- **§4's referential mechanism is withdrawn.** The scope *rules* stand:
  ownership determines scope, unscoped entities carry no tenant, and an
  unscoped entity never references a scoped one. Only the claimed enforcement
  mechanism is wrong.
- **No unscoped-entity migration may be written until a replacement exists.**
  A nullable-tenant migration applies cleanly and passes every check, which is
  what makes this dangerous rather than merely incorrect.
- Options, none yet chosen: drop `tenant_id` from the composite FKs whose
  target may be unscoped (keeping a plain FK on `entity_id`, so existence is
  still guaranteed and tenant consistency is enforced where it applies); or
  hold unscoped entities in a separate relation; or keep them tenant-stamped
  and accept the duplication. Each has a different blast radius across the 29
  constraints and needs its own measurement.
- The enforcement-table row "Unscoped entities carry no tenant | `CHECK`
  constraint" remains correct as far as it goes. It constrains the entity row;
  it says nothing about whether anything can point at it.

### Why this is recorded rather than quietly corrected

The paragraph was written with the confidence of a checked fact and was never
checked. It survived because nothing had tried to build on it — the first
attempt to write the migration found it in one query. That is the same failure
mode this record exists to name: a rule stated without its mechanism verified.
Leaving the retraction visible is more useful than a clean text.

`asset` instantiation is unaffected: asset entities are client-scoped, so no
composite key involving them ever carries a NULL tenant.

## Amendment — 2026-08-10: software is foreign reference data, not an entity in `operations.entities`

Section 5 places `publisher → product → software+version` in the entity model
as unscoped entities. The amendment above showed the *mechanism* for that could
not work. This amendment addresses the more basic point: the placement itself
is wrong.

**Software is not owned.** A client owns a *licence*; it does not own Microsoft
Word. `operations.entities` is the store for owned things — clients, devices,
assets, users — and every structure on it assumes ownership: `tenant_id` NOT
NULL, `scope_kind` of `tenant` or `client`, forced RLS with a tenant policy,
and 29 composite foreign keys that carry a tenant. Putting an unowned thing in
that store means fighting all of it, which is exactly what the failed
`MATCH SIMPLE` mechanism was an attempt to do.

**The platform already has the right home, and this record already exempts
it.** Section 7 reads: "It does not govern global reference corpora
(`intel.cves`, `intel.cpes`)." That corpus exists — 92,514 CVEs and 164,860
CPEs — in its own schema, with no tenant, no RLS and no ownership semantics.
Software, publisher and product belong beside it. They are the same kind of
thing: globally true facts about the world that no customer owns.

### Amended position

- **`publisher`, `product` and `software+version` are global reference
  entities**, held with the intel corpus, carrying no tenant and no
  `scope_kind`. They are *not* rows in `operations.entities`.
- **The installation relationship already exists.**
  `operations.software_installations_current` holds 484,636 rows keyed by
  device and title strings. It does not need to be rebuilt as a generic
  relationship; it needs the title strings to gain an identity, i.e. a foreign
  key to software+version. §1's rule that a relationship may carry its own
  attributes is already satisfied — `install_location` and `install_date` are
  on those rows today.
- **A licence is a scoped asset** and belongs in `operations.entities` under
  the `asset` class when that work is scheduled. The licence-versus-product
  distinction is what makes one owned and the other not.
- **The generic attribute/claim/effective machinery does not apply to
  software**, and that is not a loss. That machinery exists to resolve
  disagreement between sources. Software attributes — EOL date, safety score,
  CVE linkage — come from one intel path, so authority selection, conflict
  rows and audited operator decisions would be overhead with nothing to
  arbitrate.
- **`entity_classes.software` and `entity_types.software` stay registered** and
  stay empty. Retiring them is a separate decision; nothing depends on them.

### Consequences

- The 29 composite foreign keys on `operations.entities` are **untouched**.
- **No nullable `tenant_id`, no third `scope_kind`, no RLS policy
  replacement.** The `.work/backlog.md` item "Unscoped (universal) entities —
  nullable tenant, third scope_kind" is retired as unnecessary rather than
  deferred: it existed to make software fit a store software does not belong
  in.
- ADR-0015's sequencing is unaffected. Its step 3 (findings onto real subjects)
  still needs software+version to have an identity; it now gets one from the
  reference schema instead of from `operations.entities`.
- Section 5 is superseded by this amendment. The hierarchy it describes is
  retained; only its location is changed.

### Why the first placement looked right

§4 divides the world into scoped and unscoped and then treats both as
inhabitants of the same store, which makes "unscoped entity" sound like a
variant of "entity" rather than a different kind of thing. §7 already drew the
real line — governed entities versus global reference corpora — but §5 was
written without applying it to software. The two sections disagreed and nothing
tested which governed until a migration had to be written.
