"""Migration 0035 — device_long_offline → device_offline (generic, source-agnostic).

`device_long_offline` was Ninja-specific by implementation despite its
device-scoped name — it fired when Ninja's `lastContact` was >7 days old,
ignoring whether other sources (S1/LMI/SC) were still reaching the device.
That's a per-source concern (Ninja agent broken) mislabeled as
device-level state. Generalize:

  * `stale_required_platform` now uses `last_contact_at` (BLUEPRINT E.6)
    so "Ninja agent silent while S1/LMI still contacting" surfaces as a
    per-source stale finding with `platform=Ninja` in details.
  * `device_offline` (new type) fires ONLY when EVERY agent has
    lost contact — real device-level state.

Migration:
  * Seed `device_offline` finding_type.
  * Resolve all open `device_long_offline` findings — the evaluator's
    next run re-emits `device_offline` for devices that meet the
    stricter criterion, and per-source `stale_required_platform` for
    devices where only one source is silent.
  * Leave `device_long_offline` finding_type row in place (historical).
"""

from __future__ import annotations

from django.db import connection, migrations


def add_and_resolve(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.get_or_create(
        name="device_offline",
        defaults={
            "default_severity": "medium",
            "finding_class": "entity",
            "source_module": "platform.evaluator",
            "auto_resolvable": True,
            "description": (
                "Every agent on the device has lost contact past the "
                "offline threshold. True device-level unreachability — "
                "action is to recover the device, not any single agent."
            ),
        },
    )
    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = NOW()
            FROM operations.finding_types ft
            WHERE ft.id = f.finding_type_id
              AND ft.name = 'device_long_offline'
              AND f.status IN ('open', 'acknowledged')
            """
        )


def reverse(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="device_offline").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0034_remove_cross_client_conflict"),
    ]

    operations = [
        migrations.RunPython(add_and_resolve, reverse),
    ]
