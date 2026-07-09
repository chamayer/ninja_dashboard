"""Agent-compliance observations from local Ninja core tables."""

from __future__ import annotations

from datetime import datetime

from psycopg.rows import dict_row
from psycopg.types.json import Json

from ingest import db
from ingest.normalize import infer_device_type, normalize_hostname
from ingest.sources import SourceConfig


def _contains_no_av(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return "no av" in value.lower()
    if isinstance(value, dict):
        return any(_contains_no_av(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_no_av(item) for item in value)
    return False


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    with db.pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    d.id,
                    d.system_name,
                    d.display_name,
                    d.dns_name,
                    d.node_class,
                    d.os_name,
                    d.data,
                    o.name AS organization_name,
                    o.id::text AS organization_id,
                    s.offline,
                    s.last_contact,
                    p.name  AS policy_name,
                    rp.name AS role_policy_name
                FROM ninja_core.devices d
                JOIN ninja_core.organizations o ON o.id = d.organization_id
                LEFT JOIN ninja_core.policies p
                       ON p.id = d.policy_id
                LEFT JOIN ninja_core.policies rp
                       ON rp.id = d.role_policy_id
                LEFT JOIN LATERAL (
                    SELECT offline, last_contact
                    FROM ninja_core.device_snapshots s
                    WHERE s.device_id = d.id
                    ORDER BY s.snapshot_at DESC
                    LIMIT 1
                ) s ON true
                WHERE d.is_current = true
                  -- PowerShell parity: only AgentDevice records count for
                  -- agent compliance. Skip Hyper-V/VMware guests
                  -- (HYPERV_VMM_GUEST, VMWARE_VM_GUEST), NMS_* network
                  -- monitoring targets, CLOUD_MONITOR_TARGET, etc. These
                  -- have no agent installed — they're inventory entries
                  -- pulled from a host or probe and were inflating
                  -- counts + breaking NO AV detection when a hostname
                  -- collided with an agent device.
                  AND d.data->>'deviceType' = 'AgentDevice'
                """
            )
            rows = cur.fetchall()

    observations: list[dict] = []
    for row in rows:
        hostname = row["system_name"] or row["display_name"] or row["dns_name"]
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        raw_data = dict(row["data"] or {})
        # PowerShell parity: NO AV exemption fires when any of the device
        # tags array OR the assigned policy / role-policy name contains
        # "NO AV". The previous code checked raw_data["policy"] /
        # raw_data["rolePolicy"] / raw_data["rolePolicyName"], none of
        # which exist on /v2/devices-detailed — Ninja only returns the
        # policy IDs there. Resolve through ninja_core.policies instead.
        raw_data["_agent_compliance"] = {
            "no_av_exempt": (
                _contains_no_av(raw_data.get("tags"))
                or _contains_no_av(row.get("policy_name"))
                or _contains_no_av(row.get("role_policy_name"))
            ),
            "policy_name": row.get("policy_name"),
            "role_policy_name": row.get("role_policy_name"),
        }
        observations.append({
            "observed_at": observed_at,
            "platform": "Ninja",
            "source_id": source.source_id,
            "source_name": source.source_name,
            "source_client_name": None,
            "platform_group_name": row["organization_name"],
            "platform_group_id": row["organization_id"],
            "platform_device_id": str(row["id"]),
            "hostname": hostname,
            "norm_name": norm,
            "match_name": norm,
            "device_type": infer_device_type(row["os_name"], row["node_class"]),
            "os_name": row["os_name"],
            "domain_name": raw_data.get("system", {}).get("domain"),
            "is_online": None if row["offline"] is None else not row["offline"],
            "last_seen_at": row["last_contact"],
            "raw_data": Json(raw_data),
        })
    return observations
