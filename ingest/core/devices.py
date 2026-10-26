"""Devices ingest.

Source: GET /v2/devices-detailed (paginate_after).

Writes per device per run:
  - ninja_core.devices (bounded current compatibility row)
  - operations.entity_observation_current (authoritative current raw evidence)
  - operations.entity_observation_history (material/presence transitions only)

`first_seen_at` on devices is deliberately NOT in the row dict — the
column DEFAULT now() handles the initial insert, and on conflict
we don't overwrite it. `last_seen_at` IS in the dict so each upsert
bumps it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import psycopg
from psycopg.types.json import Json

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.normalize import (
    entity_type_for_node_class,
    form_factor_for_node_class,
    infer_device_role,
    normalize_mac,
)
from ingest.runlog import run_log
from ingest.source_observations import write_observations
from ingest.sources import load_source_binding
from ingest.util import ninja_epoch_to_dt

log = logging.getLogger(__name__)

_TENANT_ID = 1
NINJA_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
NINJA_DEVICE_EXTERNAL_NAMESPACE = "device"
NINJA_ORG_EXTERNAL_NAMESPACE = "organization"
NINJA_VMWARE_GUEST_VMX_EXTERNAL_NAMESPACE = "vmware_guest_vmx_path"
INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


_SERIAL_PLACEHOLDER_HINTS = (
    "serial number",
    "default string",
    "to be filled",
    "not specified",
    "not applicable",
    "invalid",
    "none",
    "n/a",
)


def _ninja_serial(system_data: dict) -> str | None:
    """Ninja's BIOS serial, unless it is a placeholder (ADR-0032).

    Where Ninja's ``serialNumber`` and ``biosSerialNumber`` differ, SentinelOne
    and ScreenConnect report the BIOS value (all 7 measured agents,
    2026-10-16). A placeholder BIOS value falls back to ``serialNumber``; the
    shared rejection list still decides whether a serial may drive a match.
    """
    bios = (system_data.get("biosSerialNumber") or "").strip()
    system = system_data.get("serialNumber")
    lowered = bios.lower()
    if (
        not bios
        or len(set(lowered)) <= 1
        or any(hint in lowered for hint in _SERIAL_PLACEHOLDER_HINTS)
    ):
        return system
    return bios


def _normalized_vmx_path(value: object) -> str | None:
    """Return a comparison-safe VMware configuration path, if supplied.

    Ninja's VMware guest node ID and ``uid`` change when inventory is
    rediscovered on another host.  Its ``files`` field is a source-reported
    VMX path instead.  A path is source-scoped rather than a universal VM UUID,
    but it is stable enough to identify the same guest across normal host
    movement.  It is intentionally not used for non-VM records or arbitrary
    file values.
    """
    if not isinstance(value, str):
        return None
    path = " ".join(value.split())
    if not path or not path.casefold().endswith(".vmx"):
        return None
    return path.casefold()


def _ninja_observation_identity(record: dict[str, object]) -> dict[str, str]:
    """Build Operations' stable source identity for one Ninja record.

    The raw numeric Ninja node ID remains available in the payload.  Only a
    VMware guest with a valid VMX path receives the path-based source identity;
    all other records retain the established Ninja device identity.
    """
    node_id = str(record["id"])
    if record.get("entity_type") != "vm.guest":
        return {
            "external_namespace": NINJA_DEVICE_EXTERNAL_NAMESPACE,
            "parent_external_namespace": "",
            "parent_external_id": "",
            "external_id": node_id,
            "entity_key": node_id,
            "vmx_path": "",
            "vmx_path_normalized": "",
        }

    vmx_path = record.get("vmx_path")
    normalized_path = _normalized_vmx_path(vmx_path)
    organization_id = str(record.get("organization_id") or "").strip()
    if not normalized_path or not organization_id:
        return {
            "external_namespace": NINJA_DEVICE_EXTERNAL_NAMESPACE,
            "parent_external_namespace": "",
            "parent_external_id": "",
            "external_id": node_id,
            "entity_key": node_id,
            "vmx_path": "",
            "vmx_path_normalized": "",
        }

    return {
        "external_namespace": NINJA_VMWARE_GUEST_VMX_EXTERNAL_NAMESPACE,
        "parent_external_namespace": NINJA_ORG_EXTERNAL_NAMESPACE,
        "parent_external_id": organization_id,
        "external_id": normalized_path,
        # This is intentionally organization-qualified: a shared Ninja source
        # may contain identical path strings for different clients.
        "entity_key": f"vmx:{organization_id}:{normalized_path}",
        "vmx_path": str(vmx_path),
        "vmx_path_normalized": normalized_path,
    }


def _add_vm_canonical_measurements(
    canonical_data: dict[str, object],
    vm_extras: dict[str, object],
) -> None:
    """Add VM measurements without replacing the direct OS boot value."""
    power_state = vm_extras.get("power_state")
    canonical_data["power_state"] = (
        power_state.lower() if isinstance(power_state, str) else None
    )
    canonical_data["parent_ninja_id"] = vm_extras.get("parent_device_id")
    hypervisor_boot = vm_extras.get("hypervisor_reported_boot_time")
    if isinstance(hypervisor_boot, datetime):
        canonical_data["hypervisor_reported_boot_time_at"] = hypervisor_boot.isoformat()


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (devices_upserted, generic_observations_written)."""
    try:
        result = _run(client, snapshot_at)
    except Exception as exc:
        _record_source_run(snapshot_at, ok=False, rows=0, error=str(exc)[:2000])
        raise
    _record_source_run(snapshot_at, ok=True, rows=result[0])
    return result


def _run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    with run_log("core.devices") as stats:
        device_rows: list[dict] = []
        snapshot_rows: list[dict] = []
        # Extra vm-tracking payload fields for the observation writer —
        # stored side-band so we don't try to insert non-existent
        # columns into ninja_core.devices.
        vm_tracking: dict[int, dict[str, object]] = {}
        # Full fetched Ninja API row per device id — side-banded to
        # `_write_ninja_observations` so the observation's `raw_data`
        # carries the actual source payload (was being dropped as `{}`,
        # which broke the Device Detail Raw tab).
        raw_by_id: dict[int, dict] = {}

        for d in client.paginate_after("/devices-detailed"):
            raw_by_id[d["id"]] = d
            os_data = d.get("os") or {}
            system_data = d.get("system") or {}
            maintenance = d.get("maintenance") or {}
            nc = (d.get("nodeClass") or "").upper()
            # Virtualization-related classes carry hypervisor tracking fields.
            # Sourced from operations.node_class_mappings (0119) rather than an
            # inline suffix tuple — 'vm' covers the guest classes and
            # 'hypervisor-host' the host classes.
            if form_factor_for_node_class(nc) in ("vm", "hypervisor-host"):
                vm_tracking[d["id"]] = {
                    "power_state": d.get("powerState"),
                    "parent_device_id": d.get("parentDeviceId"),
                    "hypervisor_reported_boot_time": ninja_epoch_to_dt(
                        d.get("lastBootTime")
                    ),
                }

            device_rows.append(
                {
                    "id": d["id"],
                    "uid": d["uid"],
                    "organization_id": d["organizationId"],
                    "location_id": d.get("locationId"),
                    "policy_id": d.get("policyId"),
                    "role_policy_id": d.get("rolePolicyId"),
                    "node_class": d["nodeClass"],
                    "approval_status": d.get("approvalStatus", "APPROVED"),
                    "display_name": d.get("displayName"),
                    "system_name": d.get("systemName"),
                    "dns_name": d.get("dnsName"),
                    "netbios_name": d.get("netbiosName"),
                    "os_name": os_data.get("name"),
                    "os_architecture": os_data.get("architecture"),
                    "os_build_number": os_data.get("buildNumber"),
                    "os_release_id": os_data.get("releaseId"),
                    # BIOS serial first (ADR-0032): where Ninja's two fields
                    # differ, SentinelOne and ScreenConnect report the BIOS
                    # value (all 7 measured agents, 2026-10-16).
                    "serial_number": _ninja_serial(system_data),
                    "manufacturer": system_data.get("manufacturer"),
                    "model": system_data.get("model"),
                    "chassis_type": system_data.get("chassisType"),
                    "is_virtual_machine": system_data.get("virtualMachine"),
                    "total_memory_bytes": system_data.get("totalPhysicalMemory"),
                    "public_ip": d.get("publicIP"),
                    "ip_addresses": d.get("ipAddresses"),
                    "mac_addresses": d.get("macAddresses"),
                    "tags": d.get("tags"),
                    "created_at_ninja": ninja_epoch_to_dt(d.get("created")),
                    "data": Json(d),
                    "last_seen_at": snapshot_at,
                    "is_current": True,
                    "missing_since": None,
                }
            )

            snapshot_rows.append(
                {
                    "snapshot_at": snapshot_at,
                    "device_id": d["id"],
                    "offline": d.get("offline"),
                    "last_contact": ninja_epoch_to_dt(d.get("lastContact")),
                    "last_boot": ninja_epoch_to_dt(os_data.get("lastBootTime")),
                    "needs_reboot": os_data.get("needsReboot"),
                    # needs_reboot_reasons is not on /devices-detailed's os{}.
                    # Will be populated from /v2/queries/device-health later.
                    "needs_reboot_reasons": None,
                    "last_user": d.get("lastLoggedInUser"),
                    "maintenance_status": maintenance.get("status"),
                    "maintenance_start": ninja_epoch_to_dt(maintenance.get("start")),
                    "maintenance_end": ninja_epoch_to_dt(maintenance.get("end")),
                    "data": Json(d),
                }
            )

        log.info("Fetched %d devices", len(device_rows))
        if not device_rows:
            raise RuntimeError(
                "Device ingest returned zero devices; refusing to mark "
                "existing devices as missing"
            )

        current_ids = [row["id"] for row in device_rows]
        with db.transaction() as cur:
            dev_count = db.upsert(
                cur,
                "ninja_core.devices",
                device_rows,
                conflict_keys=["id"],
            )
            missing_count = _mark_missing_devices(cur, current_ids, snapshot_at)

        obs_count = _write_ninja_observations(
            device_rows,
            snapshot_rows,
            snapshot_at,
            vm_tracking,
            raw_by_id,
        )
        _refresh_active_devices_view()
        _refresh_device_agent_presence_current()
        stats["rows_upserted"] = dev_count
        stats["rows_inserted"] = obs_count
        stats["devices_marked_missing"] = missing_count
        log.info(
            "Upserted %d devices, marked %d missing, wrote %d authoritative entity observations",
            dev_count,
            missing_count,
            obs_count,
        )
        return dev_count, obs_count


def _mark_missing_devices(
    cur: object, current_ids: list[int], snapshot_at: datetime
) -> int:
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


# `_sync_operations_device_links` stood here. It maintained
# `operations.v_device_source_link.last_seen_at` and `missing_since` from the Ninja
# pull, filtered `WHERE s.name = 'Ninja'`, which meant those two columns were
# only ever maintained for one of four sources. Measured before removal: 209
# links reported an agent present that had stopped reporting 6-23 days earlier
# (SentinelOne 137, LogMeIn 65, ScreenConnect 7, Ninja 0), and `last_seen_at`
# was frozen on essentially every non-Ninja link.
#
# Migration 0121 retires the table in favour of a view over
# `entity_source_links`, which
# `operations.sync_entity_source_links_from_observations()` maintains from
# observation evidence for every source. `_write_ninja_observations` below
# already emits that evidence, so this function has no replacement here.


def _sync_operations_device_exemptions(cur: object) -> None:
    """Sync the Ninja 'no av' marker into device_operator_decisions.

    Track O batch O3 moved exemptions from `devices.exemptions` into
    the polymorphic `device_operator_decisions` table (dimension=
    'exemptions'). Preserves the original semantics:
      * marker present → merge {'agent.edr': 'no_av_exempt'} into value
      * marker absent AND stored value['agent.edr']='no_av_exempt'
        → remove the 'agent.edr' key (was ingest-set, cleanup)
      * marker absent AND value['agent.edr'] set to some OTHER reason
        → leave alone (operator-set)
    Then remove now-empty rows so v_device.exemptions collapses to {}.
    """
    cur.execute(
        """
        WITH ninja_state AS (
            -- One row per OPS device — collapse across multiple Ninja
            -- source links per device (legal per BLUEPRINT E.3). If ANY
            -- Ninja link on the device carries the marker, treat it as
            -- present.
            SELECT dl.tenant_id, dl.device_id AS ops_device_id,
                   BOOL_OR(
                     (nd.data -> 'tags')::text ILIKE '%%no av%%'
                     OR COALESCE(p.name, '')  ILIKE '%%no av%%'
                     OR COALESCE(rp.name, '') ILIKE '%%no av%%'
                   ) AS marker_present
            FROM operations.v_device_source_link dl
            JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
            JOIN ninja_core.devices nd ON nd.id::text = dl.external_id
            LEFT JOIN ninja_core.policies p  ON p.id  = nd.policy_id
            LEFT JOIN ninja_core.policies rp ON rp.id = nd.role_policy_id
            GROUP BY dl.tenant_id, dl.device_id
        ),
        computed AS (
            SELECT ns.tenant_id, ns.ops_device_id,
                   CASE
                     WHEN ns.marker_present THEN
                         COALESCE(od.value, '{}'::jsonb)
                             || '{"agent.edr": "no_av_exempt"}'::jsonb
                     WHEN COALESCE(od.value, '{}'::jsonb) ->> 'agent.edr'
                          = 'no_av_exempt' THEN
                         COALESCE(od.value, '{}'::jsonb) - 'agent.edr'
                     ELSE COALESCE(od.value, '{}'::jsonb)
                   END AS new_value
            FROM ninja_state ns
            LEFT JOIN operations.device_operator_decisions od
                ON od.tenant_id = ns.tenant_id
               AND od.device_id = ns.ops_device_id
               AND od.dimension = 'exemptions'
        )
        INSERT INTO operations.device_operator_decisions
            (id, version, tenant_id, device_id, dimension,
             value, reason, set_by, set_at)
        SELECT gen_random_uuid(), 1, c.tenant_id, c.ops_device_id,
               'exemptions', c.new_value,
               'ninja.no_av_exempt sync', 'ninja.ingest', NOW()
        FROM computed c
        WHERE c.new_value <> '{}'::jsonb
        ON CONFLICT ON CONSTRAINT uq_device_operator_decisions_tenant_device_dim
        DO UPDATE SET value = EXCLUDED.value,
                      reason = EXCLUDED.reason,
                      set_by = EXCLUDED.set_by,
                      set_at = NOW()
        """
    )
    # Clean up rows that computed to empty (marker was removed and no
    # operator-set keys remain). Duplicates the CTE from the upsert
    # so the DELETE can join on the same computed new_value.
    cur.execute(
        """
        WITH ninja_state AS (
            -- One row per OPS device — collapse across multiple Ninja
            -- source links per device (legal per BLUEPRINT E.3). If ANY
            -- Ninja link on the device carries the marker, treat it as
            -- present.
            SELECT dl.tenant_id, dl.device_id AS ops_device_id,
                   BOOL_OR(
                     (nd.data -> 'tags')::text ILIKE '%%no av%%'
                     OR COALESCE(p.name, '')  ILIKE '%%no av%%'
                     OR COALESCE(rp.name, '') ILIKE '%%no av%%'
                   ) AS marker_present
            FROM operations.v_device_source_link dl
            JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
            JOIN ninja_core.devices nd ON nd.id::text = dl.external_id
            LEFT JOIN ninja_core.policies p  ON p.id  = nd.policy_id
            LEFT JOIN ninja_core.policies rp ON rp.id = nd.role_policy_id
            GROUP BY dl.tenant_id, dl.device_id
        ),
        computed AS (
            SELECT ns.tenant_id, ns.ops_device_id,
                   CASE
                     WHEN ns.marker_present THEN
                         COALESCE(od.value, '{}'::jsonb)
                             || '{"agent.edr": "no_av_exempt"}'::jsonb
                     WHEN COALESCE(od.value, '{}'::jsonb) ->> 'agent.edr'
                          = 'no_av_exempt' THEN
                         COALESCE(od.value, '{}'::jsonb) - 'agent.edr'
                     ELSE COALESCE(od.value, '{}'::jsonb)
                   END AS new_value
            FROM ninja_state ns
            LEFT JOIN operations.device_operator_decisions od
                ON od.tenant_id = ns.tenant_id
               AND od.device_id = ns.ops_device_id
               AND od.dimension = 'exemptions'
        )
        DELETE FROM operations.device_operator_decisions od
        USING computed c
        WHERE od.tenant_id = c.tenant_id
          AND od.device_id = c.ops_device_id
          AND od.dimension = 'exemptions'
          AND c.new_value = '{}'::jsonb
        """
    )


def sync_operations_device_exemptions() -> None:
    """Apply policy- and tag-based Ninja exemptions during enrichment.

    This deliberately runs after the policy collection rather than in the
    device identity job: policies enrich an already established Computer but
    are not required to establish its identity.
    """
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        _sync_operations_device_exemptions(cur)


def _record_source_run(
    started_at: datetime, ok: bool, rows: int, error: str = ""
) -> None:
    """Record the Ninja source run in operations.run_log (evaluator guard)."""
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
            cur.execute(
                """
                INSERT INTO operations.run_log
                    (id, tenant_id, kind, subject_ref, started_at, ended_at,
                     ok, rows, error)
                VALUES (gen_random_uuid(), %s, 'source.Ninja', '{}'::jsonb,
                        %s, NOW(), %s, %s, %s)
                """,
                (_TENANT_ID, started_at, ok, rows, error),
            )
    except Exception:
        log.exception("operations.run_log write failed — continuing")


def _write_ninja_observations(
    device_rows: list[dict],
    snapshot_rows: list[dict],
    snapshot_at: datetime,
    vm_tracking: dict[int, dict[str, object]] | None = None,
    raw_by_id: dict[int, dict] | None = None,
) -> int:
    """Publish Ninja device evidence through the shared source writer.

    Ninja retains its raw staging tables for its richer domain collectors, but
    Devices enter Operations with the same normalized contract as every other
    source.  The shared writer owns source-link lookup, client attachment,
    identity resolution, history, and snapshot reconciliation.
    """
    if not device_rows:
        return 0

    source = load_source_binding(NINJA_SOURCE_BINDING_ID)
    if source.platform != "Ninja":
        raise RuntimeError("Ninja source binding has an unexpected platform")
    snapshot_by_id = {row["device_id"]: row for row in snapshot_rows}
    organizations = _ninja_organizations()
    source_rows: list[dict] = []
    unknown_classes: dict[str, int] = {}

    for record in device_rows:
        entity_type = entity_type_for_node_class(record["node_class"])
        if entity_type == "unknown":
            node_class = record["node_class"] or ""
            unknown_classes[node_class] = unknown_classes.get(node_class, 0) + 1
        raw = (raw_by_id or {}).get(record["id"]) or {}
        identity = _ninja_observation_identity(
            {
                "id": record["id"],
                "organization_id": record["organization_id"],
                "entity_type": entity_type,
                "vmx_path": raw.get("files"),
            }
        )
        snapshot = snapshot_by_id.get(record["id"], {})
        offline = snapshot.get("offline")
        last_contact = snapshot.get("last_contact")
        last_boot = snapshot.get("last_boot")
        raw_system = raw.get("system") or {}
        organization_id = str(record["organization_id"])
        organization = organizations.get(organization_id, {})
        canonical_extra: dict[str, object] = {
            "node_class": record["node_class"],
            "ninja_organization_id": organization_id,
            "ninja_node_id": str(record["id"]),
            "ninja_node_uid": str(record["uid"]) if record.get("uid") else None,
            "is_vm": record.get("is_virtual_machine"),
            "last_contact_at": last_contact.isoformat() if last_contact else None,
            "offline": offline,
            "last_boot_time_at": last_boot.isoformat() if last_boot else None,
            "needs_reboot": snapshot.get("needs_reboot"),
            "needs_reboot_reasons": snapshot.get("needs_reboot_reasons"),
            "last_user": snapshot.get("last_user"),
            "maintenance_status": snapshot.get("maintenance_status"),
            "maintenance_start_at": (
                snapshot["maintenance_start"].isoformat()
                if snapshot.get("maintenance_start")
                else None
            ),
            "maintenance_end_at": (
                snapshot["maintenance_end"].isoformat()
                if snapshot.get("maintenance_end")
                else None
            ),
            "os_build_number": record["os_build_number"],
            "os_release_id": record["os_release_id"],
            "service_tag": raw.get("serviceTag") or raw_system.get("serviceTag"),
        }
        if identity["vmx_path"]:
            canonical_extra.update(
                {
                    "vmx_path": identity["vmx_path"],
                    "vmx_path_normalized": identity["vmx_path_normalized"],
                    "guest_tools_status": raw.get("toolStatus"),
                    "guest_tools_install_type": raw.get("toolsInstallType"),
                    "guest_tools_version": raw.get("toolsVersion"),
                }
            )
        vm_extras = (vm_tracking or {}).get(record["id"])
        if vm_extras:
            _add_vm_canonical_measurements(canonical_extra, vm_extras)
        hostname = record["system_name"] or record["display_name"] or record["dns_name"]
        source_rows.append(
            {
                "entity_type": entity_type,
                "platform_device_id": str(record["id"]),
                "entity_key": identity["entity_key"],
                "external_namespace": identity["external_namespace"],
                "parent_external_namespace": identity["parent_external_namespace"],
                "parent_external_id": identity["parent_external_id"],
                "external_id": identity["external_id"],
                "container_external_namespace": NINJA_ORG_EXTERNAL_NAMESPACE,
                "container_external_id": organization_id,
                "platform_group_id": organization_id,
                "platform_group_name": organization.get("name") or "",
                "hostname": hostname,
                "serial_number": record["serial_number"],
                "macs": sorted(
                    {
                        m
                        for m in (
                            normalize_mac(value)
                            for value in (record.get("mac_addresses") or [])
                            if isinstance(value, str)
                        )
                        if m
                    }
                ),
                "device_type": infer_device_role(
                    record["os_name"], record["node_class"]
                ),
                "os_name": record["os_name"],
                "domain_name": (
                    record["dns_name"].split(".", 1)[1]
                    if record["dns_name"] and "." in record["dns_name"]
                    else None
                ),
                "is_online": None if offline is None else not offline,
                "last_seen_at": last_contact,
                "canonical_extra": canonical_extra,
                "raw_data": Json(raw),
            }
        )

    for organization_id, organization in organizations.items():
        source_rows.append(
            {
                "_org_only": True,
                "container_external_namespace": NINJA_ORG_EXTERNAL_NAMESPACE,
                "container_external_id": organization_id,
                "platform_group_id": organization_id,
                "platform_group_name": organization.get("name") or "",
            }
        )

    written = write_observations(source, source_rows, uuid.uuid4(), snapshot_at)
    if unknown_classes:
        log.warning("Ninja records with unmapped node_class: %s", unknown_classes)
    return written


def _ninja_organizations() -> dict[str, dict[str, object]]:
    """Read staged org metadata solely for the normalized container rows."""
    with db.transaction() as cur:
        cur.execute("SELECT id, name FROM ninja_core.organizations")
        return {str(row[0]): {"name": row[1] or ""} for row in cur.fetchall()}


def _refresh_device_agent_presence_current() -> None:
    """Refresh presence matviews after Ninja device observations land.

    Refreshes in dependency order: device_agent_presence_current first
    (per-source × device), then device_session_current (per-device
    rollup that reads from device_agent_presence_current). Kept in one
    function so every ingest / resolver caller gets both without
    remembering to invoke each — will be formalized into a refresh
    manifest in Track O batch O5.
    """
    try:
        with db.transaction() as cur:
            cur.execute("SELECT operations.refresh_device_agent_presence_current()")
        log.info("Refreshed materialized view operations.device_agent_presence_current")
    except Exception:
        log.exception("Failed to refresh device_agent_presence_current — continuing")
        return
    try:
        with db.transaction() as cur:
            cur.execute("SELECT operations.refresh_device_session_current()")
        log.info("Refreshed materialized view operations.device_session_current")
    except Exception:
        log.exception("Failed to refresh device_session_current — continuing")


def refresh_patching_scope_current() -> None:
    """Refresh operations.device_patching_scope_current.

    Called from main.py after custom_fields ingest so the matview
    sees fresh Ninja custom_field_values + policies. Depends on
    operations.devices.os_group/device_role too — those are written by
    `ingest.device_cache_projector` (ADR-0012), which runs in the resolver
    cycle, not in this pipeline. Public (no leading underscore) so main.py can
    schedule it directly. Track O batch O4.
    """
    try:
        with db.transaction() as cur:
            cur.execute("SELECT operations.refresh_patching_scope_current()")
        log.info("Refreshed materialized view operations.device_patching_scope_current")
    except Exception:
        log.exception("Failed to refresh device_patching_scope_current — continuing")


def _refresh_active_devices_view() -> None:
    """Refresh materialized active-device inventory after current flags change."""
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
            cur.execute("REFRESH MATERIALIZED VIEW ninja_core.v_active_devices")
        log.info("Refreshed materialized view ninja_core.v_active_devices")
    except (psycopg.errors.UndefinedTable, psycopg.errors.WrongObjectType):
        log.info(
            "ninja_core.v_active_devices is not materialized yet; " "skipping refresh"
        )
