# PLAN-038 — Ninja device health as detail of the device record

**Status: defined.** Registered 2026-11-02 at the user's request ("it needs to
be changed"). Implementation needs the user's approval of the design below.

## Problem

`ingest/core/device_health.py` stores each Ninja device's health snapshot
(`/v2/queries/device-health`) as its own observation, namespace `device-health`,
key `device-health:<id>`, and copies the device's entity type onto it. Migration
0370 admits every observation as a source record and derives the record role from
the entity type, so every Ninja device appears as two source records, the second
typed as an agent (`agent.rmm` → `endpoint_agent`).

Production, read-only, 2026-11-02:

| Ninja records | `device` | `device-health` |
| --- | --- | --- |
| `endpoint_agent` | 5,104 | 5,026 |
| `virtual_machine` | 2,701 (+156 `vmware_guest_vmx_path`) | 3,383 |
| `virtual_host` | 103 | 101 |

No other source has a supplementary stream. The 8,513 health records have no
identity lookup keys and no open Issues; some pages filter them out by
`entity_key NOT LIKE 'device-health:%'`, others count or list them (the Sources
page double count in `operations/TODO.md`, 2026-10-22).

## The data model already has room for the values

No new table is needed for the values:

- All health fields are enabled `attribute_definitions` (`active_threats_count`,
  `alert_count`, `health_status`, `pending_reboot_reason`, the patch and
  vulnerability counts, `offline`, `parent_offline`,
  `product_installation_status`, …).
- The attribute projector already derives about 134,000 current claims from the
  health observations onto the Computer entity, attributed to the observation.
- `operations.ninja_device_health_current_shadow` (a view) serves the PLAN-033
  health readers.

The defect is only that the health observation is admitted, typed and shown as
a source record of its own.

## Design (user direction 2026-11-02: one record, health enriches it)

Values reach a Computer only as claims projected from a source record's
observation (ADR-0012; `entity_attribute_claim_current.observation_id` is a
foreign key), so "enrich the Computer" means the health fields become part of
the Ninja device record:

1. **The Ninja device collection fetches `/queries/device-health`** and writes each
   device's health fields into that device's own observation. The health claims
   are then attributed to the device record; no second record exists.
2. **Health joins the device record's material fields** (Ninja device material
   projection version 5), so health changes produce history the way the health
   stream does today. Confirm that identity comparison and source-record
   reassessment key only on identity fields, so health changes do not re-run them.
3. **A failed health fetch does not fail the device collection.** Decide whether
   the device record keeps the previous health values or marks health as not
   reported; it must not silently drop them.
4. **Retire the health stream:** remove the `device-health` writer from the hourly
   Ninja enrichment collection, withdraw its observations, and retire the 8,513
   health source records after a read-only check that none has a case,
   disposition, Issue or lookup key. Repoint `ninja_device_health_current_shadow`
   and the PLAN-033 readers at the device record, and remove the
   `device-health:%` page filters; the Sources page double count goes away.

Considered and rejected: writing the health fields into the device observation
from the separate hourly enrichment run. Two collections would then rewrite one
row, and each complete snapshot would erase or have to merge the other's fields.

Trade-off: health refreshes at the device collection's cadence instead of hourly,
and the device collection makes one more paged API call.

## Validation

Read-only production counts before and after (source records by namespace,
health claims, Issues); host tests for the admission change and the retirement
migration; check the PLAN-033 health readers and the Computer page still show
the values.

## Next action

User approval to implement; first read-only step: measure the device collection cadence and the health fetch time, and read the reassessment triggers for Step 2.
