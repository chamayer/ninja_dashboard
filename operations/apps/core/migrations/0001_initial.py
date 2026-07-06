from __future__ import annotations

import django.contrib.auth.models
import django.contrib.auth.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def create_operations_schema(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("CREATE SCHEMA IF NOT EXISTS operations")


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_operations_schema, migrations.RunPython.noop),
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("display_name", models.CharField(max_length=200)),
                ("brand_config", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "tenants",
                "ordering": ("display_name",),
            },
        ),
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False, help_text="Designates that this user has all permissions without explicitly assigning them.", verbose_name="superuser status")),
                ("username", models.CharField(error_messages={"unique": "A user with that username already exists."}, help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.", max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name="username")),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                ("email", models.EmailField(max_length=254)),
                ("is_staff", models.BooleanField(default=False, help_text="Designates whether the user can log into this admin site.", verbose_name="staff status")),
                ("is_active", models.BooleanField(default=True, help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts.", verbose_name="active")),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date joined")),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="users", to="operations.tenant")),
            ],
            options={
                "db_table": "users",
                "permissions": (
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
                ),
            },
            managers=[
                ("objects", django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name="UserGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="auth.group")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "user_groups",
            },
        ),
        migrations.CreateModel(
            name="UserPermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("permission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="auth.permission")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "user_permissions",
            },
        ),
        migrations.AddField(
            model_name="user",
            name="groups",
            field=models.ManyToManyField(blank=True, related_name="operations_users", related_query_name="operations_user", through="operations.UserGroup", to="auth.group"),
        ),
        migrations.AddField(
            model_name="user",
            name="user_permissions",
            field=models.ManyToManyField(blank=True, related_name="operations_users", related_query_name="operations_user", through="operations.UserPermission", to="auth.permission"),
        ),
        migrations.AddConstraint(
            model_name="usergroup",
            constraint=models.UniqueConstraint(fields=("tenant", "user", "group"), name="uq_user_groups_tenant_user_group"),
        ),
        migrations.AddConstraint(
            model_name="userpermission",
            constraint=models.UniqueConstraint(fields=("tenant", "user", "permission"), name="uq_user_permissions_tenant_user_permission"),
        ),
    ]
