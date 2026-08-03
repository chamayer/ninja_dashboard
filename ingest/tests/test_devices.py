from datetime import datetime, timezone

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
