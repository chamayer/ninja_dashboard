# 0005 — Device is a learned identity anchor with layered entities

Status: Accepted
Date: 2026-07-19
Accepted: 2026-07-20 (v1 execution — collapsed matview stays as primary consumer surface; flat Device attribute columns retained as denormalized cache in v1)

## Context

The current `Device` canonical row mixes hardware/virtualization attributes
(form factor, serial, chassis), OS-install attributes (os_name, os_family,
version), and per-agent observations onto one entity. This conflation produced
concrete defects — for example, the form-factor inference bug where agent
presence alone can label a Device as `physical` — and blocks futures that
require asset-lifecycle, OS-instance-lifetime, or per-agent-install-lifetime
reasoning.

Two operator principles frame the correct model:

1. Reimaging or upgrading an agent (or reinstalling an OS on the same
   hardware) does not create a new device — same identity, new "flavor,"
   with prior flavors preserved as history.
2. Two agent observations that share a name but no corroborating identifier
   are a conflict, not a merge.

## Options considered

- **A. Flat Device with attribute columns.** Current shape. Conflates layers;
  form-factor class of bug is a symptom.
- **B. Combined Device with attribute layers (asset_*, os_*, agents_*) plus
  audit history.** Cleaner naming, but layer histories are timelines rather
  than queryable entities. Retroactive per-OSInstance or per-AgentInstance
  questions become archaeology.
- **C. Device as a learned identity anchor with layered entities.** Selected.

## Decision

The canonical model has four entity types:

1. **`Device`** — persistent operational identity anchor. Thin. Holds stable
   ID, tenant/client scope, operator-authored context that outlives any
   layer (labels, notes, exemptions, tags), and first_seen / last_seen
   across all sources. Owns no layer facts.
2. **`Asset`** — the hardware or virtual entity. Own lifecycle
   (provisioned → in-service → retired). Form factor, serial, vm_uuid,
   chassis, virtualization. Linked to Device with effective_from /
   effective_to windows. Source-authoritative for its layer.
3. **`OSInstance`** — an OS install on an Asset. Own lifecycle
   (imaged → active → reimaged/retired). os_name, os_family, os_version,
   patch state, config state. Linked to Device with effective windows.
   Source-authoritative for its layer.
4. **`AgentInstance`** — one row per (Device, agent product, install
   lifetime). Version, heartbeat, coverage state. Linked to Device with
   effective windows. Source-authoritative for its layer.

**Identity.** Device identity is *learned*, not seeded. No source is
authoritative for Device identity itself. A new observation extends an
existing Device only when a strong corroborating identifier (serial, UUID,
MAC, install token, per-source device_id) matches. Hostname alone never
merges. No corroboration → open a new Device. Contested corroboration →
surface an identity-conflict finding.

**Findings.** Evaluators are layer-scoped: they read layer-entity data.
Findings are attached to Device (operator triage surface) with a
back-reference to the layer entity they were derived from
(`source_layer`, `source_layer_entity_id`), so retroactive per-layer-entity
queries are native. Composite evaluators that legitimately span layers
(e.g., "Windows 11 requires TPM + BitLocker") are permitted and declare
their layer dependencies.

**"Unknown" is a legitimate value at every layer.** A layer entity may live
in `unknown` state until positive evidence arrives. Presence of an
observation in one layer is not evidence for another layer's attributes.

**History.** Two mechanisms:

- Lifecycle transitions (reimage, upgrade, hardware refresh) close the
  current layer entity's effective window and open a new one. Prior layer
  entities remain queryable.
- Within an active window, field-level changes are captured in a per-layer
  audit table.

**Continuity across hardware refresh** is not a Device-successor concern.
Hardware refresh produces a new Device via the corroboration rule; any
operator-level continuity flows through the shared link on a higher entity
(User, seat, role), not through Device-to-Device successorship.

**Presentation is not evaluation.** Finding evidence panels may enrich with
cross-layer context (asset, OS, agent) without violating layer scoping.

**Effective read surface.** A `v_device_current` view flattens Device with
its currently active Asset, OSInstance, and AgentInstance rows for UI and
dashboard consumers. Evaluators and history queries read the layer entities
directly.

## Rationale

- Layer entities with their own lifecycles enable retroactive
  per-OSInstance and per-AgentInstance queries as native operations, not
  timeline reconstructions.
- Structural separation of layers prevents the form-factor class of bug by
  construction — an evaluator reading `AgentInstance` literally cannot
  reach into `Asset` attributes.
- Learned identity with a corroboration rule aligns with the existing
  data-fidelity principles (never guess, mismatches become findings) and
  the durable-canonical-entities decision (0002).
- Extends the four-layer domain storage pattern (0003) from
  per-domain-state to per-layer-entity.

## Consequences

- **Migration.** Existing `Device` columns split into layer entity tables
  with backfilled `effective_from = first_seen`, `effective_to = null`.
  Existing findings gain `source_layer` fields as null; no retroactive
  back-references.
- **Evaluators.** Re-pointed to read from their layer's entity. Composite
  evaluators must declare layer dependencies.
- **Ingest resolver.** Emits three outcomes per observation: extend an
  existing layer entity, close/open a layer entity on transition, or
  surface an identity-conflict finding. OSInstance transitions rely on
  conservative continuity — same OSInstance until clear evidence forces a
  new one; missed reinstalls under-count OSInstance history rather than
  breaking.
- **RLS and tenancy** extend across four canonical tables using the
  existing tenant-scoped pattern.
- **UI and effective view.** `v_device_current` is a required deliverable
  so operator surfaces continue to render Device-centrically.
- **Exemptions and operator context** remain Device-scoped in storage;
  survival across layer transitions is determined per exemption type.

## Supersedes or superseded by

Extends 0002 (durable canonical entities) and 0003 (four-layer domain
storage). Does not supersede either.
