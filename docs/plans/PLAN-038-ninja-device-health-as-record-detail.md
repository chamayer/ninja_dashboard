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

## The data model already has room

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

## Design (proposed)

Keep the health observation as evidence storage — its history, claims and
reconciliation stay as they are — and make it a supplement of the Ninja device
record instead of a record:

1. **Mark the stream as supplementary in admin-managed data**, not code: a stream
   setting that says namespace `device-health` of the Ninja source supplements
   namespace `device` (same `external_id`). Read the existing source/namespace
   registries before choosing where it lives.
2. **Admission skips supplementary streams.** `source_record_admit_observation`
   does not create a subject for them; a migration retires the existing 8,513
   health subjects after a read-only check that none has a case, disposition,
   Issue or lookup key.
3. **Show health on the device record.** The source-record and Computer pages
   show the supplement's values as detail of the Ninja device record; counts
   (Sources page, source-record totals) count records only, which removes the
   `device-health:%` filters.
4. **The entity type copy stays only as claim context** or is dropped if no
   reader needs it; decide after reading the claim mappings.

Rejected: merging the health fields into the device observation's
`canonical_data`. The device and health collections are separate complete
snapshots with their own reconciliation; each run would erase or have to
merge the other's fields.

## Validation

Read-only production counts before and after (source records by namespace,
health claims, Issues); host tests for the admission change and the retirement
migration; check the PLAN-033 health readers and the Computer page still show
the values.

## Next action

User approval of the design, then read the namespace registries for Step 1.
