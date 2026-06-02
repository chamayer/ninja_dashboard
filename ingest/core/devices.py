"""Devices ingest.

Source: GET /v2/devices-detailed (paginate_after).

Two writes per device per run:
  - ninja_core.devices: upsert (slowly-changing dimension). Promoted
    columns: organization_id, location_id, policy_id, node_class,
    approval_status, names, OS fields, system/asset fields, network,
    tags. Everything else lives in `data jsonb`.
  - ninja_core.device_snapshots: append (observed state at snapshot_at).
    Volatile fields: offline, last_contact, last_boot, needs_reboot,
    needs_reboot_reasons (text[] — promoted from the OS payload; exact
    source field TBD when wiring, may live in /devices-detailed os.* or
    /v2/queries/device-health), last_user, maintenance_*.
"""

from datetime import datetime

from ingest.ninja_client import NinjaClient


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (devices_upserted, snapshots_inserted)."""
    raise NotImplementedError
