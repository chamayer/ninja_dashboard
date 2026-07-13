"""SentinelOne agent collector."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from psycopg.types.json import Json

from ingest.normalize import infer_device_role, normalize_hostname, parse_dt
from ingest.sources import SourceConfig

log = logging.getLogger(__name__)


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    if not source.base_url or not source.api_token:
        raise RuntimeError("SentinelOne source requires base_url and api_token_secret_ref")

    base_url = source.base_url.rstrip("/")
    headers = {"Authorization": f"APIToken {source.api_token}"}
    cursor: str | None = None
    observations: list[dict] = []
    with httpx.Client(timeout=60) as client:
        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(f"{base_url}/agents", headers=headers, params=params)
            resp.raise_for_status()
            payload = resp.json()
            for agent in payload.get("data") or []:
                hostname = agent.get("computerName")
                norm = normalize_hostname(hostname)
                if not hostname or not norm:
                    continue
                observations.append({
                    "observed_at": observed_at,
                    "platform": "SentinelOne",
                    "source_id": source.source_id,
                    "source_name": source.source_name,
                    "source_client_name": None,
                    "platform_group_name": agent.get("siteName"),
                    "platform_group_id": str(agent.get("siteId") or ""),
                    "platform_device_id": str(agent.get("id") or ""),
                    "hostname": hostname,
                    "norm_name": norm,
                    "match_name": norm,
                    "device_type": infer_device_role(
                        agent.get("osName"), machine_type=agent.get("machineType")
                    ),
                    "os_name": agent.get("osName"),
                    "domain_name": agent.get("domain"),
                    "is_online": agent.get("isActive"),
                    "last_seen_at": parse_dt(agent.get("lastActiveDate")),
                    "raw_data": Json(agent),
                })
            cursor = (payload.get("pagination") or {}).get("nextCursor")
            if not cursor:
                break
        observations.extend(_fetch_sites(client, base_url, headers))
    return observations


def _fetch_sites(client: httpx.Client, base_url: str, headers: dict) -> list[dict]:
    """Container-only rows so sites with zero agents still produce an `org`
    observation. A sites-endpoint failure never blocks the agent run —
    device-derived groups still emit."""
    rows: list[dict] = []
    cursor: str | None = None
    try:
        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(f"{base_url}/sites", headers=headers, params=params)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data") or {}
            sites = data.get("sites") if isinstance(data, dict) else data
            for site in sites or []:
                site_id = site.get("id")
                if not site_id:
                    continue
                rows.append({
                    "_org_only": True,
                    "platform": "SentinelOne",
                    "platform_group_id": str(site_id),
                    "platform_group_name": site.get("name"),
                })
            cursor = (payload.get("pagination") or {}).get("nextCursor")
            if not cursor:
                break
    except Exception:
        log.exception("SentinelOne sites fetch failed — continuing with agent-derived groups")
    return rows
