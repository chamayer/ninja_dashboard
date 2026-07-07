from __future__ import annotations

import uuid

from django.db import migrations

NINJA_SOURCE_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
NINJA_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def seed_ninja_source_binding(apps, schema_editor):
    Tenant = apps.get_model("operations", "Tenant")
    Source = apps.get_model("operations", "Source")
    CollectorInstance = apps.get_model("operations", "CollectorInstance")
    SourceInstance = apps.get_model("operations", "SourceInstance")
    SourceBinding = apps.get_model("operations", "SourceBinding")

    tenant = Tenant.objects.get(id=1)
    ninja_source = Source.objects.get(name="Ninja")
    internal_collector = CollectorInstance.objects.get(id=INTERNAL_COLLECTOR_INSTANCE_ID)

    source_instance, _ = SourceInstance.objects.update_or_create(
        id=NINJA_SOURCE_INSTANCE_ID,
        defaults={
            "tenant": tenant,
            "source": ninja_source,
            "client": None,
            "config": {"scope": "tenant"},
            "enabled": True,
        },
    )

    SourceBinding.objects.update_or_create(
        id=NINJA_SOURCE_BINDING_ID,
        defaults={
            "tenant": tenant,
            "source_instance": source_instance,
            "collector_instance": internal_collector,
            "schedule": "",
            "enabled": True,
        },
    )


def grant_ninja_ingest_resolution_reads(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "GRANT SELECT ON operations.devices, operations.device_links TO ninja_ingest"
    )


def revoke_ninja_ingest_resolution_reads(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "REVOKE SELECT ON operations.devices, operations.device_links FROM ninja_ingest"
    )


def unseed_ninja_source_binding(apps, schema_editor):
    SourceBinding = apps.get_model("operations", "SourceBinding")
    SourceInstance = apps.get_model("operations", "SourceInstance")
    SourceBinding.objects.filter(id=NINJA_SOURCE_BINDING_ID).delete()
    SourceInstance.objects.filter(id=NINJA_SOURCE_INSTANCE_ID).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0009_rename_device_kind_to_device_type"),
    ]

    operations = [
        migrations.RunPython(seed_ninja_source_binding, unseed_ninja_source_binding),
        migrations.RunPython(
            grant_ninja_ingest_resolution_reads,
            revoke_ninja_ingest_resolution_reads,
        ),
    ]
