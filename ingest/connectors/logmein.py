"""LogMeIn Central host collector."""

from __future__ import annotations

import base64
import time
from datetime import datetime

import httpx
from psycopg.types.json import Json

from ingest.normalize import infer_device_role, normalize_hostname, parse_dt
from ingest.sources import SourceConfig


def _retry_after_seconds(value: str | None) -> int:
    try:
        return int(value or 61)
    except ValueError:
        return 61


def _ci_get(data: dict, key: str) -> object | None:
    """Match PowerShell's case-insensitive JSON property access."""
    value = data.get(key)
    if value is not None:
        return value
    lowered = key.lower()
    for current_key, current_value in data.items():
        if str(current_key).lower() == lowered:
            return current_value
    return None


def _build_group_map(groups: object) -> dict[str, str]:
    if isinstance(groups, dict):
        mapped: dict[str, str] = {}
        for key, value in groups.items():
            if isinstance(value, dict):
                name = _ci_get(value, "name")
                mapped[str(key)] = str(name or key)
            else:
                mapped[str(key)] = str(value)
        return mapped
    if isinstance(groups, list):
        mapped = {}
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = _ci_get(group, "id")
            name = _ci_get(group, "name")
            if group_id is not None and name:
                mapped[str(group_id)] = str(name)
        return mapped
    return {}


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

    hosts = _ci_get(payload, "hosts") if isinstance(payload, dict) else payload
    groups = _ci_get(payload, "groups") if isinstance(payload, dict) else []
    group_map = _build_group_map(groups)
    observations: list[dict] = []
    for host in hosts or []:
        hostname = _ci_get(host, "hostName") or _ci_get(host, "name") or _ci_get(host, "description")
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        group = _ci_get(host, "group") or {}
        group_id = _ci_get(group, "id") if isinstance(group, dict) else None
        group_id = group_id or _ci_get(host, "groupid")
        group_name = _ci_get(group, "name") if isinstance(group, dict) else None
        group_name = group_name or _ci_get(host, "groupName") or group_map.get(str(group_id))
        is_online = (
            _ci_get(host, "isHostOnline")
            if _ci_get(host, "isHostOnline") is not None
            else _ci_get(host, "isOnline")
            if _ci_get(host, "isOnline") is not None
            else _ci_get(host, "online")
        )
        raw_data = dict(host)
        raw_data["_agent_compliance"] = {
            "lmi_group_id": str(group_id or ""),
            "lmi_group_name_resolved": bool(group_name),
            "lmi_group_map_size": len(group_map),
        }
        observations.append({
            "observed_at": observed_at,
            "platform": "LogMeIn",
            "source_id": source.source_id,
            "source_name": source.source_name,
            "source_client_name": None,
            "platform_group_name": group_name,
            "platform_group_id": str(group_id or ""),
            "platform_device_id": str(_ci_get(host, "id") or _ci_get(host, "hostId") or ""),
            "hostname": hostname,
            "norm_name": norm,
            "match_name": norm,
            "device_type": infer_device_role(_ci_get(host, "osName") or _ci_get(host, "os")),
            "os_name": _ci_get(host, "osName") or _ci_get(host, "os"),
            "domain_name": _ci_get(host, "domain"),
            "is_online": is_online,
            "last_seen_at": parse_dt(_ci_get(host, "hostStateChangeDate") or _ci_get(host, "lastSeen") or _ci_get(host, "lastOnline")),
            "raw_data": Json(raw_data),
        })
    return observations
