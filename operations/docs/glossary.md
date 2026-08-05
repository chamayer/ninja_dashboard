# Glossary

Shared vocabulary for the Operations platform. Referenced from `DESIGN.md` and
the decision records. Where a word has meant several things historically, the
collision is recorded rather than quietly resolved — the ambiguity itself has
cost real time.

See ADR-0012 for the model these terms describe.

## Structure

**Entity** — something the platform tracks: a client, a device, an asset, a
user, a software product. Exists independently of any source.

**Anchor** — an entity's stable identifier plus the record that it exists.
Learned once; never removed because a source went quiet.

**Attribute** — a value belonging to one entity (a serial, a hostname).

**Relationship** — a link between two entities. **A relationship may carry its
own attributes**: an installation holds a path and a date belonging to the
device-and-software pair, not to either endpoint. There is no volume threshold
that exempts an association from being a relationship.

**Facet** — a coherent group of information about an entity: hardware, OS,
agent coverage. Stored either as attributes or as a relationship — **a facet is
not itself an entity unless it needs an identity of its own**. Per ADR-0013:
hardware and OS are attributes of the device; agent coverage is a relationship
to an agent product. Historically called a "layer entity" (ADR-0005) and an
"attribute bucket" (ADR-0006); both framings are superseded.

**Identity test** — does this need an identity of its own? Can it exist
detached from its parent, move between parents, be counted, or be referenced by
something else? If no, it is attributes. If it describes a pair, it is a
relationship. If yes, it is an entity. This is the rule that decides how a
facet is stored.

## Evidence

**Source** — a mechanism for learning about entities. Never an owner, never a
template selector, never an architectural category.

**Evidence** — anything learned. Arrives in two shapes:
- **state observation** — what *is*; content-hashed current plus history.
- **event** — what *happened*; immutable, no current/history semantics.

**Claim** — one source's typed assertion about one attribute. A unit of
evidence, with its own provenance, authority and lifetime.

**Effective value** — current belief for an attribute, selected from claims
under authority policy. The sole authority for selected source-derived values.

**State** — what we believe now, derived from evidence. **No evidence producer
writes state.**

## Components

**Projector** — derives one store from another. Four defining properties:
deterministic, **rebuildable** (drop the output and regenerate it), the **sole
writer** of the store it owns, and incremental (driven by a dirty-key queue,
recomputing only what changed). Rebuildability is what earns a projector the
right to be the only writer of state. Examples: the claim projection
(source records → claims), the effective projector (claims + operator
decisions → effective values), the candidate and relationship projectors.

**Connector** — fetches from an external source and writes evidence. Never
writes state.

**Resolver** — makes identity decisions. Its output is *learned*, not derived,
and therefore not rebuildable — which is why identity anchors are written once
and never recomputed.

**Evaluator** — derives assessments (findings). Projector-like, but its output
carries operator state (acknowledged, snoozed), so it is not freely
rebuildable.

**Refresh function** — recomputes a matview wholesale. A projector recomputes
by changed key; the distinction matters at fleet scale.

**Relay** — whether a specific claim reached us directly or via another
platform. A property of the claim, not of the source: a single source can
deliver both.

## Axes

Three independent axes. Conflating them produces false conflicts.

**Structure** — entity / attribute / relationship.

**Origin** — how a fact came to exist: **learned** from a source, **derived**
by us (a finding), or **authored** by an operator (a coverage requirement).
Origin does not change structure: a finding is an entity that was created
rather than learned.

**Scope** — see below. Note: "provenance" is deliberately avoided here. It has
meant origin, relay path, and an availability flag in different places.

## Scope

**Scoped** — owned, and therefore tenant- or client-bound. Assets, devices,
users, peripherals, clients.

**Unscoped** — owned by nobody: publishers, software products, software
versions, CVEs, CPEs. Carries no tenant. Not the same as tenant-scoped.

A scoped entity may reference an unscoped one. An **unscoped entity must never
reference a scoped one**.

## Known collisions

**"Layer"** — three meanings, all live. Qualify it or avoid it:
- ADR-0003 / DESIGN.md: a **storage tier** (canonical, derived matview,
  operator decisions, effective view).
- ADR-0005: a **facet** entity (`Asset`, `OSInstance`, `AgentInstance`) —
  superseded by ADR-0013; these are attributes and a relationship, and the
  tables remain only as projections.
- ADR-0010: an **evidence pipeline stage** (raw record, claim, canonical/
  effective, operator decision).

**"Canonical"** — a *table* in DESIGN.md (`operations.devices`); a *pipeline
stage* in ADR-0010. `devices.os_name` is canonical under one and a cache under
the other.

**"Effective"** — `v_<entity>` COALESCE-ing an override over a matview in
DESIGN.md; `entity_attribute_effective_current`, policy-selected from claims,
in ADR-0010. Same purpose, unrelated mechanisms.

**"Asset"** — `operations.assets` is a hardware **facet** of a device;
`asset` in `entity_classes` is a top-level **entity class**. Different things,
same word. A rename is owed.

**"Authority"** — *source authority* (which source wins for a value) versus
*write authority* (which component may write a store). Both are real; name
which one you mean.

**"Type"** — three registries, all legitimate:
- `entity_class` — device, client, asset, user… drives scope rules.
- `entity_type` — `agent.rmm`, `cmdb.asset`… a **capability** registry
  carrying `is_identity_signal`, `consumes_license`, `requirement_eligible`.
  The name is the misleading one; it is not a taxonomy.
- `asset_type` — endpoint_hardware, peripheral, license… the ITAM sense.
