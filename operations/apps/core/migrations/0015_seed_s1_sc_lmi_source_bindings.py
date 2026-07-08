"""Migration 0015 — seed SentinelOne, ScreenConnect, and LogMeIn source bindings.

Creates Source + SourceInstance + SourceBinding rows for the three AC
connectors so ingest can write entity_observations with valid FKs.

Fixed UUIDs follow the 00000000-0000-4000-8000-0000000000XX pattern:
  source_instance_id: 20 (S1), 21 (SC), 22 (LMI)
  source_binding_id:  12 (S1), 13 (SC), 14 (LMI)
"""

from __future__ import annotations

import uuid

from django.db import migrations

S1_SOURCE_INSTANCE_ID  = uuid.UUID("00000000-0000-4000-8000-000000000020")
SC_SOURCE_INSTANCE_ID  = uuid.UUID("00000000-0000-4000-8000-000000000021")
LMI_SOURCE_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000022")

S1_SOURCE_BINDING_ID   = uuid.UUID("00000000-0000-4000-8000-000000000012")
SC_SOURCE_BINDING_ID   = uuid.UUID("00000000-0000-4000-8000-000000000013")
LMI_SOURCE_BINDING_ID  = uuid.UUID("00000000-0000-4000-8000-000000000014")

INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

_SOURCES = (
    ("SentinelOne",   "edr",           S1_SOURCE_INSTANCE_ID,  S1_SOURCE_BINDING_ID),
    ("ScreenConnect", "remote_access", SC_SOURCE_INSTANCE_ID,  SC_SOURCE_BINDING_ID),
    ("LogMeIn",       "remote_access", LMI_SOURCE_INSTANCE_ID, LMI_SOURCE_BINDING_ID),
)


def seed_source_bindings(apps, schema_editor):
    Tenant = apps.get_model("operations", "Tenant")
    Source = apps.get_model("operations", "Source")
    CollectorInstance = apps.get_model("operations", "CollectorInstance")
    SourceInstance = apps.get_model("operations", "SourceInstance")
    SourceBinding = apps.get_model("operations", "SourceBinding")

    tenant = Tenant.objects.get(id=1)
    internal_collector = CollectorInstance.objects.get(id=INTERNAL_COLLECTOR_INSTANCE_ID)

    for source_name, kind, si_id, sb_id in _SOURCES:
        source, _ = Source.objects.update_or_create(
            name=source_name,
            defaults={"kind": kind, "capabilities": {"scope": "tenant", "implemented": True}},
        )
        source_instance, _ = SourceInstance.objects.update_or_create(
            id=si_id,
            defaults={
                "tenant": tenant,
                "source": source,
                "client": None,
                "config": {"scope": "tenant"},
                "enabled": True,
            },
        )
        SourceBinding.objects.update_or_create(
            id=sb_id,
            defaults={
                "tenant": tenant,
                "source_instance": source_instance,
                "collector_instance": internal_collector,
                "schedule": "",
                "enabled": True,
            },
        )


def unseed_source_bindings(apps, schema_editor):
    SourceBinding = apps.get_model("operations", "SourceBinding")
    SourceInstance = apps.get_model("operations", "SourceInstance")
    Source = apps.get_model("operations", "Source")

    for _, _, si_id, sb_id in _SOURCES:
        SourceBinding.objects.filter(id=sb_id).delete()
        SourceInstance.objects.filter(id=si_id).delete()

    for source_name, _, _, _ in _SOURCES:
        Source.objects.filter(name=source_name).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0014_platform_tables"),
    ]

    operations = [
        migrations.RunPython(seed_source_bindings, unseed_source_bindings),
    ]
