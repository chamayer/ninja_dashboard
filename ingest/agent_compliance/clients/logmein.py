"""LogMeIn Central host collector."""

from __future__ import annotations

import base64
import time
from datetime import datetime

import httpx
from psycopg.types.json import Json

from ingest.agent_compliance.config_loader import SourceConfig
from ingest.agent_compliance.normalize import infer_device_type, normalize_hostname, parse_dt


def _retry_after_seconds(value: str | None) -> int:
    try:
        return int(value or 61)
    except ValueError:
        return 61


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    if not source.base_url or not source.company_id or not source.psk:
        raise RuntimeError("LogMeIn source requires base_url, company_id_secret_ref, psk_secret_ref")

    token = base64.b64encode(f"{source.company_id}:{source.psk}".encode("ascii")).decode("ascii")
    headers = {"Authorization": f"Basic {token}"}
    with httpx.Client(timeout=60) as client:
        url = f"{source.base_url.rstrip('/')}/v2/hostswithgroups"
        resp = client.get(url, headers=headers)
        if resp.status_code == 429:
            retry_after = _retry_after_seconds(resp.headers.get("Retry-After"))
            time.sleep(max(retry_after, 61))
            resp = client.get(url, headers=headers)
        resp.raise_for_status()
        payload = resp.json()

    hosts = payload.get("hosts") if isinstance(payload, dict) else payload
    groups = payload.get("groups") if isinstance(payload, dict) else []
    group_map = {
        str(group.get("id")): group.get("name")
        for group in groups or []
        if group.get("id") is not None
    }
    observations: list[dict] = []
    for host in hosts or []:
        hostname = host.get("hostName") or host.get("name") or host.get("description")
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        group = host.get("group") or {}
        group_id = group.get("id") or host.get("groupId") or host.get("groupid")
        group_name = group.get("name") or host.get("groupName") or group_map.get(str(group_id))
        is_online = (
            host.get("isHostOnline")
            if "isHostOnline" in host
            else host.get("isOnline")
            if "isOnline" in host
            else host.get("online")
        )
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
            "is_online": is_online,
            "last_seen_at": parse_dt(host.get("hostStateChangeDate") or host.get("lastSeen") or host.get("lastOnline")),
            "raw_data": Json(host),
        })
    return observations
