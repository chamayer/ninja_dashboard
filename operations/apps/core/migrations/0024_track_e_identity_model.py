"""Track E identity model correction.

Ninja is now treated as an aggregation agent that can emit several entity
streams. Canonical device type is only form factor; agent presence lives in
entity observations / agent_presence_current.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models


def remap_device_types(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        Device = apps.get_model("operations", "Device")
        Device.objects.filter(device_type__in=["vm-with-agent", "vm-agentless"]).update(
            device_type="vm"
        )
        return
    schema_editor.execute(
        """
        UPDATE operations.devices
        SET device_type = 'vm'
        WHERE device_type IN ('vm-with-agent', 'vm-agentless')
        """
    )


def reverse_device_types(apps, schema_editor):
    # Deliberately lossy: Track E removes agent-presence from device_type.
    pass


def grant_ingest_link_fields(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "GRANT SELECT, INSERT, UPDATE ON operations.device_links TO ninja_ingest;"
    )


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0023_device_role_exemptions_finding_types"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="device",
            name="lifecycle_status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("offline_aging", "Offline (aging)"),
                    ("pending_cleanup", "Pending cleanup"),
                    ("retired", "Retired"),
                ],
                default="active",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="device",
            name="device_type",
            field=models.CharField(
                choices=[
                    ("physical", "Physical"),
                    ("vm", "VM"),
                    ("hypervisor-host", "Hypervisor host"),
                    ("network-device", "Network device"),
                    ("unknown", "Unknown"),
                ],
                default="unknown",
                max_length=32,
                verbose_name="Type",
            ),
        ),
        migrations.AddField(
            model_name="devicelink",
            name="match_method",
            field=models.CharField(
                choices=[
                    ("serial", "Serial"),
                    ("vm_uuid", "VM UUID"),
                    ("hostname_strict", "Hostname strict"),
                    ("hostname_loose", "Hostname loose"),
                    ("manual", "Manual"),
                    ("promoted", "Promoted"),
                    ("bootstrap", "Bootstrap"),
                ],
                default="bootstrap",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="devicelink",
            name="match_confidence",
            field=models.DecimalField(decimal_places=3, default=1, max_digits=4),
        ),
        migrations.RunPython(remap_device_types, reverse_device_types),
        migrations.RunPython(grant_ingest_link_fields, migrations.RunPython.noop),
    ]
