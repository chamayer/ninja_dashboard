"""Migration 0039 — patching finding types (P6) + P7 cutover prep.

P6 additions:
  * `patching` finding category (new row in finding_categories)
  * 4 patch finding types seeded: device_never_patched,
    patching_stalled, patch_failing_repeatedly, patch_approval_backlog
    (all category='patching', source_module='platform.patch_findings')
  * The blueprint's 5th type (reboot_pending) is parked — patch_facts
    doesn't carry a reboot-pending status yet; a follow-up connector
    change lifts it into canonical_data.

P7 cutover prep:
  * `parity_report` table for parity_check.py to write into (per-run
    snapshot of finding counts old-vs-new). Read by the Health page.
  * No enable-notification-rules yet — that's a manual admin step
    after the operator verifies parity, per BLUEPRINT §6.2.
"""

from __future__ import annotations

from django.db import connection, migrations, models


_PATCH_FINDING_TYPES = [
    ("device_never_patched",
     "high", "entity", "platform.patch_findings",
     "Device is under Ninja RMM but has zero INSTALLED patches on record — patching pipeline never completed a cycle."),
    ("patching_stalled",
     "medium", "entity", "platform.patch_findings",
     "No fresh patch-state observation for this device in the last 35 days — Ninja agent may be blocked from scanning."),
    ("patch_failing_repeatedly",
     "high", "entity", "platform.patch_findings",
     "One or more KBs have failed to install ≥3 times on this device — persistent update problem."),
    ("patch_approval_backlog",
     "medium", "entity", "platform.patch_findings",
     "Client has ≥25 APPROVED patches sitting uninstalled across their fleet — approval workflow bottleneck."),
]


def seed(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingCategory = apps.get_model("operations", "FindingCategory")
    FindingType = apps.get_model("operations", "FindingType")

    patching_cat, _ = FindingCategory.objects.get_or_create(
        name="patching",
        defaults={
            "description": "Patch pipeline health per device / per client",
            "display_order": 50,
        },
    )
    for name, severity, klass, module, desc in _PATCH_FINDING_TYPES:
        ft, created = FindingType.objects.get_or_create(
            name=name,
            defaults={
                "default_severity": severity,
                "finding_class": klass,
                "source_module": module,
                "auto_resolvable": True,
                "runbook_path": "",
                "description": desc,
                "category": patching_cat,
            },
        )
        # If it existed (unlikely for these names), update category + module
        if not created:
            ft.source_module = module
            ft.category = patching_cat
            ft.save(update_fields=["source_module", "category"])


def unseed(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")
    FindingType.objects.filter(name__in=[n for n, *_ in _PATCH_FINDING_TYPES]).delete()
    FindingCategory.objects.filter(name="patching").delete()


_PARITY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS operations.parity_report (
    id           bigserial PRIMARY KEY,
    tenant_id    bigint NOT NULL,
    run_at       timestamptz NOT NULL DEFAULT NOW(),
    finding_type text NOT NULL,
    scope_client uuid,
    legacy_count int NOT NULL DEFAULT 0,
    ops_count    int NOT NULL DEFAULT 0,
    delta        int NOT NULL DEFAULT 0,
    note         text
);
CREATE INDEX IF NOT EXISTS parity_report_run_idx ON operations.parity_report (run_at DESC);
CREATE INDEX IF NOT EXISTS parity_report_type_idx ON operations.parity_report (finding_type);
GRANT SELECT ON operations.parity_report TO operations_app, operations_readonly, metabase_ro;
GRANT INSERT ON operations.parity_report TO ninja_ingest, operations_app;
"""

_PARITY_TABLE_REVERSE = "DROP TABLE IF EXISTS operations.parity_report;"


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0038_software_finding_type_fixup"),
    ]

    operations = [
        migrations.RunSQL(_PARITY_TABLE_SQL, _PARITY_TABLE_REVERSE),
        migrations.RunPython(seed, unseed),
    ]
