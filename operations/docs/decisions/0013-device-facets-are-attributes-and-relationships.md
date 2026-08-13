# 0013 — Device facets are attributes and relationships, not entities

Status: Accepted
Date: 2026-08-05
Accepted: 2026-08-05

## Context

ADR-0005 introduced `Asset`, `OSInstance` and `AgentInstance` as first-class
entities beneath `Device`. ADR-0006 then refined them from lifecycle-window
entities into attribute buckets. Both records treat the three as one kind of
thing.

They are not. Applying the ADR-0012 identity test — does this need an identity
of its own; can it exist detached, move between parents, be counted, or be
referenced by something else? — separates them cleanly:

- **Hardware** cannot. A hardware refresh produces a *new Device* by ADR-0005's
  own corroboration rule, so hardware never outlives or moves between devices,
  and nothing references a device's hardware independently.
- **An OS install** cannot. ADR-0006 already established it as one bucket per
  device mutating in place, with reimage recorded as field changes.
- **Agent presence** is inherently about a *pair*: one row per
  (Device, Agent product), carrying version and heartbeat. That is a
  relationship with attributes, not an entity.

Treating all three as entities produced concrete, measured problems:

- Form factor lives in both `devices.device_type` and `assets.form_factor`,
  with the *cache* upstream of the supposedly source-authoritative layer
  (`ingest/identity/resolver.py:1078+` copies Device → Asset). Both hold
  identical values; neither is meaningfully the fact.
- `v_device_current`, named a required deliverable by ADR-0005, was never
  built, so the flat Device columns stayed load-bearing.
- The word "asset" now denotes four different things: the `operations.assets`
  facet table, the `asset` entity class, the `cmdb.asset` entity type, and the
  `assets.asset_type` enum — whose `peripheral`, `license` and `service` values
  duplicate registered entity classes.
- The `asset` entity class has zero entities while 4,842 non-device CMDB
  records sit unanchored, because "asset" appeared to be taken.

## Options considered

- **Keep three layer entities, fix only the write direction.** Rejected: it
  preserves the conflation that produced the collisions, and leaves hardware
  modeled as an entity that can never have an independent identity.
- **Collapse all three into attributes.** Rejected: agent presence genuinely
  describes a pair, and flattening it onto the device loses which agent
  product a version belongs to.
- **Decompose by the ADR-0012 identity test.** Selected.

## Decision

### Hardware and OS are attributes of the device entity

Form factor, serial, vm_uuid, chassis, virtualization, os_name, os_family and
os_version are **attributes of the Device entity**, carried by the generic
claim and effective-value contract. Most already are: `serial_number`,
`vm_uuid`, `is_virtual_machine`, `node_class`, `os_name` and `os_family` are
existing attribute definitions.

### Agent presence is a relationship

Agent presence is a **relationship** between a Device entity and an agent
product from the `agents` catalog, carrying version, heartbeat and coverage
state as relationship attributes. The agent catalog is unscoped reference
data per ADR-0012.

Measured 2026-08-05, `operations.agent_instances` does **not** currently hold
those attributes: 12,828 rows across 4 agents, `agent_version` populated on
**zero** of them, and zero rows ever updated after insert. Its audit trigger is
enabled but has never fired, because the only field it watches is never
written. The substantive presence data lives in
`device_agent_presence_current`.

So `agent_instances` is today a near-empty (Device, Agent) membership record
duplicating a matview. That reinforces the structural conclusion — it is a pair,
not an entity — while showing the migration target is the relationship plus
attributes sourced from presence, not a repackaging of this table.

### Form factor is derived and owned by no table

No source states form factor. It is computed from asset-nature signals —
`network.device` / `vm.host` / `vm.guest` entity types, `node_class` markers,
and `is_virtual_machine` — with agent presence explicitly excluded. `unknown`
remains legitimate and positive evidence is required to leave it.

Because it is derived, it is not an attribute definition and must never be
recorded as a source claim: mapping `node_class` to a `form_factor` attribute
would record our interpretation as if the source had asserted it.

### The typed tables become compatibility projections

`operations.assets`, `operations.os_instances` and `operations.agent_instances`
hold the same status as `devices.os_name`: typed caches written **only** by the
shared projector, never by a producer. They are droppable once consumers move
to the effective contract or to `v_device_current`. **See the amendment below:
`v_device_current` is retracted, and the typed tables are no longer under
pressure to retire on its account.**

### The `asset` entity class means a top-level tracked thing

`asset` is reserved for things the MSP tracks that are not devices — the
unanchored CMDB records, peripherals, licenses. `operations.assets` is renamed
to `device_hardware` so the word stops denoting both a device facet and a
top-level class. `asset_type` values duplicating registered entity classes
(`peripheral`, `service`, `network_appliance`, `license`) are retired in favour
of those classes.

### What ADR-0005 keeps

Unchanged and still authoritative: Device as a thin, *learned* identity anchor;
no source authoritative for Device identity; hostname alone never merges;
contested corroboration surfaces a finding; `unknown` legitimate at every
layer; **agent presence is not evidence of form factor**; per-field history.
Field history moves to the attribute claim history that already exists, which
records source and reason — unlike `asset_field_history`, whose `change_reason`
is the constant `'trigger.audit'` and whose `change_source` is never written.

## Rationale

- The identity test is a single rule that produces the decomposition, rather
  than three special cases decided per table.
- It removes the ownership question entirely. Neither Device nor Asset owns
  form factor; the effective contract does, and both tables are caches with
  one writer.
- Measured today: `assets.form_factor` and `devices.device_type` have identical
  distributions and zero mismatches, because one is copied from the other.
  Nothing is lost by treating both as projections.
- It frees the `asset` class for the 4,842 records that currently have nowhere
  to go, without inverting `Device` or migrating anything structural.
- Agent-as-relationship is the first real use of relationship attributes,
  which ADR-0012 requires and the E4 engine already has the surrounding
  machinery for.

## Consequences

- **Projector writes both.** The device cache projector computes form factor
  once and writes `device_hardware.form_factor` and `devices.device_type`
  together, so the copy step in `resolver.py:1078+` is deleted rather than
  repointed.
- **Rename `operations.assets` → `device_hardware`**, with
  `asset_field_history` following. Mechanical but wide: resolver, models,
  migrations, triggers.
- ~~**`v_device_current` remains owed** — it is what finally allows the flat
  Device columns to be dropped.~~ **Retracted 2026-08-05, see the amendment
  below.** Nothing is owed and dropping the flat columns was never the intent.
- **Agent instances migrate to relationships.** Larger work; the typed table
  remains a projection until consumers move.
- **`asset_type` narrows** to hardware-descriptive values. Peripherals and
  licenses become entities of their own class.
- No migration is required to *start*: the projector and the rename can land
  independently, and the entity-class work is unblocked immediately.

## Supersedes or superseded by

Supersedes ADR-0005's decision to model `Asset`, `OSInstance` and
`AgentInstance` as entities, and supersedes ADR-0006 entirely — its
attribute-bucket refinement was correcting the lifecycle framing of a
decomposition that was itself wrong. ADR-0005 remains authoritative for the
learned identity anchor, the corroboration rule, and the never-infer rule for
form factor. Applies ADR-0012.

## Amendment — 2026-08-05: `v_device_current` retracted

This record originally listed `v_device_current` as still owed, on the grounds
that it "is what finally allows the flat Device columns to be dropped." Both
halves of that are wrong, and the evidence disproving them was available when
this record was written. It was not consulted.

**Nothing was ever owed to consumers.** `v_device_current` appears only in
ADR-0005 and in this record. It is absent from `CHANGELOG.md` and from all
code. It was never built, so it never had consumers, so there was no migration
to complete. `operations.v_device` is not its replacement — it *predates*
ADR-0005 and has been the device read surface throughout, serving the home
view, patching population, `os_group` counts and the device drilldown.

**Dropping the flat columns was never the intent.** Release 0.64.0 — the
release that created the layer entities under ADR-0005 — states it explicitly:
"The existing collapsed `v_device` surface is unchanged; flat `Device`
attribute columns stay as a denormalized cache." `v_device_current` was scoped
as an *additional* surface for consumers wanting layer detail, not as a
replacement for the cache.

**And dropping them would be a performance defect.** Measured against
production, 5,294 devices:

| read path | time |
| --- | --- |
| five cache columns from `operations.devices` | 5.5 ms |
| three of them pivoted from `entity_attribute_effective_current` | 383.6 ms |

Roughly 70x slower for fewer attributes, scanning 182,320 effective rows. This
is not an indexing gap — ten indexes already exist on that table, including on
`entity_id`. A fleet-wide pivot must touch every row, so the sequential scan is
the correct plan; an index only helps single-device lookups. Eight consumers
read those columns, four of them materialized views.

### Amended position

- **`v_device_current` is retracted as a deliverable.** ADR-0005's effective
  read surface is satisfied by `operations.v_device`.
- **The flat Device columns are permanent**, as a single-writer projection.
  ADR-0012 permits a cache; its requirement is one writer, which `7e57ba3`
  established. The defect was never that the cache existed — it was that nine
  producers wrote it.
- **The typed layer tables are no longer under pressure to retire** on
  `v_device_current`'s account. They stay as they are. Their real defect —
  `agent_instance_field_history` holding 0 rows against ~12,800
  `agent_instances` — is tracked in `.work/backlog.md` on its own merits.

### Why this is recorded rather than quietly edited

The original line was written on the same day as this amendment, from the two
ADRs alone, without reading the changelog entry for the release that executed
ADR-0005. That is the same failure this record was created to prevent: taking a
document's framing as the history rather than checking what was actually built
and decided. Leaving the retraction visible is more useful than a clean text.

## Amendment — 2026-08-06: what ADR-0010 phase E6 means by "compatibility columns"

ADR-0010's E6 phase line reads "retire competing attachment authority and
obsolete compatibility columns/readers." It was never enumerated, and two
records disagreed about the columns half.

**The conflict.** The design intent recorded during the E-track's design
sessions framed the flat `operations.devices` cache columns as transitional —
one projector as sole writer, "validating cache/projection equality *until the
compatibility columns are dropped*." The 2026-08-05 amendment above reached the
opposite conclusion, that the columns are permanent.

**Measurement settles it without appeal to either record.** Against production
2026-08-06, 5,298 live devices:

| column | devices with an effective-contract value |
| --- | --- |
| `os_family` | 5,244 |
| `device_role` | 4,721 |
| `os_name` | 4,720 |
| `os_group` | **0** |
| `device_type` | **0** |

`os_group` and `device_type` have no effective-contract representation at all.
The projector derives them — `os_group` from `os_family` via
`os_group_mappings`, `device_type` from entity type plus node_class. Dropping
the compatibility columns is therefore not achievable for two of the five
regardless of which record is preferred, because there is nothing to drop them
*to*. Building those contract sources is separate work and is not an E6 gate.

Two supporting measurements, both re-taken 2026-08-06 rather than carried
forward: where an effective value exists there are **zero** mismatches against
the flat column (578-580 devices per column have no effective value); and the
flat read costs 4.7 ms against 362.9 ms pivoted from the contract, consistent
with the ~70x recorded a day earlier.

### Ratified position

- **The flat Device columns stay.** The 2026-08-05 amendment stands, now on
  measured rather than argued grounds. The single-writer projector and its
  ratchet test are the permanent enforcement, not an interim step.
- **E6's "compatibility columns/readers" means the compatibility _tables_.**
  Concretely: `client_links`, `client_candidates`, `merge_candidates`,
  `source_bindings`, the three empty `ninja_*_shadow` views, the two `_legacy`
  matviews, and `client_user_links`. `device_links` was the first and is
  retired (ADR-0014); `client_links` is its exact twin at 320 rows against 320
  `client` rows in `entity_source_links`.
- **The columns question reopens only if** an effective-contract source is
  built for `os_group` and `device_type`. Until then it is not a decision, it
  is unavailable.
