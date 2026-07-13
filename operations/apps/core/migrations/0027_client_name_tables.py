"""Migration 0027 — Track C batch C1: client name mapping tables.

Mappings live in data, never code (BLUEPRINT Track C principle 4):

- client_name_aliases  — normalized name → client (tiered: manual > seed
  > alignment > source); replaces legacy client_aliases.
- client_org_excludes  — source groups excluded from client candidacy;
  replaces legacy org_excludes.
- placeholder_org_names — generic container names that never become
  candidates; replaces the hardcoded _PLACEHOLDER_ORG_NAMES set
  (seeded from it here).

Legacy alias/exclude row import happens in batch C2 alongside the client
resolver.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models

_TABLES = ("client_name_aliases", "client_org_excludes", "placeholder_org_names")

_RLS_SQL = "\n".join(
    f"""
    ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON operations.{table}
        USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
    GRANT SELECT, INSERT, UPDATE, DELETE ON operations.{table} TO operations_app;
    GRANT SELECT, INSERT, UPDATE ON operations.{table} TO ninja_ingest;
    GRANT SELECT ON operations.{table} TO operations_readonly;
    GRANT SELECT ON operations.{table} TO metabase_ro;
    """
    for table in _TABLES
)

_RLS_REVERSE_SQL = "\n".join(
    f"DROP POLICY IF EXISTS tenant_isolation ON operations.{table};"
    for table in _TABLES
)

# Seed values copied from ingest/normalize.py _PLACEHOLDER_ORG_NAMES.
_PLACEHOLDER_SEED = ("defaultsite", "default", "unknown", "various")


def seed_placeholder_names(apps, schema_editor):
    PlaceholderOrgName = apps.get_model("operations", "PlaceholderOrgName")
    for name in _PLACEHOLDER_SEED:
        PlaceholderOrgName.objects.get_or_create(
            tenant_id=1,
            normalized_name=name,
            defaults={"id": uuid.uuid4(), "note": "seeded from _PLACEHOLDER_ORG_NAMES"},
        )


def unseed_placeholder_names(apps, schema_editor):
    PlaceholderOrgName = apps.get_model("operations", "PlaceholderOrgName")
    PlaceholderOrgName.objects.filter(
        tenant_id=1, normalized_name__in=_PLACEHOLDER_SEED
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0026_duplicate_record_finding"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientOrgExclude",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("external_id", models.CharField(blank=True, default="", max_length=240)),
                ("normalized_name", models.CharField(blank=True, default="", max_length=240)),
                ("reason", models.CharField(blank=True, default="", max_length=240)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.CharField(blank=True, default="", max_length=120)),
                ("source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="org_excludes", to="operations.source")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={
                "db_table": "client_org_excludes",
            },
        ),
        migrations.CreateModel(
            name="ClientNameAlias",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("alias", models.CharField(max_length=240)),
                ("normalized_name", models.CharField(max_length=240)),
                ("tier", models.CharField(choices=[("manual", "Manual"), ("seed", "Seed"), ("alignment", "Alignment"), ("source", "Source")], default="manual", max_length=16)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.CharField(blank=True, default="", max_length=120)),
                ("created_reason", models.CharField(blank=True, default="", max_length=120)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="name_aliases", to="operations.client")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={
                "db_table": "client_name_aliases",
                "constraints": [models.UniqueConstraint(fields=("tenant", "normalized_name"), name="uq_client_name_aliases_tenant_normalized")],
            },
        ),
        migrations.CreateModel(
            name="PlaceholderOrgName",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("normalized_name", models.CharField(max_length=240)),
                ("note", models.CharField(blank=True, default="", max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={
                "db_table": "placeholder_org_names",
                "constraints": [models.UniqueConstraint(fields=("tenant", "normalized_name"), name="uq_placeholder_org_names_tenant_normalized")],
            },
        ),
        migrations.RunSQL(_RLS_SQL, _RLS_REVERSE_SQL),
        migrations.RunPython(seed_placeholder_names, unseed_placeholder_names),
    ]
