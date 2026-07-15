"""Migration 0044 — reboot_pending finding type + refresh_derived coordinator
(Track O batch O5).

Adds the 5th patching finding type promised in BLUEPRINT §5.1
(previously parked in 0039 pending v_device.needs_reboot from O1/O3),
and a thin coordinator function so callers can refresh all ops
derived matviews in dependency order in one call.
"""

from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingCategory = apps.get_model("operations", "FindingCategory")

    patching_cat, _ = FindingCategory.objects.get_or_create(
        name="patching",
        defaults={
            "description": "Patch pipeline health per device / per client",
            "display_order": 50,
        },
    )
    FindingType.objects.get_or_create(
        name="reboot_pending",
        defaults={
            "default_severity": "medium",
            "finding_class": "entity",
            "source_module": "platform.patch_findings",
            "auto_resolvable": True,
            "runbook_path": "",
            "description": (
                "Device has a pending reboot flag and hasn't booted in >3 days — "
                "patches installed but not yet fully applied. Only fires for "
                "devices with effective_patching_scope='Included'."
            ),
            "category": patching_cat,
        },
    )


def unseed(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="reboot_pending").delete()


_REFRESH_COORDINATOR_SQL = """
CREATE OR REPLACE FUNCTION operations.refresh_derived()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    -- Dependency order:
    --   1. agent_presence_current — reads raw entity_observations.
    --   2. device_session_current — reads agent_presence_current +
    --      ninja_core.device_snapshots.
    --   3. device_patching_scope_current — reads ninja_core custom
    --      fields + ops.devices; independent of session state, but
    --      cheap to run last for a clean end-state.
    PERFORM operations.refresh_agent_presence_current();
    PERFORM operations.refresh_device_session_current();
    PERFORM operations.refresh_patching_scope_current();
END;
$$;

GRANT EXECUTE ON FUNCTION operations.refresh_derived()
    TO operations_app, ninja_ingest;
"""

_REFRESH_COORDINATOR_REVERSE_SQL = """
DROP FUNCTION IF EXISTS operations.refresh_derived();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0043_patching_scope_layer"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
        migrations.RunSQL(_REFRESH_COORDINATOR_SQL, _REFRESH_COORDINATOR_REVERSE_SQL),
    ]
