"""Migration 0051 — layered entities backfill (ADR-0005 slice 1b).

Populates open-window `Asset` and `OSInstance` rows from current
`Device` state so the layer tables have a starting point that mirrors
what consumers see today via `operations.v_device`.

**v1 backfill scope:**

- One `assets` row per non-deleted Device. `form_factor` copied from
  `devices.device_type` (same choices). `serial`, `vm_uuid` copied from
  the corresponding canonical Device columns. `effective_from` and
  `first_seen_at` = `devices.created_at`; `last_seen_at` =
  `devices.updated_at`; `effective_to` = NULL (open window).
- One `os_instances` row per non-deleted Device **when os_name is
  non-empty OR device_type is in ('physical', 'vm')**. Pure
  `network-device` / `hypervisor-host` Devices don't get an OSInstance
  row — no OS-install evidence. `os_name`, `os_family`, `os_group`
  copied from `devices`. `effective_from` = `devices.created_at`;
  `effective_to` = NULL.
- **No `agent_instances` backfill.** The ingest resolver rewrite in
  slice 2 (0.65.0) is the authoritative writer for AgentInstance and
  will populate rows as observations arrive. Backfilling from
  `device_agent_presence_current` would fabricate `first_seen_at`
  timestamps we don't reliably know.
- **No field-history backfill.** Audit tables start empty.
- **No findings back-reference backfill.** Existing findings retain
  `subject_layer=''` and `subject_layer_entity_id=NULL`; only findings
  produced under the new resolver carry back-references.

**Idempotency:** the migration checks for an existing open-window row
per Device per layer before inserting. Re-running is a no-op.

**Tenant scoping:** all inserts carry the source Device's tenant_id.
No cross-tenant reads.
"""

from __future__ import annotations

import uuid

from django.db import connection, migrations


def backfill_layer_entities(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with connection.cursor() as cur:
        # ── Asset backfill ──────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO operations.assets (
                id, tenant_id, version, asset_type, device_id,
                form_factor, serial, vm_uuid, chassis, virtualization,
                effective_from, effective_to, first_seen_at, last_seen_at,
                first_observed_source_id, last_observed_source_id,
                created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                d.tenant_id,
                1,
                'endpoint_hardware',
                d.id,
                d.device_type,
                COALESCE(d.canonical_serial, ''),
                COALESCE(d.canonical_vm_uuid, ''),
                '',
                '{}'::jsonb,
                d.created_at,
                NULL,
                d.created_at,
                d.updated_at,
                NULL,
                NULL,
                NOW(),
                NOW()
            FROM operations.devices d
            WHERE d.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM operations.assets a
                  WHERE a.tenant_id = d.tenant_id
                    AND a.device_id = d.id
                    AND a.asset_type = 'endpoint_hardware'
                    AND a.effective_to IS NULL
              );
            """
        )
        asset_count = cur.rowcount
        print(f"[0051] backfilled {asset_count} open-window assets rows")

        # ── OSInstance backfill ─────────────────────────────────────
        # Only for Devices with an OS install signal — os_name present,
        # or form factor is physical/vm (typical OS-carrying kinds).
        # Pure network-device / hypervisor-host get no OSInstance.
        cur.execute(
            """
            INSERT INTO operations.os_instances (
                id, tenant_id, version, device_id, os_name, os_family,
                os_group, os_version, install_identifier, patch_state,
                config_state, effective_from, effective_to,
                first_seen_at, last_seen_at,
                first_observed_source_id, last_observed_source_id,
                created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                d.tenant_id,
                1,
                d.id,
                COALESCE(d.os_name, ''),
                COALESCE(d.os_family, ''),
                COALESCE(d.os_group, 'Unknown'),
                '',
                '',
                '{}'::jsonb,
                '{}'::jsonb,
                d.created_at,
                NULL,
                d.created_at,
                d.updated_at,
                NULL,
                NULL,
                NOW(),
                NOW()
            FROM operations.devices d
            WHERE d.deleted_at IS NULL
              AND (
                  COALESCE(d.os_name, '') <> ''
                  OR d.device_type IN ('physical', 'vm')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM operations.os_instances o
                  WHERE o.tenant_id = d.tenant_id
                    AND o.device_id = d.id
                    AND o.effective_to IS NULL
              );
            """
        )
        os_count = cur.rowcount
        print(f"[0051] backfilled {os_count} open-window os_instances rows")


def unbackfill_layer_entities(apps, schema_editor):
    """Reverse: delete every open-window row. Safe because the layer
    entities are additive and consumers still read flat Device columns
    in v1."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM operations.os_instances WHERE effective_to IS NULL"
        )
        os_removed = cur.rowcount
        cur.execute(
            "DELETE FROM operations.assets "
            "WHERE effective_to IS NULL "
            "  AND asset_type = 'endpoint_hardware'"
        )
        asset_removed = cur.rowcount
        print(
            f"[0051 reverse] removed {os_removed} os_instances, "
            f"{asset_removed} assets"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0050_layered_entities_schema"),
    ]

    operations = [
        migrations.RunPython(backfill_layer_entities, unbackfill_layer_entities),
    ]
