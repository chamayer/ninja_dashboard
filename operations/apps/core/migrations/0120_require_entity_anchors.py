"""Migration 0120 — Client and Device entity anchors become required (E6).

ADR-0005 makes Device a learned identity anchor and ADR-0010 anchors every
canonical entity in `operations.entities`. Until now `clients.entity_id` and
`devices.entity_id` were nullable, because the anchors were created *after the
fact* by `operations.sync_entity_source_links_from_observations()`, which runs
in a later transaction than device promotion. Every freshly promoted device
therefore carried a NULL anchor for part of a cycle.

The resolver now creates the anchor inline (`_create_device_anchor`), reusing
the device UUID exactly as migration 0101's backfill does, so the write path
can satisfy a NOT NULL constraint.

Measured against production immediately before writing this: 5,293 devices and
76 clients, **zero** NULL `entity_id` on either. No backfill is required. The
guard below is deliberately not a no-op -- it fails loudly rather than letting
`SET NOT NULL` raise an opaque constraint error, and it re-runs the same anchor
creation the sync function performs so a stale environment can still migrate.

Deployment order matters: the resolver change must ship with or before this
migration. Both are in the same commit for that reason.
"""

from typing import ClassVar

from django.db import migrations, models

_ANCHOR_BACKFILL_SQL = """
DO $$
DECLARE
    missing_clients integer;
    missing_devices integer;
BEGIN
    -- Anchors reuse the client/device UUID. A row sharing an id across both
    -- tables would make that ambiguous; migration 0101 guards the same case.
    IF EXISTS (
        SELECT 1 FROM operations.clients c
        JOIN operations.devices d ON d.id = c.id
    ) THEN
        RAISE EXCEPTION 'Client/device UUID collision prevents anchor requirement';
    END IF;

    INSERT INTO operations.entities
        (id, tenant_id, entity_class_id, scope_kind, client_id, version,
         created_at, created_reason, updated_at, updated_reason,
         retired_at, retired_reason, deleted_at, deleted_reason)
    SELECT c.id, c.tenant_id, 'client', 'tenant', NULL, 1,
           c.created_at, 'system.anchor_requirement', c.updated_at,
           'system.anchor_requirement', NULL, '', c.deleted_at, c.deleted_reason
      FROM operations.clients c
     WHERE c.entity_id IS NULL
    ON CONFLICT (id) DO NOTHING;

    UPDATE operations.clients c
       SET entity_id = e.id
      FROM operations.entities e
     WHERE c.entity_id IS NULL AND e.id = c.id
       AND e.tenant_id = c.tenant_id AND e.entity_class_id = 'client';

    INSERT INTO operations.entities
        (id, tenant_id, entity_class_id, scope_kind, client_id, version,
         created_at, created_reason, updated_at, updated_reason,
         retired_at, retired_reason, deleted_at, deleted_reason)
    SELECT d.id, d.tenant_id, 'device', 'client', d.client_id, 1,
           d.created_at, 'system.anchor_requirement', d.updated_at,
           'system.anchor_requirement',
           CASE WHEN d.lifecycle_status = 'retired' THEN d.updated_at END,
           CASE WHEN d.lifecycle_status = 'retired'
                THEN 'system.anchor_requirement' ELSE '' END,
           d.deleted_at, d.deleted_reason
      FROM operations.devices d
     WHERE d.entity_id IS NULL
    ON CONFLICT (id) DO NOTHING;

    UPDATE operations.devices d
       SET entity_id = e.id
      FROM operations.entities e
     WHERE d.entity_id IS NULL AND e.id = d.id
       AND e.tenant_id = d.tenant_id AND e.entity_class_id = 'device';

    SELECT count(*) INTO missing_clients
      FROM operations.clients WHERE entity_id IS NULL;
    SELECT count(*) INTO missing_devices
      FROM operations.devices WHERE entity_id IS NULL;

    IF missing_clients > 0 OR missing_devices > 0 THEN
        RAISE EXCEPTION
            'Cannot require entity anchors: % clients and % devices still unanchored',
            missing_clients, missing_devices;
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0119_node_class_mappings"),
    ]

    operations: ClassVar[list] = [
        # Reverse is a no-op: dropping NOT NULL below does not need the rows
        # removed, and deleting anchors would be destructive.
        migrations.RunSQL(_ANCHOR_BACKFILL_SQL, migrations.RunSQL.noop),
        migrations.AlterField(
            model_name="client",
            name="entity",
            field=models.OneToOneField(
                on_delete=models.deletion.PROTECT,
                related_name="client_record",
                to="operations.entity",
            ),
        ),
        migrations.AlterField(
            model_name="device",
            name="entity",
            field=models.OneToOneField(
                on_delete=models.deletion.PROTECT,
                related_name="device_record",
                to="operations.entity",
            ),
        ),
    ]
