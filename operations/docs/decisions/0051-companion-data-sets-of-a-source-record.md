# 0051 — Companion data sets belong to a source record

Status: Accepted
Date: 2026-11-02

## Context

A source can return more than one data set about the same item from different
endpoints. Ninja's device health (`/v2/queries/device-health`) is collected
separately from the device list and was stored as its own observation. Since
0370 every observation was admitted as a source record, so each Ninja device had
a second record, typed like the device and linked to a Computer by itself
(8,513 records, 7,330 links; 38 linked to a different Computer than their
device; 72 `offline` conflicts between the two, all timing differences).

## Options considered

- Keep the second record and hide it in readers (status quo filters).
- Fetch health in the device collection and merge it into the device record:
  couples a fragile collection and puts constantly changing counts on the
  identity record.
- Merge it into the device record from the separate health run: two complete
  snapshots would rewrite one row and erase each other's fields.
- A companion data set attached to the device record (selected).

## Decision

The user decided (2026-11-02): a companion data set has no life of its own but
is linked to its owner record.

- Companion streams are admin-managed data (`source_record_companion_streams`:
  source, namespace, owner key field).
- A companion is never admitted as a source record and never linked on its own;
  it is attached to its owner (`source_record_companions`).
- It keeps its own collection and timestamps. An active companion needs a present
  owner at commit; withdrawing the owner withdraws its companions.
- Its attribute claims are attributed through the owner's link. A field the owner
  record reports itself comes from the owner only.

## Rationale

One record per item matches what a source record is. Health keeps its own
collection cadence, cannot feed a different Computer than its device, and cannot
conflict with its own device record.

## Consequences

- Enforced by `check_companion_owner`, `withdraw_companions_with_owner`, the
  admission rule and the projector join (migration 0397), not by readers.
- Another source with a supplementary endpoint registers a stream instead of
  adding reader filters.
- The ADR-0045 change trail sees one record per Ninja device.

## Supersedes or superseded by

Refines 0370 admission (PLAN-004). Related: ADR-0012, ADR-0045, PLAN-038.
