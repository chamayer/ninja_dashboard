"""ScreenConnect access-session collector."""

from __future__ import annotations

from datetime import datetime

import httpx
from psycopg.types.json import Json

from ingest.normalize import infer_device_role, normalize_hostname, parse_dt
from ingest.sources import SourceConfig


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

    # EVERY live session becomes an observation — same-hostname sessions are
    # potential duplicate agents (each consumes a license) and must stay
    # accounted rows. The identity layer collapses sessions proven to be one
    # machine (serial/MAC) onto one device; the evaluator flags the group as
    # duplicate_platform_record. session_counts keeps the legacy IsDup flag
    # the matrix builder reads (`screenconnect_dup`).
    kept: list[dict] = []
    session_counts: dict[str, int] = {}
    for session in sessions or []:
        if session.get("IsDeleted") or session.get("IsEnded"):
            continue
        guest = session.get("GuestInfo") or {}
        hostname = guest.get("MachineName") or session.get("Name")
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        session_counts[norm] = session_counts.get(norm, 0) + 1
        kept.append(session)

    observations: list[dict] = []
    for session in kept:
        guest = session.get("GuestInfo") or {}
        hostname = guest.get("MachineName") or session.get("Name")
        norm = normalize_hostname(hostname)
        last_seen = parse_dt(guest.get("LastActivityTime"))
        if last_seen and last_seen.year <= 1:
            last_seen = None
        is_online = any(
            conn.get("ProcessType") == 2
            for conn in session.get("ActiveConnections") or []
        )
        raw = dict(session)
        count = session_counts.get(norm, 1)
        raw["IsDup"] = count > 1
        raw["_agent_compliance"] = {
            "sc_session_count": count,
            "sc_is_dup": count > 1,
        }
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
            "device_type": infer_device_role(guest.get("OperatingSystemName")),
            "os_name": guest.get("OperatingSystemName"),
            "domain_name": guest.get("MachineDomain"),
            "is_online": is_online,
            "last_seen_at": last_seen,
            "raw_data": Json(raw),
        })
    return observations
