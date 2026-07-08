"""Migration 0014 — new platform tables.

Creates: coverage_requirements, admin_findings, queue_registry,
         identity_candidates, notification_rules, notification_state,
         notification_events.

Enables RLS (tenant_isolation policy) on all tenant-scoped tables.
Grants SELECT/INSERT/UPDATE/DELETE to operations_app and ninja_ingest.
Seeds existing queues into queue_registry.
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


_TENANT_NEW_TABLES = (
    "coverage_requirements",
    "admin_findings",
    "identity_candidates",
    "notification_rules",
    "notification_state",
    "notification_events",
)

_TENANT_RW_ROLES = ("operations_app", "ninja_ingest")
_TENANT_RO_ROLES = ("operations_readonly", "metabase_ro")

QUEUE_SEEDS = (
    ("software.scheduled", "refresh",    "ninja_core.software_scheduled_queue", "ninja.ingest", 120, 10, 500, "Scheduled per-org software pull"),
    ("software.demand",    "refresh",    "ninja_core.software_demand_queue",    "ninja.ingest",  30,  5, 100, "On-demand operator-triggered software pull"),
    ("software.activity",  "refresh",    "ninja_core.software_activity_queue",  "ninja.ingest",  60, 10, 500, "Activity-triggered per-device software pull"),
    ("identity.resolution","processing", "operations.entity_observations",      "identity.resolver", 120, 0, 0, "Polling resolver for unresolved entity_observations (v1)"),
)


def apply_rls_and_grants(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    for table in _TENANT_NEW_TABLES:
        schema_editor.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('operations.{table}') IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY';
                    EXECUTE 'ALTER TABLE operations.{table} FORCE ROW LEVEL SECURITY';
                    EXECUTE 'DROP POLICY IF EXISTS tenant_isolation ON operations.{table}';
                    EXECUTE 'CREATE POLICY tenant_isolation ON operations.{table}
                        USING (tenant_id = current_setting(''operations.tenant_id'', TRUE)::bigint)';
                    EXECUTE 'ALTER TABLE operations.{table} OWNER TO operations_migrate';
                END IF;
            END $$;
            """
        )
        for role in _TENANT_RW_ROLES:
            schema_editor.execute(
                f"GRANT INSERT, SELECT, UPDATE, DELETE ON operations.{table} TO {role};"
            )
        for role in _TENANT_RO_ROLES:
            schema_editor.execute(
                f"GRANT SELECT ON operations.{table} TO {role};"
            )

    # queue_registry has no tenant_id — no RLS, full access for app + ingest
    schema_editor.execute("ALTER TABLE operations.queue_registry OWNER TO operations_migrate;")
    for role in _TENANT_RW_ROLES:
        schema_editor.execute(
            f"GRANT INSERT, SELECT, UPDATE, DELETE ON operations.queue_registry TO {role};"
        )
    for role in _TENANT_RO_ROLES:
        schema_editor.execute(
            f"GRANT SELECT ON operations.queue_registry TO {role};"
        )


def seed_queue_registry(apps, schema_editor):
    QueueRegistry = apps.get_model("operations", "QueueRegistry")
    for queue_key, queue_type, table_name, owner, max_age, max_fail, max_depth, desc in QUEUE_SEEDS:
        QueueRegistry.objects.update_or_create(
            queue_key=queue_key,
            defaults={
                "queue_type": queue_type,
                "table_name": table_name,
                "owner": owner,
                "enabled": True,
                "max_pending_age_m": max_age,
                "max_failure_count": max_fail,
                "max_depth": max_depth,
                "description": desc,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0013_finding_extensions"),
    ]

    operations = [
        # ── CoverageRequirement ───────────────────────────────────────
        migrations.CreateModel(
            name="CoverageRequirement",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("entity_type", models.CharField(max_length=80)),
                ("platform", models.CharField(blank=True, default="", max_length=80)),
                ("device_scope", models.CharField(default="all", max_length=40)),
                ("severity", models.CharField(choices=[("critical","Critical"),("high","High"),("medium","Medium"),("low","Low"),("info","Info")], default="high", max_length=16)),
                ("gap_after_hours", models.PositiveIntegerField(default=24)),
                ("confidence_probable", models.PositiveIntegerField(default=48)),
                ("confidence_confirmed", models.PositiveIntegerField(default=168)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("client", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="coverage_requirements", to="operations.client")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={"db_table": "coverage_requirements", "ordering": ["entity_type", "platform"]},
        ),

        # ── AdminFinding ──────────────────────────────────────────────
        migrations.CreateModel(
            name="AdminFinding",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("condition_key", models.CharField(max_length=255)),
                ("severity", models.CharField(choices=[("critical","Critical"),("high","High"),("medium","Medium"),("low","Low"),("info","Info")], default="medium", max_length=16)),
                ("status", models.CharField(choices=[("open","Open"),("acknowledged","Acknowledged"),("investigating","Investigating"),("suppressed","Suppressed"),("resolved","Resolved"),("wontfix","Won't fix")], default="open", max_length=24)),
                ("subject_ref", models.JSONField(default=dict)),
                ("details", models.JSONField(default=dict)),
                ("first_detected_at", models.DateTimeField()),
                ("last_detected_at", models.DateTimeField()),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("finding_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="admin_findings", to="operations.findingtype")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={"db_table": "admin_findings"},
        ),
        migrations.AddConstraint(
            model_name="adminfinding",
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=["open", "acknowledged"]),
                fields=["tenant", "condition_key"],
                name="uq_admin_findings_active_condition_key",
            ),
        ),
        migrations.AddIndex(
            model_name="adminfinding",
            index=models.Index(fields=["tenant", "status", "severity"], name="idx_admin_findings_status"),
        ),

        # ── QueueRegistry ─────────────────────────────────────────────
        migrations.CreateModel(
            name="QueueRegistry",
            fields=[
                ("queue_key", models.CharField(max_length=120, primary_key=True, serialize=False)),
                ("queue_type", models.CharField(max_length=16)),
                ("table_name", models.CharField(max_length=120)),
                ("owner", models.CharField(max_length=80)),
                ("enabled", models.BooleanField(default=True)),
                ("max_pending_age_m", models.PositiveIntegerField(default=60)),
                ("max_failure_count", models.PositiveIntegerField(default=5)),
                ("max_depth", models.PositiveIntegerField(default=1000)),
                ("description", models.TextField(blank=True)),
            ],
            options={"db_table": "queue_registry", "ordering": ["queue_key"]},
        ),

        # ── IdentityCandidate ─────────────────────────────────────────
        migrations.CreateModel(
            name="IdentityCandidate",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("confidence", models.CharField(max_length=16)),
                ("signals", models.JSONField(default=dict)),
                ("status", models.CharField(default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_by", models.CharField(blank=True, max_length=120)),
                ("device_a", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="identity_candidates_a", to="operations.device")),
                ("device_b", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="identity_candidates_b", to="operations.device")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={"db_table": "identity_candidates"},
        ),
        migrations.AddConstraint(
            model_name="identitycandidate",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="pending"),
                fields=["tenant", "device_a", "device_b"],
                name="uq_identity_candidates_pending_pair",
            ),
        ),

        # ── NotificationRule ──────────────────────────────────────────
        migrations.CreateModel(
            name="NotificationRule",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("finding_class", models.CharField(default="entity", max_length=16)),
                ("min_severity", models.CharField(blank=True, default="", max_length=16)),
                ("min_confidence", models.CharField(blank=True, default="", max_length=16)),
                ("match_criteria", models.JSONField(default=dict)),
                ("urgency_hours", models.PositiveIntegerField(blank=True, null=True)),
                ("cooldown_hours", models.PositiveIntegerField(default=24)),
                ("enabled", models.BooleanField(default=True)),
                ("client", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="notification_rules", to="operations.client")),
                ("finding_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="notification_rules", to="operations.findingtype")),
                ("route", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="rules", to="operations.notificationroute")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={"db_table": "notification_rules"},
        ),

        # ── NotificationState ─────────────────────────────────────────
        migrations.CreateModel(
            name="NotificationState",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("fingerprint", models.CharField(max_length=255)),
                ("last_sent_at", models.DateTimeField()),
                ("next_allowed_at", models.DateTimeField()),
                ("send_count", models.PositiveIntegerField(default=1)),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="state_entries", to="operations.notificationrule")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={"db_table": "notification_state"},
        ),
        migrations.AddConstraint(
            model_name="notificationstate",
            constraint=models.UniqueConstraint(
                fields=["tenant", "fingerprint", "rule"],
                name="uq_notification_state_fingerprint_rule",
            ),
        ),

        # ── NotificationEvent ─────────────────────────────────────────
        migrations.CreateModel(
            name="NotificationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("fingerprint", models.CharField(max_length=255)),
                ("channel", models.CharField(max_length=16)),
                ("status", models.CharField(max_length=16)),
                ("payload_ref", models.JSONField(default=dict)),
                ("error", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                ("rule", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="events", to="operations.notificationrule")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="operations.tenant")),
            ],
            options={"db_table": "notification_events"},
        ),
        migrations.AddIndex(
            model_name="notificationevent",
            index=models.Index(fields=["tenant", "sent_at"], name="idx_notif_events_sent_at"),
        ),

        # ── RLS + grants ──────────────────────────────────────────────
        migrations.RunPython(apply_rls_and_grants, migrations.RunPython.noop),

        # ── Seed queue_registry ───────────────────────────────────────
        migrations.RunPython(seed_queue_registry, migrations.RunPython.noop),
    ]
