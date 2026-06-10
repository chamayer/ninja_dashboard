"""Load DB-backed agent-compliance configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ingest import db
from ingest.agent_compliance.normalize import canonical_platform, normalize_org_name

ORG_EXCLUDES = {"abe private", "amrose-test"}


@dataclass(frozen=True)
class SourceConfig:
    source_id: int
    source_key: str
    platform: str
    source_name: str
    client_id: int | None
    client_name: str | None
    is_shared: bool
    enabled: bool
    base_url: str | None
    token_url: str | None
    api_token: str | None
    client_id_value: str | None
    client_secret: str | None
    ext_guid: str | None
    secret_key: str | None
    company_id: str | None
    psk: str | None


@dataclass(frozen=True)
class ClientConfig:
    client_id: int
    client_name: str
    default_max_age_days: int


@dataclass(frozen=True)
class Requirement:
    client_id: int | None
    device_scope: str
    required_platforms: tuple[str, ...]
    max_age_days: int | None


def _secret(ref: str | None) -> str | None:
    if not ref:
        return None
    return os.environ.get(ref)


def load_sources() -> list[SourceConfig]:
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT
                ps.source_id, ps.source_key, ps.platform, ps.source_name,
                ps.client_id, c.client_name, ps.is_shared, ps.enabled,
                ps.base_url, ps.token_url, ps.api_token_secret_ref,
                ps.client_id_secret_ref, ps.client_secret_ref,
                ps.ext_guid_secret_ref, ps.secret_key_secret_ref,
                ps.company_id_secret_ref, ps.psk_secret_ref
            FROM ninja_agent_compliance.platform_sources ps
            LEFT JOIN ninja_agent_compliance.clients c ON c.client_id = ps.client_id
            WHERE ps.enabled
            ORDER BY ps.platform, ps.source_name
            """
        )
        rows = cur.fetchall()
    return [
        SourceConfig(
            source_id=row[0],
            source_key=row[1],
            platform=canonical_platform(row[2]),
            source_name=row[3],
            client_id=row[4],
            client_name=row[5],
            is_shared=row[6],
            enabled=row[7],
            base_url=row[8],
            token_url=row[9],
            api_token=_secret(row[10]),
            client_id_value=_secret(row[11]),
            client_secret=_secret(row[12]),
            ext_guid=_secret(row[13]),
            secret_key=_secret(row[14]),
            company_id=_secret(row[15]),
            psk=_secret(row[16]),
        )
        for row in rows
    ]


def load_clients() -> dict[int, ClientConfig]:
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT client_id, client_name, default_max_age_days
            FROM ninja_agent_compliance.clients
            WHERE enabled
            """
        )
        rows = cur.fetchall()
    return {
        row[0]: ClientConfig(
            client_id=row[0],
            client_name=row[1],
            default_max_age_days=row[2],
        )
        for row in rows
    }


def load_aliases() -> dict[tuple[str, str, str], int]:
    """Return exact and normalized (platform, alias_type, value) aliases."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT platform, alias_type, alias_value, client_id
            FROM ninja_agent_compliance.client_aliases
            WHERE enabled
            ORDER BY
                CASE source
                    WHEN 'manual' THEN 0
                    WHEN 'seed' THEN 1
                    WHEN 'alignment' THEN 2
                    ELSE 3
                END,
                alias_id
            """
        )
        rows = cur.fetchall()
    aliases: dict[tuple[str, str, str], int] = {}
    for platform, alias_type, alias_value, client_id in rows:
        platform = canonical_platform(platform)
        exact = alias_value.strip().lower()
        aliases.setdefault((platform, alias_type, exact), client_id)
        normalized = normalize_org_name(alias_value)
        if normalized:
            aliases.setdefault((platform, f"{alias_type}_norm", normalized), client_id)
    return aliases


def sync_clients_from_observations(observations: list[dict[str, Any]]) -> int:
    """Mirror the PowerShell alignment map and persist platform aliases."""
    platform_alias_types = {
        "Ninja": "org_name",
        "SentinelOne": "site_name",
        "LogMeIn": "group_name",
    }
    by_norm: dict[str, list[tuple[str, str]]] = {}
    for obs in observations:
        platform = canonical_platform(obs.get("platform") or "")
        if platform not in platform_alias_types:
            continue
        name = (obs.get("platform_group_name") or "").strip()
        if not name:
            continue
        if name.lower() in ORG_EXCLUDES:
            continue
        norm = normalize_org_name(name)
        if not norm:
            continue
        by_norm.setdefault(norm, []).append((platform, name))
    if not by_norm:
        return 0

    with db.transaction() as cur:
        cur.execute(
            """
            SELECT client_id, client_name, source
            FROM ninja_agent_compliance.clients
            WHERE enabled
            """
        )
        clients = cur.fetchall()
        cur.execute(
            """
            SELECT DISTINCT client_id
            FROM ninja_agent_compliance.client_aliases
            WHERE enabled
            UNION
            SELECT DISTINCT client_id
            FROM ninja_agent_compliance.platform_requirements
            WHERE client_id IS NOT NULL AND enabled
            """
        )
        configured_client_ids = {row[0] for row in cur.fetchall()}

        client_by_norm = {
            normalize_org_name(row[1]): (row[0], row[1], row[2])
            for row in clients
        }
        explicit_by_norm = {
            normalize_org_name(row[1]): (row[0], row[1], row[2])
            for row in clients
            if row[0] in configured_client_ids
        }

        platforms_by_norm = {
            norm: {platform for platform, _ in entries}
            for norm, entries in by_norm.items()
        }
        canonical_norm_by_norm = {norm: norm for norm in by_norm}
        ninja_norms = [
            norm for norm, platforms in platforms_by_norm.items()
            if "Ninja" in platforms
        ]
        for norm, platforms in platforms_by_norm.items():
            if "Ninja" in platforms or len(norm) < 4:
                continue
            candidates = [
                ninja_norm for ninja_norm in ninja_norms
                if ninja_norm != norm
                and len(ninja_norm) >= 4
                and (ninja_norm in norm or norm in ninja_norm)
                and not (platforms & platforms_by_norm[ninja_norm])
            ]
            if len(candidates) == 1:
                canonical_norm_by_norm[norm] = candidates[0]

        canonical_names: dict[str, str] = {}
        for norm, entries in by_norm.items():
            explicit = explicit_by_norm.get(norm)
            if explicit:
                canonical_names[norm] = explicit[1]
                continue
            for preferred_platform in ("Ninja", "SentinelOne", "LogMeIn"):
                name = next((entry_name for platform, entry_name in entries if platform == preferred_platform), None)
                if name:
                    canonical_names[norm] = name
                    break
        for norm, canonical_norm in canonical_norm_by_norm.items():
            if norm in explicit_by_norm:
                continue
            if canonical_norm != norm and canonical_norm in canonical_names:
                canonical_names[norm] = canonical_names[canonical_norm]

        cur.executemany(
            """
            INSERT INTO ninja_agent_compliance.clients
                (client_name, default_max_age_days, source, notes)
            VALUES (%s, 30, 'alignment', 'Discovered from platform org/site/group alignment')
            ON CONFLICT (client_name) DO NOTHING
            """,
            [(name,) for name in sorted(set(canonical_names.values()))],
        )
        cur.execute(
            """
            SELECT client_id, client_name, source
            FROM ninja_agent_compliance.clients
            WHERE enabled
            """
        )
        client_by_name = {
            row[1].strip().lower(): (row[0], row[1], row[2])
            for row in cur.fetchall()
        }

        alias_rows: list[tuple[int, str, str, str, str]] = []
        for norm, entries in by_norm.items():
            canonical = client_by_name.get(canonical_names[norm].strip().lower())
            if not canonical:
                continue
            client_id = canonical[0]
            seen: set[tuple[str, str, str]] = set()
            for platform, name in entries:
                alias_type = platform_alias_types[platform]
                key = (platform, alias_type, name.strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                alias_rows.append((
                    client_id,
                    platform,
                    alias_type,
                    name,
                    "Generated from PowerShell-style org alignment",
                ))
        if alias_rows:
            cur.executemany(
                """
                INSERT INTO ninja_agent_compliance.client_aliases
                    (client_id, platform, alias_type, alias_value, source, notes, updated_by)
                VALUES (%s, %s, %s, %s, 'alignment', %s, 'agent_compliance')
                ON CONFLICT (client_id, platform, (COALESCE(source_id, 0)), alias_type, alias_value)
                DO UPDATE SET
                    enabled = true,
                    notes = EXCLUDED.notes,
                    updated_at = now(),
                    updated_by = EXCLUDED.updated_by
                """,
                alias_rows,
            )
        return len(alias_rows)


def load_requirements() -> list[Requirement]:
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT client_id, device_scope, required_platforms, max_age_days
            FROM ninja_agent_compliance.platform_requirements
            WHERE enabled
            ORDER BY client_id NULLS LAST, device_scope
            """
        )
        rows = cur.fetchall()
    return [
        Requirement(
            client_id=row[0],
            device_scope=row[1],
            required_platforms=tuple(canonical_platform(v) for v in row[2]),
            max_age_days=row[3],
        )
        for row in rows
    ]


def get_requirement(
    requirements: list[Requirement],
    client_id: int,
    device_scope: str,
) -> Requirement:
    checks = (
        (client_id, device_scope),
        (client_id, "all"),
        (None, device_scope),
        (None, "all"),
    )
    for wanted_client_id, wanted_scope in checks:
        for req in requirements:
            if req.client_id == wanted_client_id and req.device_scope == wanted_scope:
                return req
    return Requirement(None, "all", ("Ninja", "SentinelOne", "LogMeIn"), 30)


def resolve_client_id(
    aliases: dict[tuple[str, str, str], int],
    platform: str,
    group_name: str | None,
    group_id: str | None,
) -> tuple[int | None, str]:
    platform = canonical_platform(platform)
    candidates: list[tuple[str, str | None]] = [
        ("group_name", group_name),
        ("org_name", group_name),
        ("site_name", group_name),
        ("group_id", group_id),
        ("org_id", group_id),
        ("site_id", group_id),
    ]
    for alias_type, value in candidates:
        if not value:
            continue
        exact_value = value.strip().lower()
        client_id = aliases.get((platform, alias_type, exact_value))
        if client_id:
            return client_id, "alias"
        normalized_value = normalize_org_name(value)
        client_id = aliases.get((platform, f"{alias_type}_norm", normalized_value))
        if client_id:
            return client_id, "alias_norm"
    return None, "unresolved"


def json_default(value: Any) -> str:
    return str(value)
