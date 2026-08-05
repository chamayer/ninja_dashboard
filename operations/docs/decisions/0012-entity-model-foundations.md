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
- Tenant consistency applies only when the target is scoped. A composite
  foreign key under `MATCH SIMPLE` expresses this natively: a NULL tenant on
  the target stands the constraint down, while a plain foreign key still
  guarantees the row exists.

### 5. Software

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
