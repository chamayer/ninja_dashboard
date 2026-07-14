"""Migration 0033 — Agent universe + os_group + device_unenrolled.

Data model changes:
  * `agents` reference table (4 seeded rows)
  * `os_group_mappings` reference table (data-driven os_family → os_group)
  * `devices.os_group` (Windows / macOS / Linux / Other / Unknown)
  * `requirement_profile_items.agent_id` + `.applicable_os_groups`
  * `coverage_requirements.agent_id` + `.applicable_os_groups`
  * `device_unenrolled` finding type (entity, medium, auto)

Semantics:
  * Coverage requirements apply only to devices in the "agent universe"
    (has ANY agent.* observation historically). Pure vm.guest / vm.host /
    network.device tracking rows are surfaced separately via the new
    `device_unenrolled` finding type.
  * Within the universe, each required Agent is skipped for a device
    whose `os_group` is not in `Agent.supported_os_groups` (agent
    physics — e.g. LMI on Linux).
  * Profile items may narrow further via `applicable_os_groups` (client
    policy override on top of the physics ceiling).
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import connection, migrations, models


_AGENTS_SEED = [
    ("Ninja", "agent.rmm", ["Windows", "macOS", "Linux"], "critical"),
    ("SentinelOne", "agent.edr", ["Windows", "macOS", "Linux"], "critical"),
    ("LogMeIn", "agent.remote_access", ["Windows", "macOS"], "high"),
    ("ScreenConnect", "agent.remote_access", ["Windows", "macOS"], "high"),
]

_OS_GROUP_MAP_SEED = [
    # first-match-wins order via priority ascending
    ("Windows Server %", "Windows", 10),
    ("Windows %", "Windows", 20),
    ("Windows", "Windows", 30),
    ("macOS %", "macOS", 10),
    ("macOS", "macOS", 20),
    ("Linux", "Linux", 10),
    ("Other", "Other", 100),
]


def seed_and_migrate(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    Agent = apps.get_model("operations", "Agent")
    OsGroupMapping = apps.get_model("operations", "OsGroupMapping")
    RequirementProfileItem = apps.get_model("operations", "RequirementProfileItem")
    CoverageRequirement = apps.get_model("operations", "CoverageRequirement")
    FindingType = apps.get_model("operations", "FindingType")

    # ── 1. Seed Agents ────────────────────────────────────────────────
    agent_by_name = {}
    for name, entity_type, supported, severity in _AGENTS_SEED:
        agent, _ = Agent.objects.get_or_create(
            name=name,
            defaults={
                "entity_type": entity_type,
                "supported_os_groups": supported,
                "default_severity": severity,
                "default_gap_after_hours": 24,
                "default_confidence_probable": 48,
                "default_confidence_confirmed": 168,
            },
        )
        agent_by_name[name] = agent

    # ── 2. Seed OsGroupMappings ───────────────────────────────────────
    for pattern, os_group, priority in _OS_GROUP_MAP_SEED:
        OsGroupMapping.objects.get_or_create(
            pattern=pattern,
            defaults={"os_group": os_group, "priority": priority},
        )

    # ── 3. Backfill devices.os_group from os_family via mappings ──────
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE operations.devices d
            SET os_group = COALESCE(
                (SELECT m.os_group
                 FROM operations.os_group_mappings m
                 WHERE d.os_family LIKE m.pattern
                 ORDER BY m.priority ASC LIMIT 1),
                'Unknown'
            )
            WHERE d.tenant_id = 1
            """
        )

    # ── 4. Backfill agent_id on existing profile items + coverage rows ─
    for item in RequirementProfileItem.objects.filter(tenant_id=1, agent__isnull=True):
        agent = agent_by_name.get(item.platform)
        if agent:
            item.agent = agent
            item.save(update_fields=["agent"])

    for req in CoverageRequirement.objects.filter(tenant_id=1, agent__isnull=True):
        agent = agent_by_name.get(req.platform)
        if agent:
            req.agent = agent
            req.save(update_fields=["agent"])

    # ── 5. Seed device_unenrolled finding type ────────────────────────
    FindingType.objects.get_or_create(
        name="device_unenrolled",
        defaults={
            "default_severity": "medium",
            "finding_class": "entity",
            "source_module": "platform.evaluator",
            "auto_resolvable": True,
            "description": (
                "Device is tracked by a hypervisor / NMS / cloud monitor "
                "but has no agent.* observations. Operator must enroll "
                "agents, exclude the device from management, or retire "
                "the tracking record."
            ),
        },
    )


def unseed(apps, schema_editor):
    Agent = apps.get_model("operations", "Agent")
    OsGroupMapping = apps.get_model("operations", "OsGroupMapping")
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="device_unenrolled").delete()
    Agent.objects.all().delete()
    OsGroupMapping.objects.all().delete()


_RLS_SQL = """
ALTER TABLE operations.agents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.agents FOR SELECT USING (TRUE);
GRANT SELECT ON operations.agents TO operations_app, ninja_ingest, operations_readonly, metabase_ro;

ALTER TABLE operations.os_group_mappings ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.os_group_mappings FOR SELECT USING (TRUE);
GRANT SELECT ON operations.os_group_mappings TO operations_app, ninja_ingest, operations_readonly, metabase_ro;

GRANT UPDATE ON operations.devices TO ninja_ingest;
"""

_RLS_REVERSE_SQL = """
DROP POLICY IF EXISTS tenant_read ON operations.agents;
DROP POLICY IF EXISTS tenant_read ON operations.os_group_mappings;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0032_client_profiles_from_legacy"),
    ]

    operations = [
        migrations.CreateModel(
            name="Agent",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=80, unique=True)),
                ("entity_type", models.CharField(max_length=80)),
                ("supported_os_groups", models.JSONField(default=list)),
                ("default_severity", models.CharField(default="high", max_length=16)),
                ("default_gap_after_hours", models.PositiveIntegerField(default=24)),
                ("default_confidence_probable", models.PositiveIntegerField(default=48)),
                ("default_confidence_confirmed", models.PositiveIntegerField(default=168)),
            ],
            options={"db_table": "agents", "ordering": ("name",)},
        ),
        migrations.CreateModel(
            name="OsGroupMapping",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("pattern", models.CharField(max_length=80)),
                ("os_group", models.CharField(max_length=16)),
                ("priority", models.PositiveIntegerField(default=100)),
            ],
            options={"db_table": "os_group_mappings", "ordering": ("priority", "pattern")},
        ),
        migrations.AddField(
            model_name="device",
            name="os_group",
            field=models.CharField(blank=True, default="Unknown", max_length=16),
        ),
        migrations.AddField(
            model_name="requirementprofileitem",
            name="agent",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="profile_items",
                to="operations.agent",
            ),
        ),
        migrations.AddField(
            model_name="requirementprofileitem",
            name="applicable_os_groups",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="requirementprofileitem",
            name="entity_type",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="coveragerequirement",
            name="agent",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="coverage_requirements",
                to="operations.agent",
            ),
        ),
        migrations.AddField(
            model_name="coveragerequirement",
            name="applicable_os_groups",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="coveragerequirement",
            name="entity_type",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.RunSQL(_RLS_SQL, _RLS_REVERSE_SQL),
        migrations.RunPython(seed_and_migrate, unseed),
    ]
