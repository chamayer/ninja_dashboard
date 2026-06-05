"""Device health ingest.

Source: GET /v2/queries/device-health

This endpoint gives one compact current-health row per device, including
pending reboot reason and Ninja's summary patch counts. We store it as a
snapshot so we can compare Ninja summary counts with our patch facts
without replacing the existing patch-count source yet.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Json

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log

log = logging.getLogger(__name__)


def run(client: NinjaClient, snapshot_at: datetime) -> int:
    """Fetch device health rows. Returns snapshots upserted."""
    with run_log("core.device_health") as stats:
        known_device_ids = _fetch_known_device_ids()
        rows: list[dict[str, Any]] = []

        for rec in client.paginate_cursor("/queries/device-health"):
            device_id = rec.get("deviceId")
            if device_id not in known_device_ids:
                continue
            rows.append(_to_row(rec, snapshot_at))

        if rows:
            with db.transaction() as cur:
                count = db.upsert(
                    cur,
                    "ninja_core.device_health_snapshots",
                    rows,
                    conflict_keys=["snapshot_at", "device_id"],
            )
            _refresh_latest_health_view()
        else:
            count = 0

        stats["rows_upserted"] = count
        log.info("Upserted %d device health snapshots", count)
        return count


def _fetch_known_device_ids() -> set[int]:
    with db.transaction() as cur:
        cur.execute("SELECT id FROM ninja_core.devices")
        return {row[0] for row in cur.fetchall()}


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _to_row(rec: dict[str, Any], snapshot_at: datetime) -> dict[str, Any]:
    return {
        "snapshot_at":                    snapshot_at,
        "device_id":                      rec["deviceId"],
        "pending_reboot_reason":          _blank_to_none(rec.get("pendingRebootReason")),
        "failed_os_patches_count":        rec.get("failedOSPatchesCount"),
        "pending_os_patches_count":       rec.get("pendingOSPatchesCount"),
        "failed_software_patches_count":  rec.get("failedSoftwarePatchesCount"),
        "pending_software_patches_count": rec.get("pendingSoftwarePatchesCount"),
        "alert_count":                    rec.get("alertCount"),
        "active_job_count":               rec.get("activeJobCount"),
        "health_status":                  rec.get("healthStatus"),
        "active_threats_count":           rec.get("activeThreatsCount"),
        "quarantined_threats_count":      rec.get("quarantinedThreatsCount"),
        "blocked_threats_count":          rec.get("blockedThreatsCount"),
        "critical_vulnerability_count":   rec.get("criticalVulnerabilityCount"),
        "high_vulnerability_count":       rec.get("highVulnerabilityCount"),
        "medium_vulnerability_count":     rec.get("mediumVulnerabilityCount"),
        "low_vulnerability_count":        rec.get("lowVulnerabilityCount"),
        "installation_issues_count":      rec.get("installationIssuesCount"),
        "offline":                        rec.get("offline"),
        "parent_offline":                 rec.get("parentOffline"),
        "products_installation_statuses": Json(rec.get("productsInstallationStatuses") or {}),
        "data":                           Json(rec),
    }


def _refresh_latest_health_view() -> None:
    try:
        with db.transaction() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW ninja_core.latest_device_health")
        log.info("Refreshed materialized view ninja_core.latest_device_health")
    except (psycopg.errors.UndefinedTable, psycopg.errors.WrongObjectType):
        log.info(
            "ninja_core.latest_device_health is not materialized yet; "
            "skipping refresh"
        )
