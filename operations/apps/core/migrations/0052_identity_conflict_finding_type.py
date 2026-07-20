"""Migration 0052 — seed identity_conflict FindingType (ADR-0005 slice 3).

Per ADR-0005: hostname-only matches never merge. When two Devices in the
same client share a hostname with no strong corroborating identifier
(serial / vm_uuid / MAC / install token), the situation is a conflict —
surfaced as an operator-visible Finding rather than silently reconciled.

**Coexistence with `identity_candidates`:**

- `operations.identity_candidates` remains as the raw ingest-side signal
  (a row per ambiguous observation for operator review).
- This Finding is the operator-visible lens on top of the same signal
  and lives in the standard findings queue with severity + lifecycle.
  Emission is triggered from the resolver's existing candidate-creation
  path in `ingest/identity/resolver.py::_maybe_create_candidate`.

**Category:** identity (assigned when the `identity` FindingCategory
exists; otherwise leaves category NULL — data-driven per project rules).
"""

from __future__ import annotations

from django.db import migrations


def seed_identity_conflict(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")

    category = FindingCategory.objects.filter(name="identity").first()

    FindingType.objects.update_or_create(
        name="identity_conflict",
        defaults={
            "default_severity": "high",
            "finding_class": "entity",
            "category": category,
            "source_module": "identity.resolver",
            "auto_resolvable": False,
            "description": (
                "Two or more devices in the same client share a hostname "
                "without any strong corroborating identifier (serial / "
                "vm_uuid / MAC / install token). Per ADR-0005, hostname "
                "alone never merges — the candidates stay as separate "
                "device rows and this finding surfaces the conflict for "
                "operator resolution. See operations.identity_candidates "
                "for the raw signal."
            ),
        },
    )


def unseed_identity_conflict(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="identity_conflict").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0051_layered_entities_backfill"),
    ]

    operations = [
        migrations.RunPython(seed_identity_conflict, unseed_identity_conflict),
    ]
