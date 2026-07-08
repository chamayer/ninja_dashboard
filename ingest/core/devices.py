"""Devices ingest.

Source: GET /v2/devices-detailed (paginate_after).

Two writes per device per run:
  - ninja_core.devices            (upsert on id; slowly-changing dim)
  - ninja_core.device_snapshots   (insert per snapshot_at; volatile state)

`first_seen_at` on devices is deliberately NOT in the row dict — the
column DEFAULT now() handles the initial insert, and on conflict
we don't overwrite it. `last_seen_at` IS in the dict so each upsert
bumps it.
"""

from __future__ import annotations

import logging
from datetime import datetime

import psycopg
from psycopg.types.json import Json

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log
from ingest.util import ninja_epoch_to_dt

log = logging.getLogger(__name__)


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (devices_upserted, snapshots_inserted)."""
    with run_log("core.devices") as stats:
        device_rows: list[dict] = []
        snapshot_rows: list[dict] = []

        for d in client.paginate_after("/devices-detailed"):
            os_data = d.get("os") or {}
            system_data = d.get("system") or {}
            maintenance = d.get("maintenance") or {}

            device_rows.append({
                "id":                  d["id"],
                "uid":                 d["uid"],
                "organization_id":     d["organizationId"],
                "location_id":         d.get("locationId"),
                "policy_id":           d.get("policyId"),
                "role_policy_id":      d.get("rolePolicyId"),
                "node_class":          d["nodeClass"],
                "approval_status":     d.get("approvalStatus", "APPROVED"),
                "display_name":        d.get("displayName"),
                "system_name":         d.get("systemName"),
                "dns_name":            d.get("dnsName"),
                "netbios_name":        d.get("netbiosName"),
                "os_name":             os_data.get("name"),
                "os_architecture":     os_data.get("architecture"),
                "os_build_number":     os_data.get("buildNumber"),
                "os_release_id":       os_data.get("releaseId"),
                "serial_number":       system_data.get("serialNumber"),
                "manufacturer":        system_data.get("manufacturer"),
                "model":               system_data.get("model"),
                "chassis_type":        system_data.get("chassisType"),
                "is_virtual_machine":  system_data.get("virtualMachine"),
                "total_memory_bytes":  system_data.get("totalPhysicalMemory"),
                "public_ip":           d.get("publicIP"),
                "ip_addresses":        d.get("ipAddresses"),
                "mac_addresses":       d.get("macAddresses"),
                "tags":                d.get("tags"),
                "created_at_ninja":    ninja_epoch_to_dt(d.get("created")),
                "data":                Json(d),
                "last_seen_at":        snapshot_at,
                "is_current":          True,
                "missing_since":       None,
            })

            snapshot_rows.append({
                "snapshot_at":          snapshot_at,
                "device_id":            d["id"],
                "offline":              d.get("offline"),
                "last_contact":         ninja_epoch_to_dt(d.get("lastContact")),
                "last_boot":            ninja_epoch_to_dt(os_data.get("lastBootTime")),
                "needs_reboot":         os_data.get("needsReboot"),
                # needs_reboot_reasons is not on /devices-detailed's os{}.
                # Will be populated from /v2/queries/device-health later.
                "needs_reboot_reasons": None,
                "last_user":            d.get("lastLoggedInUser"),
                "maintenance_status":   maintenance.get("status"),
                "maintenance_start":    ninja_epoch_to_dt(maintenance.get("start")),
                "maintenance_end":      ninja_epoch_to_dt(maintenance.get("end")),
                "data":                 Json(d),
            })

        log.info("Fetched %d devices", len(device_rows))
        if not device_rows:
            raise RuntimeError(
                "Device ingest returned zero devices; refusing to mark "
                "existing devices as missing"
            )

        current_ids = [row["id"] for row in device_rows]
        with db.transaction() as cur:
            dev_count = db.upsert(
                cur, "ninja_core.devices", device_rows, conflict_keys=["id"],
            )
            snap_count = db.upsert(
                cur,
                "ninja_core.device_snapshots",
                snapshot_rows,
                conflict_keys=["snapshot_at", "device_id"],
            )
            missing_count = _mark_missing_devices(cur, current_ids, snapshot_at)
            _sync_operations_device_links(cur, current_ids, snapshot_at)

        _refresh_active_devices_view()
        stats["rows_upserted"] = dev_count
        stats["rows_inserted"] = snap_count
        stats["devices_marked_missing"] = missing_count
        log.info(
            "Upserted %d devices, inserted %d snapshots, marked %d missing",
            dev_count, snap_count, missing_count,
        )
        return dev_count, snap_count


def _mark_missing_devices(cur: object, current_ids: list[int], snapshot_at: datetime) -> int:
    """Mark devices absent from a successful full Ninja device pull as non-current.

    We keep the device row and historical snapshots, but current dashboards
    should not count devices no longer returned by Ninja.
    """
    cur.execute(
        """
        UPDATE ninja_core.devices
        SET is_current = FALSE,
            missing_since = COALESCE(missing_since, %(snapshot_at)s)
        WHERE is_current = TRUE
          AND NOT (id = ANY(%(current_ids)s))
        """,
        {"snapshot_at": snapshot_at, "current_ids": current_ids},
    )
    return cur.rowcount


def _sync_operations_device_links(cur: object, current_ids: list[int], snapshot_at: datetime) -> None:
    """Keep operations.device_links.last_seen_at and missing_since in sync with the Ninja pull."""
    cur.execute("SET LOCAL operations.tenant_id = 1")
    ids_text = [str(i) for i in current_ids]
    params = {"snapshot_at": snapshot_at, "ids": ids_text}
    cur.execute(
        """
        UPDATE operations.device_links dl
        SET last_seen_at = %(snapshot_at)s
        FROM operations.sources s
        WHERE dl.source_id = s.id AND s.name = 'Ninja'
          AND dl.external_id = ANY(%(ids)s)
          AND dl.missing_since IS NULL
        """,
        params,
    )
    cur.execute(
        """
        UPDATE operations.device_links dl
        SET missing_since = %(snapshot_at)s
        FROM operations.sources s
        WHERE dl.source_id = s.id AND s.name = 'Ninja'
          AND NOT (dl.external_id = ANY(%(ids)s))
          AND dl.missing_since IS NULL
        """,
        params,
    )
    cur.execute(
        """
        UPDATE operations.device_links dl
        SET missing_since = NULL
        FROM operations.sources s
        WHERE dl.source_id = s.id AND s.name = 'Ninja'
          AND dl.external_id = ANY(%(ids)s)
          AND dl.missing_since IS NOT NULL
        """,
        params,
    )


def _refresh_active_devices_view() -> None:
    """Refresh materialized active-device inventory after current flags change."""
    try:
        with db.transaction() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW ninja_core.v_active_devices")
        log.info("Refreshed materialized view ninja_core.v_active_devices")
    except (psycopg.errors.UndefinedTable, psycopg.errors.WrongObjectType):
        log.info(
            "ninja_core.v_active_devices is not materialized yet; "
            "skipping refresh"
        )
