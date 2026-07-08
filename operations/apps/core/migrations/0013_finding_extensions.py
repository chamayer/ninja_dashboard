"""Migration 0013 — finding type extensions + finding extensions.

FindingType gains: finding_class, source_module, auto_resolvable
Finding gains: condition_key, confidence, last_detected_at, client FK,
               unique constraint on active condition_key

Seeds finding_class / source_module on the 10 existing types and
inserts 6 new finding types (entity + admin).
"""

from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


EXISTING_TYPE_UPDATES = {
    "unlinked_external_identity":    ("entity", "identity.resolver"),
    "stale_collector_binding":       ("entity", "queue.health"),
    "unauthorized_rmm":              ("entity", "inventory.software"),
    "unauthorized_av":               ("entity", "inventory.software"),
    "unauthorized_remote_access":    ("entity", "inventory.software"),
    "install_path_suspicious":       ("entity", "inventory.software"),
    "rare_recent":                   ("entity", "inventory.software"),
    "eol_runtime":                   ("entity", "inventory.software"),
    "suspicious_name":               ("entity", "inventory.software"),
    "multi_av_conflict":             ("entity", "inventory.software"),
}

NEW_FINDING_TYPES = (
    # (name, default_severity, description, finding_class, source_module, auto_resolvable)
    ("device_missing_from_source",  "high",   "Device disappeared from source API",     "entity", "ninja.ingest",       True),
    ("device_long_offline",         "medium", "Device offline for extended period",      "entity", "ninja.ingest",       True),
    ("device_stale_data",           "low",    "Device data not refreshed recently",      "entity", "ninja.ingest",       True),
    ("missing_required_platform",   "high",   "Required coverage platform not observed", "entity", "platform.evaluator", True),
    ("software_queue_stalled",      "high",   "Software refresh queue stalled",          "admin",  "queue.health",       False),
    ("identity_resolution_pending", "low",    "Devices awaiting identity resolution",    "admin",  "identity.resolver",  False),
)


def seed_finding_extensions(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")

    for name, (finding_class, source_module) in EXISTING_TYPE_UPDATES.items():
        FindingType.objects.filter(name=name).update(
            finding_class=finding_class,
            source_module=source_module,
            auto_resolvable=True,
        )

    for name, severity, description, finding_class, source_module, auto_resolvable in NEW_FINDING_TYPES:
        FindingType.objects.update_or_create(
            name=name,
            defaults={
                "default_severity": severity,
                "description": description,
                "finding_class": finding_class,
                "source_module": source_module,
                "auto_resolvable": auto_resolvable,
                "runbook_path": f"docs/runbooks/{name}.md",
            },
        )


def unseed_finding_extensions(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name__in=[n for n, *_ in NEW_FINDING_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0012_lifecycle_columns"),
    ]

    operations = [
        # ── FindingType additions ─────────────────────────────────────
        migrations.AddField(
            model_name="findingtype",
            name="finding_class",
            field=models.CharField(
                choices=[("entity", "Entity"), ("admin", "Admin")],
                default="entity",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="source_module",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="auto_resolvable",
            field=models.BooleanField(default=True),
        ),

        # ── Finding additions ─────────────────────────────────────────
        migrations.AddField(
            model_name="finding",
            name="client",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="findings",
                to="operations.client",
            ),
        ),
        migrations.AddField(
            model_name="finding",
            name="condition_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="finding",
            name="confidence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("possible", "Possible"),
                    ("probable", "Probable"),
                    ("confirmed", "Confirmed"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="finding",
            name="last_detected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),

        # Unique constraint: one open/acked finding per condition_key per tenant
        migrations.AddConstraint(
            model_name="finding",
            constraint=models.UniqueConstraint(
                condition=models.Q(condition_key__gt="")
                & models.Q(status__in=["open", "acknowledged"]),
                fields=["tenant", "condition_key"],
                name="uq_findings_active_condition_key",
            ),
        ),

        # ── Seed data ─────────────────────────────────────────────────
        migrations.RunPython(seed_finding_extensions, unseed_finding_extensions),
    ]
