from datetime import datetime, timezone
import inspect

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
