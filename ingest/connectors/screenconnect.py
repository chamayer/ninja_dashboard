"""ScreenConnect access-session collector."""

from __future__ import annotations

import re
from datetime import datetime

import httpx
from psycopg.types.json import Json

from ingest.normalize import infer_device_role, normalize_hostname, parse_dt
from ingest.sources import SourceConfig


EXTERNAL_NAMESPACE = "access-session"
CONTAINER_EXTERNAL_NAMESPACE = "source-instance"


def _group(source: SourceConfig, session: dict) -> tuple[str, str, str]:
    if not source.is_shared:
        return (
            CONTAINER_EXTERNAL_NAMESPACE,
            str(source.client_id or ""),
            source.client_name or "",
        )
    field = source.screenconnect_group_field or ""
    values = session.get("CustomProperties") or {}
    value = values.get(field) if isinstance(values, dict) else None
    if value is None:
        values = session.get("CustomPropertyValues") or []
        index = int(field.removeprefix("CustomProperty")) - 1
        value = (
            values[index] if isinstance(values, list) and index < len(values) else None
        )
    # A missing customer property remains unassigned evidence, never the
    # instance's client or another customer's group.
    name = value.strip() if isinstance(value, str) else ""
    return field.lower(), name, name


def fetch(source: SourceConfig, observed_at: datetime) -> list[dict]:
    if not source.base_url or not source.ext_guid or not source.secret_key:
        raise RuntimeError(
            "ScreenConnect source requires base_url, ext_guid_secret_ref, secret_key_secret_ref"
        )
    if source.is_shared:
        if source.client_id:
            raise RuntimeError(
                "Shared ScreenConnect source must not be assigned to a client"
            )
        if not re.fullmatch(
            r"CustomProperty[1-8]", source.screenconnect_group_field or ""
        ):
            raise RuntimeError(
                "Shared ScreenConnect source requires screenconnect_group_field "
                "set to its customer CustomProperty1 through CustomProperty8"
            )
    elif not source.client_name:
        raise RuntimeError("ScreenConnect source must be assigned to a client")

    base_url = source.base_url.rstrip("/")
    url = (
        f"{base_url}/App_Extensions/{source.ext_guid}/Service.ashx/GetSessionsByFilter"
    )
    headers = {
        "Content-Type": "application/json",
        "CTRLAuthHeader": source.secret_key,
        "Origin": base_url,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, headers=headers, json=["SessionType = 'Access'"])
        resp.raise_for_status()
        sessions = resp.json()
    if not isinstance(sessions, list) or any(
        not isinstance(item, dict) for item in sessions
    ):
        raise RuntimeError(
            "ScreenConnect session response must be a list of session objects"
        )

    # EVERY live session becomes an observation — same-hostname sessions are
    # potential duplicate agents (each consumes a license) and must stay
    # accounted rows. The identity layer collapses sessions proven to be one
    # machine (serial/MAC) onto one device; the evaluator flags the group as
    # duplicate_platform_record. session_counts keeps the legacy IsDup flag
    # the matrix builder reads (`screenconnect_dup`).
    kept: list[dict] = []
    session_counts: dict[tuple[str, str], int] = {}
    for session in sessions or []:
        if session.get("IsDeleted") or session.get("IsEnded"):
            continue
        guest = session.get("GuestInfo") or {}
        hostname = guest.get("MachineName") or session.get("Name")
        norm = normalize_hostname(hostname)
        if not hostname or not norm:
            continue
        _, group_id, _ = _group(source, session)
        key = (group_id, norm)
        session_counts[key] = session_counts.get(key, 0) + 1
        kept.append(session)

    observations: list[dict] = []
    for session in kept:
        guest = session.get("GuestInfo") or {}
        hostname = guest.get("MachineName") or session.get("Name")
        norm = normalize_hostname(hostname)
        group_namespace, group_id, group_name = _group(source, session)
        last_seen = parse_dt(guest.get("LastActivityTime"))
        if last_seen and last_seen.year <= 1:
            last_seen = None
        is_online = any(
            conn.get("ProcessType") == 2
            for conn in session.get("ActiveConnections") or []
        )
        raw = dict(session)
        count = session_counts.get((group_id, norm), 1)
        raw["IsDup"] = count > 1
        raw["_collector"] = {
            "sc_session_count": count,
            "sc_is_dup": count > 1,
        }
        observations.append(
            {
                "observed_at": observed_at,
                "platform": "ScreenConnect",
                "external_namespace": EXTERNAL_NAMESPACE,
                "container_external_namespace": group_namespace,
                "container_external_id": group_id if source.is_shared else "self",
                "source_id": source.source_id,
                "source_name": source.source_name,
                "source_client_name": None if source.is_shared else source.client_name,
                "platform_group_name": group_name,
                "platform_group_id": group_id,
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
            }
        )
    return observations
