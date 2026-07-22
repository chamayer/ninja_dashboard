"""Devices ingest.

Source: GET /v2/devices-detailed (paginate_after).

Writes per device per run:
  - ninja_core.devices            (upsert on id; slowly-changing dim)
  - ninja_core.device_snapshots   (insert per snapshot_at; volatile state)
  - operations.entity_observations (agent.rmm observation; idempotent via batch_id hash)

`first_seen_at` on devices is deliberately NOT in the row dict — the
column DEFAULT now() handles the initial insert, and on conflict
we don't overwrite it. `last_seen_at` IS in the dict so each upsert
bumps it.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime

import psycopg
from psycopg.types.json import Json

from ingest import db
from ingest.observations import write_current_rows
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.ninja_client import NinjaClient
from ingest.normalize import (
    entity_type_for_node_class,
    infer_device_role,
    normalize_mac,
    normalize_org_name,
    os_family,
)
from ingest.runlog import run_log
from ingest.util import ninja_epoch_to_dt

log = logging.getLogger(__name__)

_TENANT_ID = 1
NINJA_SOURCE_BINDING_ID      = uuid.UUID("00000000-0000-4000-8000-000000000011")
INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (devices_upserted, snapshots_inserted)."""
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

        for d in client.paginate_after("/devices-detailed"):
            os_data = d.get("os") or {}
            system_data = d.get("system") or {}
            maintenance = d.get("maintenance") or {}
            nc = (d.get("nodeClass") or "").upper()
            if nc.endswith(("_VMM_GUEST", "_VM_GUEST", "_VMM_HOST", "_VM_HOST")):
                vm_tracking[d["id"]] = {
                    "power_state":       d.get("powerState"),
                    "parent_device_id":  d.get("parentDeviceId"),
                    "last_boot_time":    d.get("lastBootTime"),
                }

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
            _sync_operations_device_roles(cur)
            _sync_operations_device_exemptions(cur)

        _refresh_active_devices_view()
        obs_count = _write_ninja_observations(
            device_rows, snapshot_rows, snapshot_at, vm_tracking,
        )
        _refresh_device_agent_presence_current()
        stats["rows_upserted"] = dev_count
        stats["rows_inserted"] = snap_count
        stats["devices_marked_missing"] = missing_count
        log.info(
            "Upserted %d devices, inserted %d snapshots, marked %d missing, wrote %d entity observations",
            dev_count, snap_count, missing_count, obs_count,
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


def _sync_operations_device_roles(cur: object) -> None:
    """Refresh device_role, os_name/os_family, os_group from the Ninja pull.

    device_role is set from explicit signals only (node_class, server OS,
    client OS) — devices with no signal keep their current role, never a
    guessed default.

    The NO-AV exemption from the Ninja marker is synced separately by
    `_sync_operations_device_exemptions()` — Track O batch O3 moved
    exemptions off `devices.exemptions` into the polymorphic
    `device_operator_decisions` table (dimension='exemptions').
    """
    cur.execute(
        """
        UPDATE operations.devices d
        SET device_role = CASE
                WHEN UPPER(nd.node_class) LIKE '%%SERVER%%' THEN 'server'
                WHEN UPPER(nd.node_class) LIKE '%%WORKSTATION%%' THEN 'workstation'
                WHEN UPPER(nd.node_class) = 'MAC' THEN 'workstation'
                WHEN LOWER(COALESCE(nd.os_name, '')) LIKE '%%server%%' THEN 'server'
                WHEN LOWER(COALESCE(nd.os_name, '')) LIKE '%%windows%%' THEN 'workstation'
                WHEN LOWER(COALESCE(nd.os_name, '')) LIKE '%%macos%%'
                  OR LOWER(COALESCE(nd.os_name, '')) LIKE '%%os x%%' THEN 'workstation'
                ELSE d.device_role
            END,
            os_name   = COALESCE(nd.os_name, d.os_name),
            os_family = CASE
                WHEN nd.os_name IS NULL THEN d.os_family
                ELSE operations.os_family(nd.os_name)
            END,
            os_group = COALESCE(
                (SELECT m.os_group FROM operations.os_group_mappings m
                 WHERE (CASE WHEN nd.os_name IS NULL THEN d.os_family
                             ELSE operations.os_family(nd.os_name) END) LIKE m.pattern
                 ORDER BY m.priority ASC LIMIT 1),
                'Unknown'
            )
        FROM operations.device_links dl
        JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
        JOIN ninja_core.devices nd ON nd.id::text = dl.external_id
        WHERE dl.device_id = d.id
          AND dl.tenant_id = d.tenant_id
        """
    )


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
            -- device_links per device (legal per BLUEPRINT E.3). If ANY
            -- Ninja link on the device carries the marker, treat it as
            -- present.
            SELECT dl.tenant_id, dl.device_id AS ops_device_id,
                   BOOL_OR(
                     (nd.data -> 'tags')::text ILIKE '%%no av%%'
                     OR COALESCE(p.name, '')  ILIKE '%%no av%%'
                     OR COALESCE(rp.name, '') ILIKE '%%no av%%'
                   ) AS marker_present
            FROM operations.device_links dl
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
            -- device_links per device (legal per BLUEPRINT E.3). If ANY
            -- Ninja link on the device carries the marker, treat it as
            -- present.
            SELECT dl.tenant_id, dl.device_id AS ops_device_id,
                   BOOL_OR(
                     (nd.data -> 'tags')::text ILIKE '%%no av%%'
                     OR COALESCE(p.name, '')  ILIKE '%%no av%%'
                     OR COALESCE(rp.name, '') ILIKE '%%no av%%'
                   ) AS marker_present
            FROM operations.device_links dl
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
) -> int:
    """Write one entity_observation per Ninja record seen in this sync.

    Ninja is an aggregator carrying multiple streams — entity_type comes
    from node_class (agent.rmm / vm.guest / vm.host / network.device /
    monitor.target). EVERY record is observed, linked or not; unlinked
    rows get device_id NULL and flow through the identity resolver.

    Uses a per-run batch_id + per-device hash so re-runs of the same
    snapshot_at are idempotent (ON CONFLICT DO NOTHING).
    """
    if not device_rows:
        return 0

    presence = {
        r["device_id"]: (r["offline"], r["last_contact"]) for r in snapshot_rows
    }
    ninja_ids = [str(r["id"]) for r in device_rows]
    batch_id = uuid.uuid4()

    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
            run_id = begin_run(
                cur, _TENANT_ID, NINJA_SOURCE_BINDING_ID, "Ninja",
                snapshot_at, expected_rows=len(device_rows),
            )
            cur.execute(
                """
                SELECT dl.external_id, dl.device_id, d.client_id
                FROM operations.device_links dl
                JOIN operations.devices d
                     ON d.id = dl.device_id AND d.tenant_id = dl.tenant_id
                JOIN operations.sources s
                     ON s.id = dl.source_id AND s.name = 'Ninja'
                WHERE dl.tenant_id = %s
                  AND dl.external_id = ANY(%s)
                """,
                (_TENANT_ID, ninja_ids),
            )
            link_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

            # org → client mapping so unlinked records still carry their client.
            cur.execute(
                """
                SELECT cl.external_id, cl.client_id
                FROM operations.client_links cl
                JOIN operations.sources s ON s.id = cl.source_id AND s.name = 'Ninja'
                WHERE cl.tenant_id = %s
                """,
                (_TENANT_ID,),
            )
            org_map = {row[0]: row[1] for row in cur.fetchall()}

            obs_rows = []
            unknown_classes: dict[str, int] = {}
            for r in device_rows:
                entry = link_map.get(str(r["id"]))
                ops_device_id, client_id = entry if entry else (None, None)
                if client_id is None:
                    client_id = org_map.get(str(r["organization_id"]))
                entity_type = entity_type_for_node_class(r["node_class"])
                if entity_type == "unknown":
                    unknown_classes[r["node_class"] or ""] = (
                        unknown_classes.get(r["node_class"] or "", 0) + 1
                    )
                entity_key = str(r["id"])
                obs_hash = hashlib.sha256(
                    f"{entity_key}:{snapshot_at.isoformat()}".encode()
                ).digest()
                offline, last_contact = presence.get(r["id"], (None, None))
                canonical_data = {
                    "hostname": (
                        r["system_name"] or r["display_name"] or r["dns_name"]
                    ),
                    "platform":      "Ninja",
                    "entity_type":   entity_type,
                    "node_class":    r["node_class"],
                    "vm_uuid":       str(r["uid"]) if r.get("uid") else None,
                    "is_vm":         r.get("is_virtual_machine"),
                    "last_seen_at":  last_contact.isoformat() if last_contact else None,
                    "is_online":     None if offline is None else not offline,
                    "serial_number": r["serial_number"],
                    "macs": sorted({
                        m for m in (
                            normalize_mac(x)
                            for x in (r.get("mac_addresses") or [])
                            if isinstance(x, str)
                        ) if m
                    }),
                    # None when node_class/os give no explicit signal — never guessed.
                    "device_role":   infer_device_role(r["os_name"], r["node_class"]),
                    "os_name":       r["os_name"],
                    "os_family":     os_family(r["os_name"]),
                    # Ninja doesn't expose AD domain directly; the DNS suffix
                    # is the closest factual equivalent.
                    "domain": (
                        r["dns_name"].split(".", 1)[1]
                        if r["dns_name"] and "." in r["dns_name"] else None
                    ),
                }
                # vm.guest / vm.host tracking payload — sourced from the
                # side-band lookup populated during fetch.
                vm_extras = (vm_tracking or {}).get(r["id"])
                if vm_extras:
                    ps = vm_extras.get("power_state")
                    canonical_data["power_state"] = (
                        ps.lower() if isinstance(ps, str) else None
                    )
                    canonical_data["parent_ninja_id"] = vm_extras.get("parent_device_id")
                    canonical_data["last_boot_time_at"] = vm_extras.get("last_boot_time")
                obs_rows.append({
                    "observation_id":          uuid.uuid4(),
                    "tenant_id":               _TENANT_ID,
                    "client_id":               client_id,
                    "device_id":               ops_device_id,
                    "collector_instance_id":   INTERNAL_COLLECTOR_INSTANCE_ID,
                    "source_binding_id":       NINJA_SOURCE_BINDING_ID,
                    "entity_type":             entity_type,
                    "entity_key":              entity_key,
                    "platform":                "Ninja",
                    "subplatform":             "",
                    "observed_at":             snapshot_at,
                    "raw_data":                Json({}),
                    "canonical_data":          Json(canonical_data),
                    "batch_id":                batch_id,
                    "observation_hash":        obs_hash,
                    "collector_version":       "",
                    "schema_version":          1,
                })

            # One `org` observation per Ninja organization per run (BLUEPRINT
            # Track C.2) — every org, including ones with zero devices.
            # client_id here is rung 1 only (existing client_links); rungs
            # 2-4 belong to the client resolver (C2).
            org_counts: dict[str, int] = {}
            for r in device_rows:
                oid = str(r["organization_id"])
                org_counts[oid] = org_counts.get(oid, 0) + 1
            cur.execute("SELECT id, name FROM ninja_core.organizations")
            for org_id, org_name in cur.fetchall():
                oid = str(org_id)
                obs_rows.append({
                    "observation_id":        uuid.uuid4(),
                    "tenant_id":             _TENANT_ID,
                    "client_id":             org_map.get(oid),
                    "device_id":             None,
                    "collector_instance_id": INTERNAL_COLLECTOR_INSTANCE_ID,
                    "source_binding_id":     NINJA_SOURCE_BINDING_ID,
                    "entity_type":           "org",
                    "entity_key":            oid,
                    "platform":              "Ninja",
                    "subplatform":           "",
                    "observed_at":           snapshot_at,
                    "raw_data":              Json({}),
                    "canonical_data":        Json({
                        "name":            org_name,
                        "normalized_name": normalize_org_name(org_name),
                        "platform":        "Ninja",
                        "entity_type":     "org",
                        "device_count":    org_counts.get(oid, 0),
                    }),
                    "batch_id":              batch_id,
                    # entity_type prefixed so an org key can never collide
                    # with a device key in the same batch.
                    "observation_hash":      hashlib.sha256(
                        f"org:{oid}:{snapshot_at.isoformat()}".encode()
                    ).digest(),
                    "collector_version":     "",
                    "schema_version":        1,
                })

            if obs_rows:
                db.insert_ignore(
                    cur,
                    "operations.entity_observations",
                    obs_rows,
                    conflict_keys=["tenant_id", "collector_instance_id", "batch_id", "observation_hash"],
                )
                current_rows = []
                for row in obs_rows:
                    current = dict(row)
                    current["parent_source_key"] = ""
                    current["last_seen_at"] = row["observed_at"]
                    current["last_received_at"] = row["observed_at"]
                    current["active"] = True
                    current["withdrawn_at"] = None
                    current["snapshot_scope"] = "Ninja"
                    current["last_snapshot_run_id"] = run_id
                    current["raw_hash"] = hashlib.sha256(
                        str(row["raw_data"]).encode("utf-8")
                    ).digest()
                    current_rows.append(current)
                write_current_rows(cur, current_rows)
                complete_run(cur, run_id, len(current_rows))
                reconcile_complete_run(cur, run_id)
            if unknown_classes:
                # Never silently dropped — surfaced here, admin finding in E2.
                log.warning(
                    "Ninja records with unmapped node_class (observed as "
                    "entity_type='unknown'): %s", unknown_classes,
                )
            return len(obs_rows)
    except Exception:
        log.exception("Ninja entity_observations write failed — continuing")
        return 0


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
    operations.devices.os_group/device_role too — those are set by
    `_sync_operations_device_roles` (already run earlier in the
    devices pipeline). Public (no leading underscore) so main.py can
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
            cur.execute("REFRESH MATERIALIZED VIEW ninja_core.v_active_devices")
        log.info("Refreshed materialized view ninja_core.v_active_devices")
    except (psycopg.errors.UndefinedTable, psycopg.errors.WrongObjectType):
        log.info(
            "ninja_core.v_active_devices is not materialized yet; "
            "skipping refresh"
        )
