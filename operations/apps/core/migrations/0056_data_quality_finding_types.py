"""Migration 0056 — seed data-quality FindingTypes.

Per the "nothing hidden or silently ignored" rule
(`memory/feedback_nothing_hidden.md`, 2026-07-20). Three silent
filters in the ingest pipeline that need operator-visible surfaces:

- **`placeholder_serial`** — the resolver's `is_usable_serial()`
  gate silently prevents placeholder / filler serials
  ('None', 'Default string', 'System Serial Number', repeated-char
  fillers, etc.) from driving identity matches. Correct behavior,
  but the operator never learns the device has a bad serial.
- **`shared_serial`** — two or more devices in the same client
  share a canonical_serial. Formerly surfaced only on the retired
  `identity_candidates_list` admin page (0.68.0).
- **`unmatched_source_group`** — observation groups that failed to
  resolve to any device (`operations.unmatched_source_groups`
  status='pending'). Formerly surfaced only as a summary count on
  the retired admin page; only individual visibility was via ingest
  logs.

Emission is wired into the resolver's `_sync_device_attributes`
sweep in a follow-up code change; this migration only seeds the
types.
"""

from __future__ import annotations

from django.db import migrations


_SEEDS = [
    (
        "placeholder_serial",
        "high",
        "entity",
        "identity",
        "identity.resolver",
        True,
        "Device has a placeholder / filler canonical_serial "
        "(e.g. 'None', 'Default string', 'System Serial Number', "
        "'00000000') and thus cannot be used for cross-source "
        "identity correlation. The resolver correctly ignores such "
        "serials for matching; this finding surfaces the affected "
        "devices so operators can correct or acknowledge the data "
        "quality gap.",
    ),
    (
        "shared_serial",
        "high",
        "entity",
        "identity",
        "identity.resolver",
        True,
        "Two or more devices in the same client share a "
        "canonical_serial. Serial should be unique per physical "
        "machine; sharing indicates either a data-quality issue "
        "(clone / template / misread) or a genuine misidentification. "
        "Operator resolution: investigate the affected devices "
        "(often a merge candidate; see the generic device_merge "
        "action) or correct the serial value.",
    ),
    (
        "unmatched_source_group",
        "medium",
        "admin",
        "identity",
        "identity.resolver",
        True,
        "A source observation could not be resolved to any device "
        "and sits in operations.unmatched_source_groups with "
        "status='pending'. Formerly visible only as a summary count "
        "on the retired identity admin page; now surfaced per group "
        "so operators can act on each.",
    ),
]


def seed_data_quality_types(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")

    for name, severity, klass, category_name, source_module, auto, description in _SEEDS:
        category = FindingCategory.objects.filter(name=category_name).first()
        FindingType.objects.update_or_create(
            name=name,
            defaults={
                "default_severity": severity,
                "finding_class": klass,
                "category": category,
                "source_module": source_module,
                "auto_resolvable": auto,
                "description": description,
            },
        )


def unseed_data_quality_types(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(
        name__in=[name for name, *_ in _SEEDS],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0055_layer_field_history_triggers"),
    ]

    operations = [
        migrations.RunPython(seed_data_quality_types, unseed_data_quality_types),
    ]
