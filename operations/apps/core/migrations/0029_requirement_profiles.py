"""Migration 0029 — Track C batch C3a.

Adds:
  * requirement_profiles  — named templates of coverage requirements
    (tenant-default is a data row, per Track C principle 4)
  * requirement_profile_items — one (entity_type, platform, device_scope)
    row per template (shape mirrors CoverageRequirement, minus client)
  * clients.requirement_profile  — nullable FK; assigned on accept

Seeds a "Standard" profile from the tenant's current GLOBAL
(client_id NULL) coverage_requirements so acceptance in C3c has a real
template out of the gate. Marks it is_tenant_default.
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


_PROFILE_TABLES = ("requirement_profiles", "requirement_profile_items")

_RLS_SQL = "\n".join(
    f"""
    ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON operations.{table}
        USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
    GRANT SELECT, INSERT, UPDATE, DELETE ON operations.{table} TO operations_app;
    GRANT SELECT ON operations.{table} TO ninja_ingest;
    GRANT SELECT ON operations.{table} TO operations_readonly;
    GRANT SELECT ON operations.{table} TO metabase_ro;
    """
    for table in _PROFILE_TABLES
)

_RLS_REVERSE_SQL = "\n".join(
    f"DROP POLICY IF EXISTS tenant_isolation ON operations.{table};"
    for table in _PROFILE_TABLES
)


def seed_standard_profile(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    RequirementProfile = apps.get_model("operations", "RequirementProfile")
    RequirementProfileItem = apps.get_model("operations", "RequirementProfileItem")
    CoverageRequirement = apps.get_model("operations", "CoverageRequirement")

    profile, created = RequirementProfile.objects.get_or_create(
        tenant_id=1, name="Standard",
        defaults={
            "id": uuid.uuid4(),
            "description": "Seeded from tenant global coverage_requirements",
            "is_tenant_default": True,
        },
    )
    if not created and not profile.is_tenant_default:
        # If a same-named profile pre-exists, don't override its default flag.
        return

    seen: set[tuple] = set()
    for req in CoverageRequirement.objects.filter(
        tenant_id=1, client__isnull=True, enabled=True
    ):
        key = (req.entity_type, req.platform, req.device_scope)
        if key in seen:
            continue
        seen.add(key)
        RequirementProfileItem.objects.get_or_create(
            tenant_id=1, profile=profile,
            entity_type=req.entity_type,
            platform=req.platform,
            device_scope=req.device_scope,
            defaults={
                "id": uuid.uuid4(),
                "severity": req.severity,
                "gap_after_hours": req.gap_after_hours,
                "confidence_probable": req.confidence_probable,
                "confidence_confirmed": req.confidence_confirmed,
            },
        )


def unseed_standard_profile(apps, schema_editor):
    RequirementProfile = apps.get_model("operations", "RequirementProfile")
    RequirementProfile.objects.filter(tenant_id=1, name="Standard").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0028_client_resolver"),
    ]

    operations = [
        migrations.CreateModel(
            name="RequirementProfile",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("description", models.CharField(blank=True, default="", max_length=240)),
                ("is_tenant_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={
                "db_table": "requirement_profiles",
            },
        ),
        migrations.AddConstraint(
            model_name="requirementprofile",
            constraint=models.UniqueConstraint(
                fields=("tenant", "name"),
                name="uq_requirement_profiles_tenant_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="requirementprofile",
            constraint=models.UniqueConstraint(
                fields=("tenant",),
                condition=models.Q(("is_tenant_default", True)),
                name="uq_requirement_profiles_tenant_default",
            ),
        ),
        migrations.CreateModel(
            name="RequirementProfileItem",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("entity_type", models.CharField(max_length=80)),
                ("platform", models.CharField(blank=True, default="", max_length=80)),
                ("device_scope", models.CharField(default="all", max_length=40)),
                ("severity", models.CharField(default="high", max_length=16)),
                ("gap_after_hours", models.PositiveIntegerField(default=24)),
                ("confidence_probable", models.PositiveIntegerField(default=48)),
                ("confidence_confirmed", models.PositiveIntegerField(default=168)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="operations.requirementprofile")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={
                "db_table": "requirement_profile_items",
                "constraints": [models.UniqueConstraint(fields=("tenant", "profile", "entity_type", "platform", "device_scope"), name="uq_requirement_profile_items_shape")],
            },
        ),
        migrations.AddField(
            model_name="client",
            name="requirement_profile",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clients",
                to="operations.requirementprofile",
            ),
        ),
        migrations.RunSQL(_RLS_SQL, _RLS_REVERSE_SQL),
        migrations.RunPython(seed_standard_profile, unseed_standard_profile),
    ]
