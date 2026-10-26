from datetime import datetime, timezone
import inspect
from types import SimpleNamespace

import pytest

devices = pytest.importorskip(
    "ingest.core.devices", reason="ingest HTTP dependencies ship in the image"
)


def test_vm_measurements_preserve_direct_os_boot_time() -> None:
    os_boot = datetime(2026, 8, 1, 9, tzinfo=timezone.utc)
    hypervisor_boot = datetime(2026, 8, 1, 8, 55, tzinfo=timezone.utc)
    canonical: dict[str, object] = {"last_boot_time_at": os_boot.isoformat()}

    devices._add_vm_canonical_measurements(
        canonical,
        {
            "power_state": "POWERED_ON",
            "parent_device_id": 7,
            "hypervisor_reported_boot_time": hypervisor_boot,
        },
    )

    assert canonical == {
        "last_boot_time_at": os_boot.isoformat(),
        "power_state": "powered_on",
        "parent_ninja_id": 7,
        "hypervisor_reported_boot_time_at": hypervisor_boot.isoformat(),
    }


def test_vmware_guest_uses_organization_scoped_vmx_path_identity() -> None:
    identity = devices._ninja_observation_identity(
        {
            "id": 9215,
            "organization_id": 42,
            "entity_type": "vm.guest",
            "vmx_path": " [NVMe-82-SAN] 82Livigent01/82Livigent01.vmx ",
        }
    )

    assert identity == {
        "external_namespace": "vmware_guest_vmx_path",
        "parent_external_namespace": "organization",
        "parent_external_id": "42",
        "external_id": "[nvme-82-san] 82livigent01/82livigent01.vmx",
        "entity_key": "vmx:42:[nvme-82-san] 82livigent01/82livigent01.vmx",
        "vmx_path": " [NVMe-82-SAN] 82Livigent01/82Livigent01.vmx ",
        "vmx_path_normalized": "[nvme-82-san] 82livigent01/82livigent01.vmx",
    }


def test_vmware_guest_without_vmx_path_keeps_ninja_node_identity() -> None:
    identity = devices._ninja_observation_identity(
        {
            "id": 9215,
            "organization_id": 42,
            "entity_type": "vm.guest",
            "vmx_path": "",
        }
    )

    assert identity == {
        "external_namespace": "device",
        "parent_external_namespace": "",
        "parent_external_id": "",
        "external_id": "9215",
        "entity_key": "9215",
        "vmx_path": "",
        "vmx_path_normalized": "",
    }


def test_non_guest_keeps_ninja_node_identity_even_with_file_path() -> None:
    identity = devices._ninja_observation_identity(
        {
            "id": 6159,
            "organization_id": 42,
            "entity_type": "vm.host",
            "vmx_path": "[NVMe-82-SAN] VMware11/VMware11.vmx",
        }
    )

    assert identity["external_namespace"] == "device"
    assert identity["external_id"] == "6159"


def test_normal_device_collection_does_not_write_legacy_snapshots() -> None:
    assert "ninja_core.device_snapshots" not in inspect.getsource(devices._run)


def test_ninja_devices_publish_the_shared_source_row_contract(monkeypatch) -> None:
    observed_at = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        devices,
        "load_source_binding",
        lambda _binding_id: SimpleNamespace(platform="Ninja"),
    )
    monkeypatch.setattr(
        devices, "_ninja_organizations", lambda: {"7": {"name": "Acme"}}
    )

    def fake_write(source, rows, batch_id, timestamp, **kwargs):
        captured.update(
            source=source,
            rows=rows,
            batch_id=batch_id,
            timestamp=timestamp,
            kwargs=kwargs,
        )
        return len(rows)

    monkeypatch.setattr(devices, "write_observations", fake_write)
    device_rows = [
        {
            "id": 41,
            "uid": "node-41",
            "organization_id": 7,
            "node_class": "WINDOWS_WORKSTATION",
            "is_virtual_machine": False,
            "system_name": "nycd-pc01",
            "display_name": "NYCD-PC01",
            "dns_name": "nycd-pc01.example.test",
            "serial_number": "SERIAL-41",
            "mac_addresses": ["AA-BB-CC-DD-EE-FF"],
            "os_name": "Windows 11",
            "os_build_number": "26100",
            "os_release_id": "24H2",
        }
    ]
    snapshot_rows = [
        {
            "device_id": 41,
            "offline": False,
            "last_contact": observed_at,
            "last_boot": None,
            "needs_reboot": False,
            "needs_reboot_reasons": None,
            "last_user": "operator",
            "maintenance_status": None,
            "maintenance_start": None,
            "maintenance_end": None,
        }
    ]

    written = devices._write_ninja_observations(
        device_rows,
        snapshot_rows,
        observed_at,
        raw_by_id={41: {"system": {}}},
    )

    assert written == 2
    device_row, organization_row = captured["rows"]
    assert device_row["entity_type"] == "agent.rmm"
    assert device_row["platform_group_id"] == "7"
    assert device_row["container_external_id"] == "7"
    assert device_row["canonical_extra"]["ninja_node_id"] == "41"
    assert device_row["is_online"] is True
    assert organization_row == {
        "_org_only": True,
        "container_external_namespace": "organization",
        "container_external_id": "7",
        "platform_group_id": "7",
        "platform_group_name": "Acme",
    }
