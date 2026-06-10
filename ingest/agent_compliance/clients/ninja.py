"""Agent-compliance observations from local Ninja core tables."""

from __future__ import annotations

from datetime import datetime

from psycopg.rows import dict_row
from psycopg.types.json import Json

from ingest import db
from ingest.agent_compliance.config_loader import SourceConfig
from ingest.agent_compliance.normalize import infer_device_type, normalize_hostname


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
                    s.last_contact
                FROM ninja_core.devices d
                JOIN ninja_core.organizations o ON o.id = d.organization_id
                LEFT JOIN LATERAL (
                    SELECT offline, last_contact
                    FROM ninja_core.device_snapshots s
                    WHERE s.device_id = d.id
                    ORDER BY s.snapshot_at DESC
                    LIMIT 1
                ) s ON true
                WHERE d.is_current = true
                """
            )
            rows = cur.fetchall()

    observations: list[dict] = []
    for row in rows:
        hostname = row["system_name"] or row["display_name"] or row["dns_name"]
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
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
            "domain_name": (row["data"] or {}).get("system", {}).get("domain"),
            "is_online": None if row["offline"] is None else not row["offline"],
            "last_seen_at": row["last_contact"],
            "raw_data": Json(row["data"] or {}),
        })
    return observations
