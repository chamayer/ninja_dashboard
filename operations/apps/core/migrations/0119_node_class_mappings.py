"""Migration 0119 — the Ninja node_class taxonomy becomes data.

Per ADR-0012 section 6 a domain mapping is operator-maintainable data, not a
constant. This one was hardcoded in five places with three different matching
styles:

  - `normalize._AGENT_NODE_CLASSES` (set membership) plus prefix/suffix tests
  - `resolver._infer_form_factor` (`str.startswith` / `str.endswith`)
  - `device_cache_projector` (`left(...)` / `right(...)` in SQL)
  - `core/devices.py` (a suffix tuple, for is_vm detection)
  - `restore_ninja_historical_evidence.py` (the same suffix tuple)

Seeded from the union of those copies. All 11 node_class values present in
production map cleanly, so the seed is complete against current data rather
than merely plausible.

`form_factor` is deliberately NULL for the agent classes. ADR-0005: agent
presence is not evidence of form factor, and a default of 'physical' here is
exactly the bug that record exists to prevent.
"""

from typing import ClassVar

from django.db import migrations, models

# (pattern, entity_type, form_factor) in priority order — first match wins.
# form_factor '' means "this class says nothing about form factor".
_SEED: tuple[tuple[str, str, str], ...] = (
    # Agent streams. No form factor: an agent says an OS is managed, not that
    # the hardware is physical.
    ("WINDOWS_WORKSTATION", "agent.rmm", ""),
    ("WINDOWS_SERVER", "agent.rmm", ""),
    ("LINUX_WORKSTATION", "agent.rmm", ""),
    ("LINUX_SERVER", "agent.rmm", ""),
    ("MAC", "agent.rmm", ""),
    ("MAC_SERVER", "agent.rmm", ""),
    # Asset-nature streams. These do imply a form factor.
    ("%\\_VMM\\_GUEST", "vm.guest", "vm"),
    ("%\\_VM\\_GUEST", "vm.guest", "vm"),
    ("%\\_VMM\\_HOST", "vm.host", "hypervisor-host"),
    ("%\\_VM\\_HOST", "vm.host", "hypervisor-host"),
    ("NMS\\_%", "network.device", "network-device"),
    ("CLOUD_MONITOR_TARGET", "monitor.target", ""),
)

_GRANT_SQL = """
GRANT SELECT ON operations.node_class_mappings
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""

_GRANT_REVERSE_SQL = """
REVOKE SELECT ON operations.node_class_mappings
    FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""


def _seed(apps, schema_editor):
    Mapping = apps.get_model("operations", "NodeClassMapping")
    Mapping.objects.bulk_create(
        [
            Mapping(
                pattern=pattern,
                entity_type=entity_type,
                form_factor=form_factor,
                priority=(index + 1) * 10,
            )
            for index, (pattern, entity_type, form_factor) in enumerate(_SEED)
        ]
    )


def _unseed(apps, schema_editor):
    apps.get_model("operations", "NodeClassMapping").objects.all().delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0118_os_family_mappings"),
    ]

    operations: ClassVar[list] = [
        migrations.CreateModel(
            name="NodeClassMapping",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("pattern", models.CharField(max_length=80)),
                ("entity_type", models.CharField(max_length=32)),
                ("form_factor", models.CharField(blank=True, default="", max_length=24)),
                ("priority", models.PositiveIntegerField(default=100)),
            ],
            options={
                "db_table": "node_class_mappings",
                "ordering": ("priority", "pattern"),
            },
        ),
        migrations.RunPython(_seed, _unseed),
        migrations.RunSQL(_GRANT_SQL, _GRANT_REVERSE_SQL),
    ]
