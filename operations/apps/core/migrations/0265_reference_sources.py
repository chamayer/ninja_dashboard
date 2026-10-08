"""Register external reference feeds as configured Sources."""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import migrations


INTERNAL_COLLECTOR_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
REFERENCE_SOURCES = (
    ("NVD", "reference.nvd", "security", 360),
    ("CPE Dictionary", "reference.cpe", "software", 1440),
    ("CISA KEV", "reference.kev", "security", 60),
    ("EPSS", "reference.epss", "security", 1440),
    ("AlienVault OTX", "reference.otx", "security", 360),
    ("abuse.ch", "reference.abusech", "security", 360),
    ("Windows Package Manager", "reference.winget", "software", 1440),
    ("Chocolatey", "reference.chocolatey", "software", 1440),
    ("Remote-access catalog", "reference.remote-access", "software", 1440),
    ("End-of-life data", "reference.end-of-life", "software", 1440),
)

REFERENCE_JOB_KEYS = (
    "intel-nvd", "intel-cpe-dict", "intel-kev", "intel-epss", "intel-winget",
    "intel-chocolatey", "intel-lolrmm", "intel-otx", "intel-abusech", "intel-endoflife",
)


def seed_reference_sources(apps, schema_editor):
    Tenant = apps.get_model("operations", "Tenant")
    Source = apps.get_model("operations", "Source")
    SourceInstance = apps.get_model("operations", "SourceInstance")
    SourceBinding = apps.get_model("operations", "SourceBinding")
    CollectorInstance = apps.get_model("operations", "CollectorInstance")

    tenant = Tenant.objects.get(id=1)
    collector = CollectorInstance.objects.get(id=INTERNAL_COLLECTOR_ID)
    namespace = uuid.UUID("05e0f4dc-cc80-4e4c-88b9-f2a43e063a65")
    # Older imported Sources were inserted with explicit IDs, leaving the
    # PostgreSQL sequence behind the table maximum.  Align it before the
    # migration creates any reference Source rows.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT setval(pg_get_serial_sequence('operations.sources', 'id'),
                              COALESCE((SELECT MAX(id) FROM operations.sources), 1),
                              TRUE)"""
        )
    for name, source_key, purpose, minutes in REFERENCE_SOURCES:
        source, _ = Source.objects.get_or_create(
            name=name,
            defaults={
                "kind": "reference",
                "entity_type": "",
                "capabilities": {"purpose": purpose, "external": True},
            },
        )
        instance, _ = SourceInstance.objects.get_or_create(
            id=uuid.uuid5(namespace, f"instance:{source_key}"),
            defaults={
                "tenant": tenant,
                "source": source,
                "config": {"platform": source_key, "source_key": source_key, "source_name": name},
                "enabled": True,
            },
        )
        SourceBinding.objects.get_or_create(
            id=uuid.uuid5(namespace, f"binding:{source_key}"),
            defaults={
                "tenant": tenant,
                "source_instance": instance,
                "collector_instance": collector,
                "schedule": f"interval:{minutes}",
                "enabled": True,
            },
        )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """UPDATE operations.job_schedules SET enabled = FALSE,
                   capability_reason = 'Replaced by the configured source schedule.', next_due_at = NULL
                 WHERE tenant_id = 1 AND definition_key = ANY(%s)""",
            [list(REFERENCE_JOB_KEYS)],
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0264_source_scoped_dispatch")]
    operations: ClassVar[list] = [migrations.RunPython(seed_reference_sources, migrations.RunPython.noop)]
