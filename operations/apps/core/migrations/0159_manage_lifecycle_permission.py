"""Add a dedicated permission for canonical Computer lifecycle actions."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


def grant_lifecycle_permission(apps, schema_editor) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("operations", "User")
    content_type = ContentType.objects.get(app_label="operations", model="user")
    lifecycle_permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="manage_lifecycle",
        defaults={"name": "Can manage Computer lifecycle"},
    )
    catalog_permission = Permission.objects.filter(
        content_type=content_type,
        codename="manage_catalog",
    ).first()
    if catalog_permission is None:
        return
    for group in Group.objects.filter(permissions=catalog_permission):
        group.permissions.add(lifecycle_permission)
    for user in User.objects.filter(user_permissions=catalog_permission):
        user.user_permissions.add(lifecycle_permission)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0158_source_record_lifecycle_contract"),
    ]

    operations: ClassVar[list[migrations.operations.base.Operation]] = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": (
                    ("view_clients", "Can view clients"),
                    ("view_devices", "Can view devices"),
                    ("view_software", "Can view software"),
                    ("view_findings", "Can view findings"),
                    ("write_decisions", "Can write decisions"),
                    ("approve_merges", "Can approve merges"),
                    ("manage_findings", "Can manage findings"),
                    ("manage_lifecycle", "Can manage Computer lifecycle"),
                    ("manage_client_policy", "Can manage client policy"),
                    ("manage_catalog", "Can manage software catalog"),
                    ("manage_collectors", "Can manage collectors"),
                    ("manage_sources", "Can manage sources"),
                    ("manage_secrets", "Can manage secrets"),
                    ("manage_users", "Can manage Operations users"),
                    ("manage_taxonomy", "Can manage reference taxonomy"),
                    ("run_queries", "Can run saved queries"),
                    ("view_restricted_evidence", "Can view restricted source evidence"),
                ),
            },
        ),
        migrations.RunPython(grant_lifecycle_permission, migrations.RunPython.noop),
    ]
