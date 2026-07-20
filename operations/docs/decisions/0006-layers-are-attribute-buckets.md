## 0006 — Layer entities are attribute buckets, not lifecycle-window entities

Status: Accepted
Date: 2026-07-20

## Context

ADR-0005 established `Asset`, `OSInstance`, and `AgentInstance` as
first-class layer entities beneath `Device`, framed with
`effective_from` / `effective_to` windows suggesting per-install /
per-reimage / per-refresh lifecycle transitions. The v1 schema and
resolver code shipped that shape.

In practice:

- Hardware refresh already produces a new `Device` via the identity
  corroboration rule (ADR-0005). No Asset lifecycle-boundary needed.
- OS reimage on the same hardware is "same Device, new flavor" — the
  OSInstance's fields mutate; no bucket split.
- Agent reinstall resumes reporting the same attribute stream — the
  AgentInstance bucket doesn't split; the DeviceLink's external_id
  changes silently underneath.
- The operational questions operators actually ask (current coverage,
  historical trends, forensics windows) all resolve to
  `current value` + `value-change timeline` per (Device, layer,
  significant field). Install-lifetime boundaries aren't part of the
  question.

The install-lifetime framing was solving a problem the platform
doesn't have.

## Decision

Layer entities are **attribute buckets** combined with a Device to
form a picture — one row per (Device, layer key), long-lived,
mutating in place. Not lifecycle-window entities.

- `Asset` — one bucket per Device for `asset_type='endpoint_hardware'`.
  Currently one open bucket per Device (partial unique index).
- `OSInstance` — one bucket per Device.
- `AgentInstance` — one bucket per (Device, Agent product).

Lifecycle transitions (reimage, reinstall, refresh) are **not**
represented as close-old / open-new operations on layer entities.
They are either (a) resolved higher up as a new Device (hardware
refresh) or (b) recorded as field-value mutations plus audit-trail
entries on the same bucket (OS reimage, agent reinstall).

`effective_from` degrades to "first observed on this Device." It
retains its column for compatibility and for the edge case in
`effective_to`.

`effective_to` remains as a rarely-used escape hatch — permanent
retirement of a layer bucket where the layer itself is no longer
applicable to the Device. It is not a lifecycle mechanism for
reinstalls, reimages, or refreshes. Expected to remain NULL for
almost every row in practice.

Per-layer history lives in the existing significant-field audit
tables (`asset_field_history`, `os_instance_field_history`,
`agent_instance_field_history`), which the next slice will wire up
so that meaningful field transitions on the current bucket are
recorded. Trends and forensics query the audit timeline, not
window boundaries.

## Rationale

- Matches the actual operational questions: no consumer asks
  "was there a gap between agent installs on this endpoint?" —
  they ask "was the agent healthy on this date," which is a
  current-value-at-time-D question resolvable via field audit.
- Removes the "install_token" placeholder path in the resolver
  that no source populates.
- Removes an entire class of transition-detection code that would
  have needed careful design (when is a DeviceLink stale enough to
  count as a reinstall?) for no operational payoff.
- Preserves the ADR-0005 win — layers still have their own
  attributes, their own audit trails, their own evaluator scoping,
  their own retroactive queryability. Only the window-splitting
  behavior is removed.
- Matches the code that already shipped — the resolver never wrote
  close-open transitions in v1; it only created and updated in
  place.

## Consequences

- Backlog item "AgentInstance install-lifetime detection" is
  retired; replaced by "activate significant-field audit trails."
- ADR-0005 language about "effective windows" and "layer transitions"
  is superseded in the specific sense above. Multi-open-bucket
  scenarios (multiple concurrent Assets or OSInstances per Device)
  are explicitly not represented.
- Schema stays as-is. `effective_to` columns and CHECK constraints
  remain but are documented as escape-hatch. Partial unique indexes
  keying off `effective_to IS NULL` still work — they just enforce
  the one-bucket-per-device rule in the common case.
- The `install_token` column on AgentInstance is documented as
  unused-in-current-pipeline. Removal is optional cleanup.
- Presentation: no user-facing "install history" surface is planned.
  Operator questions about historical agent behavior go through the
  audit timeline.

## Supersedes or superseded by

Clarifies and partially supersedes ADR-0005 §Decision (specifically
the "effective windows" and "layer transitions" language). ADR-0005
remains the authority for the identity anchor + layered entities
model overall.
