"""Upsert operations.devices from ninja_core.devices.

Idempotent. Keyed on DeviceLink(source=Ninja, external_id=<device.id>) so
Ninja renames update the canonical row without churning.

Requires bootstrap_clients_from_ninja to have run first — devices are
resolved to their canonical Client via ClientLink(source=Ninja,
external_id=<org.id>). Devices for orgs we haven't imported are skipped
(logged so operators can spot the gap).

Runs at container startup from entrypoint.sh as operations_migrate
(SUPERUSER, bypasses RLS). Safe to run manually:

    docker exec ninja-operations python manage.py bootstrap_devices_from_ninja
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.core.models import Client, ClientLink, Device, DeviceLink, Source

TENANT_ID = 1
NINJA_SOURCE_NAME = "Ninja"


def _classify(node_class: str, is_vm: bool) -> str:
    """Map Ninja node_class to Operations DeviceKind."""
    nc = (node_class or "").upper()
    if "VMHOST" in nc or nc.endswith("_HOST"):
        return Device.DeviceKind.HYPERVISOR_HOST
    if "NMS" in nc:
        return Device.DeviceKind.NETWORK_DEVICE
    if is_vm or nc.endswith("_GUEST"):
        # Ninja only reports VMs where its agent is installed, so treat
        # as agented VM. Agentless VMs come from vCenter/HyperV modules.
        return Device.DeviceKind.VM_WITH_AGENT
    return Device.DeviceKind.PHYSICAL


def _canonical_hostname(display_name: str | None, system_name: str | None, dns_name: str | None) -> str:
    for candidate in (display_name, system_name, dns_name):
        if candidate:
            return candidate
    return "(unknown)"


class Command(BaseCommand):
    help = "Upsert Operations devices from ninja_core.devices."

    def handle(self, *args, **options) -> None:
        if connection.vendor != "postgresql":
            self.stdout.write("[bootstrap_devices_from_ninja] non-postgres backend; skipping.")
            return

        try:
            source = Source.objects.get(name=NINJA_SOURCE_NAME)
        except Source.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    "[bootstrap_devices_from_ninja] Ninja source not seeded; skipping."
                )
            )
            return

        # Preload the org_id → Client.id mapping from ClientLinks so we
        # can resolve devices without one query per device.
        org_to_client: dict[str, int] = dict(
            ClientLink.objects.filter(tenant_id=TENANT_ID, source=source).values_list(
                "external_id", "client_id"
            )
        )
        if not org_to_client:
            self.stdout.write(
                self.style.WARNING(
                    "[bootstrap_devices_from_ninja] no ClientLink(source=Ninja) rows; "
                    "run bootstrap_clients_from_ninja first. Skipping."
                )
            )
            return

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, uid, organization_id, node_class, is_virtual_machine,
                       COALESCE(display_name, ''), COALESCE(system_name, ''),
                       COALESCE(dns_name, ''), COALESCE(serial_number, '')
                  FROM ninja_core.devices
                 ORDER BY id
                """
            )
            rows = cursor.fetchall()

        if not rows:
            self.stdout.write("[bootstrap_devices_from_ninja] ninja_core.devices empty.")
            return

        created = updated = unchanged = orphaned = 0
        with transaction.atomic():
            for (
                device_id,
                uid,
                org_id,
                node_class,
                is_vm,
                display_name,
                system_name,
                dns_name,
                serial_number,
            ) in rows:
                client_id = org_to_client.get(str(org_id))
                if client_id is None:
                    orphaned += 1
                    continue

                external_id = str(device_id)
                hostname = _canonical_hostname(display_name, system_name, dns_name)
                kind = _classify(node_class, bool(is_vm))
                vm_uuid = str(uid) if is_vm else ""

                link = (
                    DeviceLink.objects.select_related("device")
                    .filter(tenant_id=TENANT_ID, source=source, external_id=external_id)
                    .first()
                )
                if link is not None:
                    device = link.device
                    dirty_device = False
                    if device.canonical_hostname != hostname:
                        device.canonical_hostname = hostname
                        dirty_device = True
                    if device.canonical_serial != (serial_number or ""):
                        device.canonical_serial = serial_number or ""
                        dirty_device = True
                    if device.canonical_vm_uuid != vm_uuid:
                        device.canonical_vm_uuid = vm_uuid
                        dirty_device = True
                    if device.device_kind != kind:
                        device.device_kind = kind
                        dirty_device = True
                    if device.client_id != client_id:
                        device.client_id = client_id
                        dirty_device = True
                    if dirty_device:
                        device.save(
                            update_fields=[
                                "canonical_hostname",
                                "canonical_serial",
                                "canonical_vm_uuid",
                                "device_kind",
                                "client_id",
                            ]
                        )
                        updated += 1
                    else:
                        unchanged += 1

                    if link.external_name != hostname:
                        link.external_name = hostname
                        link.save(update_fields=["external_name"])
                    continue

                device = Device.objects.create(
                    tenant_id=TENANT_ID,
                    client_id=client_id,
                    canonical_hostname=hostname,
                    canonical_serial=serial_number or "",
                    canonical_vm_uuid=vm_uuid,
                    device_kind=kind,
                )
                DeviceLink.objects.create(
                    tenant_id=TENANT_ID,
                    device=device,
                    source=source,
                    external_id=external_id,
                    external_name=hostname,
                )
                created += 1

        msg = (
            f"[bootstrap_devices_from_ninja] created={created} updated={updated} "
            f"unchanged={unchanged} orphaned={orphaned} total={len(rows)}"
        )
        self.stdout.write(self.style.SUCCESS(msg))
