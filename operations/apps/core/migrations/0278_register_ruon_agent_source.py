"""Register R-U-ON as an agent source (``agent.monitoring``).

R-U-ON is agent-based uptime/performance monitoring. Like LogMeIn and
ScreenConnect it installs on the machine, so it is an identity-signal agent
stream and can be a required agent in a requirement profile.

Seeds reference data only: the entity type, platform aliases, the ``agents``
requirement-universe row, and the source/instance/binding. Which clients
require it, and for which device scope, is operator data set in requirement
profiles — not decided here.

The instance is seeded enabled, like the other agent sources. Its credentials
are the environment variables named in ``client_id_ref`` / ``client_secret_ref``
(``RUON_USERNAME`` / ``RUON_PASSWORD``); set them in the host ``.env`` before
the deploy, or the first cycles record failed runs until they exist. Disable it
in the Django admin (Source instances) to pause collection.

Displayed times carry no timezone, so ``last_seen_at`` stays null and the
displayed text is kept raw rather than guessed.

Coverage-requirement ``Agent.supported_os_groups`` is the widest plausible
ceiling; narrow it, or use a profile item's ``applicable_os_groups``, once the
supported platforms are confirmed.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import migrations

INTERNAL_COLLECTOR_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_NAMESPACE = uuid.UUID("5d0b4a1e-6c1f-4f7e-9a53-0c7d7c1e2b90")
SOURCE_NAME = "R-U-ON"
SOURCE_KEY = "ruon"

ENTITY_TYPE_SQL = """
INSERT INTO operations.entity_types
    (name, entity_class_id, is_identity_signal, consumes_license,
     requirement_eligible, lifecycle_evidence_mode, description)
VALUES
    ('agent.monitoring', 'device', TRUE, FALSE, TRUE, 'direct_contact',
     'Monitoring agent installed on the machine (uptime and performance).')
ON CONFLICT (name) DO NOTHING;

INSERT INTO operations.platform_aliases (alias, canonical) VALUES
    ('r-u-on', 'R-U-ON'),
    ('ruon',   'R-U-ON')
ON CONFLICT (alias) DO NOTHING;

INSERT INTO operations.agents
    (name, entity_type, supported_os_groups, default_severity,
     default_gap_after_hours, default_confidence_probable,
     default_confidence_confirmed)
VALUES
    ('R-U-ON', 'agent.monitoring', '["Windows", "macOS", "Linux"]'::jsonb,
     'high', 24, 48, 168)
ON CONFLICT (name) DO NOTHING;
"""


def register_source(apps, schema_editor):
    Tenant = apps.get_model("operations", "Tenant")
    Source = apps.get_model("operations", "Source")
    SourceInstance = apps.get_model("operations", "SourceInstance")
    SourceBinding = apps.get_model("operations", "SourceBinding")
    CollectorInstance = apps.get_model("operations", "CollectorInstance")

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT setval(pg_get_serial_sequence('operations.sources', 'id'),
                              COALESCE((SELECT MAX(id) FROM operations.sources), 1),
                              TRUE)"""
        )
    tenant = Tenant.objects.get(id=1)
    collector = CollectorInstance.objects.get(id=INTERNAL_COLLECTOR_ID)
    source, _ = Source.objects.get_or_create(
        name=SOURCE_NAME,
        defaults={
            "kind": "monitoring",
            "entity_type": "agent.monitoring",
            "capabilities": {"scope": "tenant", "implemented": True},
        },
    )
    instance, _ = SourceInstance.objects.get_or_create(
        id=uuid.uuid5(_NAMESPACE, f"instance:{SOURCE_KEY}"),
        defaults={
            "tenant": tenant,
            "source": source,
            "client": None,
            "enabled": True,
            "config": {
                "platform": SOURCE_NAME,
                "source_key": SOURCE_KEY,
                "source_name": SOURCE_NAME,
                "is_shared": True,
                "base_url": "https://www.r-u-on.com",
                "client_id_ref": "RUON_USERNAME",
                "client_secret_ref": "RUON_PASSWORD",
            },
        },
    )
    SourceBinding.objects.get_or_create(
        id=uuid.uuid5(_NAMESPACE, f"binding:{SOURCE_KEY}"),
        defaults={
            "tenant": tenant,
            "source_instance": instance,
            "collector_instance": collector,
            "schedule": "interval:240",
            "enabled": True,
        },
    )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0277_software_reclassification_target_cursor"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(ENTITY_TYPE_SQL, migrations.RunSQL.noop),
        migrations.RunPython(register_source, migrations.RunPython.noop),
    ]
