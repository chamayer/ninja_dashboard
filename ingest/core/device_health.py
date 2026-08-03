"""Device health ingest.

Source: GET /v2/queries/device-health

This endpoint gives one compact current-health row per device, including
pending reboot reason and Ninja's summary patch counts. We store it as a
snapshot so we can compare Ninja summary counts with our patch facts
without replacing the existing patch-count source yet.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Json

from ingest import db
from ingest.core.devices import (
    INTERNAL_COLLECTOR_INSTANCE_ID,
    NINJA_SOURCE_BINDING_ID,
)
from ingest.ninja_client import NinjaClient
from ingest.normalize import entity_type_for_node_class
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.observations import write_current_rows
from ingest.runlog import run_log

log = logging.getLogger(__name__)

_TENANT_ID = 1
NINJA_HEALTH_EXTERNAL_NAMESPACE = "device-health"
NINJA_HEALTH_SNAPSHOT_SCOPE = "Ninja.device-health"


def run(client: NinjaClient, snapshot_at: datetime) -> int:
    """Fetch device health rows. Returns snapshots upserted."""
    with run_log("core.device_health") as stats:
        known_devices = _fetch_known_devices()
        rows: list[dict[str, Any]] = []
        raw_by_id: dict[int, dict[str, Any]] = {}
        unknown_count = 0

        for rec in client.paginate_cursor("/queries/device-health"):
            device_id = rec.get("deviceId")
            if device_id not in known_devices:
                unknown_count += 1
                continue
            raw_by_id[device_id] = rec
            rows.append(_to_row(rec, snapshot_at))

        if not rows:
            raise RuntimeError(
                "Device-health ingest returned zero known devices; refusing "
                "to reconcile current evidence"
            )

        with db.transaction() as cur:
            count = db.upsert(
                cur,
                "ninja_core.device_health_snapshots",
                rows,
                conflict_keys=["snapshot_at", "device_id"],
            )
        _refresh_latest_health_view()
        observation_count = _write_health_observations(
            rows,
            raw_by_id,
            known_devices,
            snapshot_at,
        )

        stats["rows_upserted"] = count
        stats["rows_inserted"] = observation_count
        log.info(
            "Upserted %d device health snapshots, wrote %d shadow observations "
            "and ignored %d unknown devices",
            count,
            observation_count,
            unknown_count,
        )
        return count


def _fetch_known_devices() -> dict[int, str]:
    with db.transaction() as cur:
        cur.execute("SELECT id, node_class FROM ninja_core.devices")
        return {row[0]: row[1] for row in cur.fetchall()}


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _to_row(rec: dict[str, Any], snapshot_at: datetime) -> dict[str, Any]:
    return {
        "snapshot_at": snapshot_at,
        "device_id": rec["deviceId"],
        "pending_reboot_reason": _blank_to_none(rec.get("pendingRebootReason")),
        "failed_os_patches_count": rec.get("failedOSPatchesCount"),
        "pending_os_patches_count": rec.get("pendingOSPatchesCount"),
        "failed_software_patches_count": rec.get("failedSoftwarePatchesCount"),
        "pending_software_patches_count": rec.get("pendingSoftwarePatchesCount"),
        "alert_count": rec.get("alertCount"),
        "active_job_count": rec.get("activeJobCount"),
        "health_status": rec.get("healthStatus"),
        "active_threats_count": rec.get("activeThreatsCount"),
        "quarantined_threats_count": rec.get("quarantinedThreatsCount"),
        "blocked_threats_count": rec.get("blockedThreatsCount"),
        "critical_vulnerability_count": rec.get("criticalVulnerabilityCount"),
        "high_vulnerability_count": rec.get("highVulnerabilityCount"),
        "medium_vulnerability_count": rec.get("mediumVulnerabilityCount"),
        "low_vulnerability_count": rec.get("lowVulnerabilityCount"),
        "installation_issues_count": rec.get("installationIssuesCount"),
        "offline": rec.get("offline"),
        "parent_offline": rec.get("parentOffline"),
        "products_installation_statuses": Json(
            rec.get("productsInstallationStatuses") or {}
        ),
        "data": Json(rec),
    }


def _canonical_health(row: dict[str, Any], entity_type: str) -> dict[str, Any]:
    products = row["products_installation_statuses"]
    if hasattr(products, "obj"):
        products = products.obj
    return {
        "platform": "Ninja",
        "entity_type": entity_type,
        "pending_reboot_reason": row["pending_reboot_reason"],
        "failed_os_patches_count": row["failed_os_patches_count"],
        "pending_os_patches_count": row["pending_os_patches_count"],
        "failed_software_patches_count": row["failed_software_patches_count"],
        "pending_software_patches_count": row["pending_software_patches_count"],
        "alert_count": row["alert_count"],
        "active_job_count": row["active_job_count"],
        "health_status": row["health_status"],
        "active_threats_count": row["active_threats_count"],
        "quarantined_threats_count": row["quarantined_threats_count"],
        "blocked_threats_count": row["blocked_threats_count"],
        "critical_vulnerability_count": row["critical_vulnerability_count"],
        "high_vulnerability_count": row["high_vulnerability_count"],
        "medium_vulnerability_count": row["medium_vulnerability_count"],
        "low_vulnerability_count": row["low_vulnerability_count"],
        "installation_issues_count": row["installation_issues_count"],
        "offline": row["offline"],
        "parent_offline": row["parent_offline"],
        "products_installation_statuses": products,
    }


def _write_health_observations(
    rows: list[dict[str, Any]],
    raw_by_id: dict[int, dict[str, Any]],
    known_devices: dict[int, str],
    snapshot_at: datetime,
) -> int:
    """Shadow-write health current/history; legacy remains authoritative."""
    batch_id = uuid.uuid4()
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                      FROM pg_attribute
                     WHERE attrelid =
                           'operations.entity_observation_current'::regclass
                       AND attname = 'material_projection_version'
                       AND NOT attisdropped
                )
                """
            )
            if not cur.fetchone()[0]:
                log.info(
                    "Ninja health shadow schema is not available yet; "
                    "legacy write remains authoritative"
                )
                return 0

            run_id, source_instance_id = begin_run(
                cur,
                _TENANT_ID,
                NINJA_SOURCE_BINDING_ID,
                NINJA_HEALTH_SNAPSHOT_SCOPE,
                snapshot_at,
                expected_rows=len(rows),
            )
            device_ids = [str(row["device_id"]) for row in rows]
            cur.execute(
                """
                SELECT dl.external_id, dl.device_id, d.client_id
                  FROM operations.device_links dl
                  JOIN operations.devices d
                    ON d.id = dl.device_id AND d.tenant_id = dl.tenant_id
                  JOIN operations.sources s
                    ON s.id = dl.source_id AND lower(s.name) = 'ninja'
                 WHERE dl.tenant_id = %s
                   AND dl.external_id = ANY(%s)
                """,
                (_TENANT_ID, device_ids),
            )
            link_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

            current_rows: list[dict[str, Any]] = []
            for row in rows:
                external_id = str(row["device_id"])
                linked = link_map.get(external_id)
                ops_device_id, client_id = linked if linked else (None, None)
                entity_type = entity_type_for_node_class(
                    known_devices[row["device_id"]]
                )
                current_rows.append(
                    {
                        "observation_id": uuid.uuid4(),
                        "tenant_id": _TENANT_ID,
                        "source_binding_id": NINJA_SOURCE_BINDING_ID,
                        "source_instance_id": source_instance_id,
                        "last_seen_binding_id": NINJA_SOURCE_BINDING_ID,
                        "external_namespace": NINJA_HEALTH_EXTERNAL_NAMESPACE,
                        "parent_external_namespace": "",
                        "parent_external_id": "",
                        "external_id": external_id,
                        "collector_instance_id": INTERNAL_COLLECTOR_INSTANCE_ID,
                        "client_id": client_id,
                        "device_id": ops_device_id,
                        "entity_type": entity_type,
                        "parent_source_key": "",
                        "entity_key": external_id,
                        "platform": "Ninja",
                        "subplatform": "device-health",
                        "observed_at": snapshot_at,
                        "last_seen_at": snapshot_at,
                        "last_received_at": snapshot_at,
                        "active": True,
                        "withdrawn_at": None,
                        "snapshot_scope": NINJA_HEALTH_SNAPSHOT_SCOPE,
                        "last_snapshot_run_id": run_id,
                        "raw_data": Json(raw_by_id[row["device_id"]]),
                        "canonical_data": Json(_canonical_health(row, entity_type)),
                        "batch_id": batch_id,
                        "collector_version": "",
                        "schema_version": 1,
                    }
                )

            written = write_current_rows(cur, current_rows)
            complete_run(
                cur,
                run_id,
                written,
                is_complete_snapshot=True,
                identity_rows=current_rows,
            )
            reconcile_complete_run(cur, run_id)
            return written
    except Exception:
        log.exception(
            "Ninja health shadow observation write failed; "
            "legacy health snapshot remains authoritative"
        )
        return 0


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
