"""LogMeIn Central host collector."""

from __future__ import annotations

import base64
from datetime import datetime

import httpx
from psycopg.types.json import Json

from ingest.agent_compliance.config_loader import SourceConfig
from ingest.agent_compliance.normalize import infer_device_type, normalize_hostname, parse_dt


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    if not source.base_url or not source.company_id or not source.psk:
        raise RuntimeError("LogMeIn source requires base_url, company_id_secret_ref, psk_secret_ref")

    token = base64.b64encode(f"{source.company_id}:{source.psk}".encode("ascii")).decode("ascii")
    headers = {"Authorization": f"Basic {token}"}
    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{source.base_url.rstrip('/')}/v2/hostswithgroups", headers=headers)
        resp.raise_for_status()
        payload = resp.json()

    hosts = payload.get("hosts") if isinstance(payload, dict) else payload
    observations: list[dict] = []
    for host in hosts or []:
        hostname = host.get("hostName") or host.get("name") or host.get("description")
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        group = host.get("group") or {}
        group_name = group.get("name") or host.get("groupName")
        group_id = group.get("id") or host.get("groupId")
        observations.append({
            "observed_at": observed_at,
            "platform": "LogMeIn",
            "source_id": source.source_id,
            "source_name": source.source_name,
            "source_client_name": None,
            "platform_group_name": group_name,
            "platform_group_id": str(group_id or ""),
            "platform_device_id": str(host.get("id") or host.get("hostId") or ""),
            "hostname": hostname,
            "norm_name": norm,
            "match_name": norm,
            "device_type": infer_device_type(host.get("osName") or host.get("os")),
            "os_name": host.get("osName") or host.get("os"),
            "domain_name": host.get("domain"),
            "is_online": host.get("isOnline") if "isOnline" in host else host.get("online"),
            "last_seen_at": parse_dt(host.get("lastSeen") or host.get("lastOnline")),
            "raw_data": Json(host),
        })
    return observations
