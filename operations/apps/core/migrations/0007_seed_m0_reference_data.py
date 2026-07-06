from __future__ import annotations

import uuid

from django.contrib.auth.hashers import make_password
from django.db import migrations


PERMISSIONS = (
    ("view_clients", "Can view clients"),
    ("view_devices", "Can view devices"),
    ("view_software", "Can view software"),
    ("view_findings", "Can view findings"),
    ("write_decisions", "Can write decisions"),
    ("approve_merges", "Can approve merges"),
    ("manage_findings", "Can manage findings"),
    ("manage_client_policy", "Can manage client policy"),
    ("manage_catalog", "Can manage software catalog"),
    ("manage_collectors", "Can manage collectors"),
    ("manage_sources", "Can manage sources"),
    ("manage_secrets", "Can manage secrets"),
    ("manage_users", "Can manage Operations users"),
    ("manage_taxonomy", "Can manage reference taxonomy"),
    ("run_queries", "Can run saved queries"),
)

VIEW_PERMISSIONS = ("view_clients", "view_devices", "view_software", "view_findings")
OPERATOR_PERMISSIONS = (
    *VIEW_PERMISSIONS,
    "write_decisions",
    "approve_merges",
    "manage_findings",
    "manage_client_policy",
    "run_queries",
)

FINDING_TYPES = (
    ("unlinked_external_identity", "high", "Unlinked external identity"),
    ("stale_collector_binding", "medium", "Stale collector binding"),
    ("unauthorized_rmm", "high", "Unauthorized RMM"),
    ("unauthorized_av", "high", "Unauthorized AV"),
    ("unauthorized_remote_access", "high", "Unauthorized remote access"),
    ("install_path_suspicious", "medium", "Suspicious install path"),
    ("rare_recent", "medium", "Rare recent install"),
    ("eol_runtime", "high", "End-of-life runtime"),
    ("suspicious_name", "medium", "Suspicious software name"),
    ("multi_av_conflict", "high", "Multiple AV/EDR conflict"),
)

INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def seed_m0_reference_data(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    Tenant = apps.get_model("operations", "Tenant")
    Source = apps.get_model("operations", "Source")
    Collector = apps.get_model("operations", "Collector")
    CollectorInstance = apps.get_model("operations", "CollectorInstance")
    FindingType = apps.get_model("operations", "FindingType")
    User = apps.get_model("operations", "User")

    tenant, _ = Tenant.objects.get_or_create(
        id=1,
        defaults={
            "slug": "amrose",
            "display_name": "AMRose",
            "brand_config": {},
        },
    )

    content_type, _ = ContentType.objects.get_or_create(
        app_label="operations",
        model="user",
    )
    permission_by_codename = {}
    for codename, name in PERMISSIONS:
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        if permission.name != name:
            permission.name = name
            permission.save(update_fields=["name"])
        permission_by_codename[codename] = permission

    admin_group, _ = Group.objects.get_or_create(name="admin")
    operator_group, _ = Group.objects.get_or_create(name="operator")
    viewer_group, _ = Group.objects.get_or_create(name="viewer")

    admin_group.permissions.set(permission_by_codename.values())
    operator_group.permissions.set(
        permission_by_codename[codename] for codename in OPERATOR_PERMISSIONS
    )
    viewer_group.permissions.set(
        permission_by_codename[codename] for codename in (*VIEW_PERMISSIONS, "run_queries")
    )

    Source.objects.update_or_create(
        name="Ninja",
        defaults={
            "kind": "rmm",
            "capabilities": {"scope": "tenant", "implemented": True},
        },
    )

    Collector.objects.update_or_create(
        name="internal-ingest",
        defaults={
            "kind": "internal",
            "capabilities": {"transport": "in_process"},
        },
    )
    Collector.objects.update_or_create(
        name="ninja-hosted-script",
        defaults={
            "kind": "https",
            "capabilities": {"transport": "ninja_script"},
        },
    )

    CollectorInstance.objects.update_or_create(
        id=INTERNAL_COLLECTOR_INSTANCE_ID,
        defaults={
            "tenant": tenant,
            "name": "internal-ingest",
            "kind": "internal",
            "token_hash": "",
            "capabilities": {"transport": "in_process", "trusted_network": True},
            "version": 1,
        },
    )

    for name, severity, description in FINDING_TYPES:
        FindingType.objects.update_or_create(
            name=name,
            defaults={
                "default_severity": severity,
                "runbook_path": f"docs/runbooks/{name}.md",
                "description": description,
            },
        )

    if not User.objects.filter(username="admin").exists():
        User.objects.create_superuser(
            username="admin",
            email="admin@localhost",
            password=make_password(None),
            tenant=tenant,
        )


def unseed_m0_reference_data(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Tenant = apps.get_model("operations", "Tenant")
    Source = apps.get_model("operations", "Source")
    Collector = apps.get_model("operations", "Collector")
    CollectorInstance = apps.get_model("operations", "CollectorInstance")
    FindingType = apps.get_model("operations", "FindingType")
    User = apps.get_model("operations", "User")

    User.objects.filter(username="admin", email="admin@localhost").delete()
    CollectorInstance.objects.filter(id=INTERNAL_COLLECTOR_INSTANCE_ID).delete()
    FindingType.objects.filter(name__in=[name for name, _, _ in FINDING_TYPES]).delete()
    Collector.objects.filter(name__in=["internal-ingest", "ninja-hosted-script"]).delete()
    Source.objects.filter(name="Ninja").delete()
    Group.objects.filter(name__in=["admin", "operator", "viewer"]).delete()
    Tenant.objects.filter(id=1, slug="amrose").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0006_rls_roles_policies_grants"),
    ]

    operations = [
        migrations.RunPython(seed_m0_reference_data, unseed_m0_reference_data),
    ]
