"""ScreenConnect access-session collector."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from psycopg.types.json import Json

from ingest.agent_compliance.config_loader import SourceConfig
from ingest.agent_compliance.normalize import infer_device_type, normalize_hostname, parse_dt


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    if not source.base_url or not source.ext_guid or not source.secret_key:
        raise RuntimeError("ScreenConnect source requires base_url, ext_guid_secret_ref, secret_key_secret_ref")
    if not source.client_name:
        raise RuntimeError("ScreenConnect source must be assigned to a client")

    base_url = source.base_url.rstrip("/")
    url = f"{base_url}/App_Extensions/{source.ext_guid}/Service.ashx/GetSessionsByFilter"
    headers = {
        "Content-Type": "application/json",
        "CTRLAuthHeader": source.secret_key,
        "Origin": base_url,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, headers=headers, json=["SessionType = 'Access'"])
        resp.raise_for_status()
        sessions = resp.json()

    best: dict[str, tuple[datetime | None, dict]] = {}
    for session in sessions or []:
        guest = session.get("GuestInfo") or {}
        hostname = guest.get("MachineName") or session.get("Name")
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        last_seen = parse_dt(guest.get("LastActivityTime"))
        if last_seen and last_seen.year <= 1:
            last_seen = None
        existing = best.get(norm)
        if existing is None:
            best[norm] = (last_seen, session)
            continue
        old_seen = existing[0] or datetime.min.replace(tzinfo=timezone.utc)
        new_seen = last_seen or datetime.min.replace(tzinfo=timezone.utc)
        if new_seen > old_seen:
            best[norm] = (last_seen, session)

    observations: list[dict] = []
    for norm, (last_seen, session) in best.items():
        guest = session.get("GuestInfo") or {}
        hostname = guest.get("MachineName") or session.get("Name")
        is_online = any(
            conn.get("ProcessType") == 2
            for conn in session.get("ActiveConnections") or []
        )
        observations.append({
            "observed_at": observed_at,
            "platform": "ScreenConnect",
            "source_id": source.source_id,
            "source_name": source.source_name,
            "source_client_name": source.client_name,
            "platform_group_name": source.client_name,
            "platform_group_id": str(source.client_id or ""),
            "platform_device_id": str(session.get("SessionID") or ""),
            "hostname": hostname,
            "norm_name": norm,
            "match_name": norm,
            "device_type": infer_device_type(guest.get("OperatingSystemName")),
            "os_name": guest.get("OperatingSystemName"),
            "domain_name": guest.get("MachineDomain"),
            "is_online": is_online,
            "last_seen_at": last_seen,
            "raw_data": Json(session),
        })
    return observations
