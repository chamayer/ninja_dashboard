# PLAN-038 — Ninja device health as detail of the device record

**Status: active — released in 0.141.0 (migration 0397); production
verification after deploy.** Registered 2026-11-02 at the user's request; the
user approved implementing and completing it the same day. Decision:
[ADR-0051](../../operations/docs/decisions/0051-companion-data-sets-of-a-source-record.md).

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

## Design (user decisions 2026-11-02)

Health is a companion data set of the Ninja device record: it has no life of its
own but is linked to the device record (ADR-0051).

- **Never a record:** the admission trigger skips companion streams
  (admin-managed `source_record_companion_streams`; Ninja `device-health`, owner
  key `ninja_node_id`). No link of its own; `device_id` stays empty.
- **Attached:** `attach_source_record_companions` (called by the health writer in
  its transaction) records the owner in `source_record_companions`. The writer
  stores health only for a device whose record is present.
- **Lifecycle:** an active companion needs a present owner at commit
  (`check_companion_owner`); withdrawing the owner withdraws its companions and
  closes their history (`withdraw_companions_with_owner`). History ages out under
  the existing 90-day retention; the long-term trail is PLAN-019 Step 4.
- **Values:** the claim projector attributes companion claims through the owner's
  link; a field the owner reports itself (`offline`) is claimed from the owner
  only. Records without an owner keep their projection hash.
- **Readers:** the source-record page of a Ninja device shows its device health;
  the Sources page counts records only (`v_source_instance_record_counts`). The
  existing `device-health:%` filters stay; they are now redundant, not needed.
- Rejected: merging health into the device collection or the device row (ADR-0051).

## One-time cleanup (migration 0397)

Attach all health observations to their owners (all 5,611 active ones have a
present owner); end the 7,330 health links through `set_source_association`
(link history closed and kept); remove the 8,513 health source records with their
132,368 derived assessments and 8,513 queue rows. Backup before release:
`~/backups/plan038-20261102T150553Z` on the host (CSV with SHA256SUMS).

## Validation

- Schema-only clone of production on the host (roles, schema, configuration
  tables; synthetic rows), migration run as `operations_migrate`, writer steps as
  `ninja_ingest` under RLS. All checks passed: health records removed and links
  ended with history kept; each health attached to its device record; ordinary
  records keep their projection hash; mismatched health now feeds its device's
  Computer; `offline` only from the device record and device claims unchanged;
  new health not admitted; health withdrawn with its device and history closed;
  orphan health refused; Sources counts records only.
- The clone caught one defect before release: a NULL owner made the field filter
  NULL and would have withdrawn every source's claims; fixed with `COALESCE`.
- Local: `test_migration_0397.py` (4) and `test_device_health.py` (5) pass; ruff
  clean on changed files; the source-record template renders.

## Next action

After deploy: read-only production check (0 health records and links, 5,611
companions, health claims re-projected, `offline` conflicts gone), then mark
complete.
