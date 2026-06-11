"""Load DB-backed agent-compliance configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ingest import db
from ingest.agent_compliance.normalize import (
    canonical_platform,
    is_placeholder_org_name,
    normalize_org_name,
)


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
        rows = [
            row for row in cur.fetchall()
            if not is_placeholder_org_name(row[5])
        ]
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
              AND source <> 'alignment'
            """
        )
        rows = [row for row in cur.fetchall() if not is_placeholder_org_name(row[1])]
    return {
        row[0]: ClientConfig(
            client_id=row[0],
            client_name=row[1],
            default_max_age_days=row[2],
        )
        for row in rows
    }


def load_org_excludes() -> set[str]:
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT pattern
            FROM ninja_agent_compliance.org_excludes
            WHERE enabled
            """
        )
        return {row[0].strip().lower() for row in cur.fetchall()}


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
        if is_placeholder_org_name(alias_value):
            continue
        platform = canonical_platform(platform)
        exact = alias_value.strip().lower()
        aliases.setdefault((platform, alias_type, exact), client_id)
        normalized = normalize_org_name(alias_value)
        if normalized:
            aliases.setdefault((platform, f"{alias_type}_norm", normalized), client_id)
    return aliases


def sync_clients_from_observations(
    observations: list[dict[str, Any]],
    run_id: int | None = None,
    observed_at: datetime | None = None,
) -> int:
    """Mirror the PowerShell alignment map and persist platform aliases."""
    org_excludes = load_org_excludes()
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
        if not name or is_placeholder_org_name(name):
            continue
        if name.lower() in org_excludes:
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
        clients = [row for row in cur.fetchall() if not is_placeholder_org_name(row[1])]
        authoritative_clients = {
            normalize_org_name(row[1]): (row[0], row[1], row[2])
            for row in clients
            if row[2] != "alignment"
        }
        cur.execute(
            """
            SELECT DISTINCT client_id
            FROM ninja_agent_compliance.client_aliases
            WHERE enabled AND source <> 'alignment'
            UNION
            SELECT DISTINCT client_id
            FROM ninja_agent_compliance.platform_requirements
            WHERE client_id IS NOT NULL AND enabled
            """
        )
        configured_client_ids = {row[0] for row in cur.fetchall()}

        explicit_by_norm = {
            normalize_org_name(row[1]): (row[0], row[1], row[2])
            for row in clients
            if row[0] in configured_client_ids
        }

        known_client_by_norm = dict(authoritative_clients)
        cur.execute(
            """
            SELECT c.client_id, c.client_name, a.alias_value
            FROM ninja_agent_compliance.client_aliases a
            JOIN ninja_agent_compliance.clients c ON c.client_id = a.client_id
            WHERE a.enabled
              AND a.source IN ('manual', 'seed')
            """
        )
        for client_id, client_name, alias_value in cur.fetchall():
            known_client_by_norm.setdefault(normalize_org_name(client_name), (client_id, client_name))
            if is_placeholder_org_name(alias_value):
                continue
            known_client_by_norm.setdefault(normalize_org_name(alias_value), (client_id, client_name))

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
        candidate_rows: list[tuple[str, str, str, str, int, datetime, datetime]] = []
        run_seen_at = observed_at or datetime.now(timezone.utc)
        for norm, entries in by_norm.items():
            explicit = explicit_by_norm.get(norm)
            if explicit:
                canonical_names[norm] = explicit[1]
                continue
            for preferred_platform in ("Ninja", "SentinelOne", "LogMeIn"):
                candidate_name = next((entry_name for platform, entry_name in entries if platform == preferred_platform), None)
                if not candidate_name:
                    continue
                preferred_existing = known_client_by_norm.get(normalize_org_name(candidate_name))
                if preferred_existing:
                    canonical_names[norm] = preferred_existing[1]
                    break
        for norm, canonical_norm in canonical_norm_by_norm.items():
            if norm in explicit_by_norm:
                continue
            if canonical_norm != norm and canonical_norm in canonical_names:
                canonical_names[norm] = canonical_names[canonical_norm]
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
            if not is_placeholder_org_name(row[1])
        }

        alias_rows: list[tuple[int, str, str, str, str]] = []
        platform_name_by_client: dict[int, dict[str, str]] = {}
        merged_from_by_client: dict[int, list[str]] = {}
        for norm, entries in by_norm.items():
            canonical_name = canonical_names.get(norm)
            if not canonical_name:
                for platform, name in entries:
                    candidate_rows.append((
                        norm,
                        name,
                        platform,
                        name,
                        sum(1 for p, candidate_name in entries if p == platform and candidate_name == name),
                        run_seen_at,
                        run_seen_at,
                    ))
                continue
            canonical = client_by_name.get(canonical_name.strip().lower())
            if not canonical:
                for platform, name in entries:
                    candidate_rows.append((
                        norm,
                        name,
                        platform,
                        name,
                        sum(1 for p, candidate_name in entries if p == platform and candidate_name == name),
                        run_seen_at,
                        run_seen_at,
                    ))
                continue
            client_id = canonical[0]
            if canonical_norm_by_norm.get(norm, norm) != norm:
                merged_from_by_client.setdefault(client_id, []).append(
                    f"{canonical_name} ({'+'.join(sorted(platforms_by_norm[norm]))}, fuzzy)"
                )
            seen: set[tuple[str, str, str]] = set()
            for platform, name in entries:
                platform_name_by_client.setdefault(client_id, {}).setdefault(platform, name)
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
        if candidate_rows:
            cur.executemany(
                """
                INSERT INTO ninja_agent_compliance.org_candidates
                    (norm_name, candidate_name, platform, source_name, observed_count, first_seen_at, last_seen_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'agent_compliance')
                ON CONFLICT (norm_name, platform, candidate_name) DO UPDATE SET
                    observed_count = ninja_agent_compliance.org_candidates.observed_count + EXCLUDED.observed_count,
                    last_seen_at = GREATEST(ninja_agent_compliance.org_candidates.last_seen_at, EXCLUDED.last_seen_at),
                    updated_at = now(),
                    updated_by = EXCLUDED.updated_by,
                    enabled = true
                """,
                candidate_rows,
            )
        _write_alignment_rows(
            cur,
            run_id=run_id,
            observed_at=run_seen_at,
            clients=client_by_name,
            explicit_client_ids=configured_client_ids,
            platform_name_by_client=platform_name_by_client,
            merged_from_by_client=merged_from_by_client,
            by_norm=by_norm,
        )
        return len(alias_rows)


def _write_alignment_rows(
    cur: Any,
    run_id: int | None,
    observed_at: datetime,
    clients: dict[str, tuple[int, str, str]],
    explicit_client_ids: set[int],
    platform_name_by_client: dict[int, dict[str, str]],
    merged_from_by_client: dict[int, list[str]],
    by_norm: dict[str, list[tuple[str, str]]],
) -> None:
    cur.execute(
        """
        SELECT client_id, required_platforms
        FROM ninja_agent_compliance.platform_requirements
        WHERE enabled
        ORDER BY client_id NULLS LAST
        """
    )
    required_by_client: dict[int | None, set[str]] = {}
    for client_id, platforms in cur.fetchall():
        required_by_client.setdefault(client_id, set()).update(canonical_platform(p) for p in platforms)
    default_required = required_by_client.get(None, {"Ninja", "SentinelOne", "LogMeIn"})

    # PowerShell parity (Get-OrgAlignmentMap, lines 972-987): the "expected"
    # platform name comes from explicit OrgConfig FIRST, observed FIRST-norm-match
    # SECOND, org_name THIRD. In our schema, OrgConfig is the manual/seed alias
    # table — 'org_name' for Ninja, 'site_name' for S1, 'group_name' for LMI.
    # Manual outranks seed; we ignore source='alignment' to avoid feedback loop.
    alias_type_for_platform = {
        "Ninja": "org_name",
        "SentinelOne": "site_name",
        "LogMeIn": "group_name",
    }
    cur.execute(
        """
        SELECT client_id, platform, alias_type, alias_value, source
        FROM ninja_agent_compliance.client_aliases
        WHERE enabled AND source IN ('manual', 'seed')
        ORDER BY
            CASE source WHEN 'manual' THEN 0 ELSE 1 END,
            alias_id
        """
    )
    configured_name_by_client: dict[tuple[int, str], str] = {}
    for client_id, platform, alias_type, alias_value, _source in cur.fetchall():
        canon_platform = canonical_platform(platform)
        if alias_type_for_platform.get(canon_platform) != alias_type:
            continue
        configured_name_by_client.setdefault((client_id, canon_platform), alias_value)

    norm_maps = {"Ninja": {}, "SentinelOne": {}, "LogMeIn": {}}
    for entries in by_norm.values():
        for platform, name in entries:
            norm_maps[platform][normalize_org_name(name)] = name

    rows = []
    for client_id, org_name, source in clients.values():
        names = platform_name_by_client.get(client_id, {})
        if source == "alignment" and "Ninja" not in names and client_id not in explicit_client_ids:
            continue
        if not names and client_id not in explicit_client_ids:
            continue
        required = required_by_client.get(client_id, default_required)
        expected_ninja = (
            configured_name_by_client.get((client_id, "Ninja"))
            or names.get("Ninja")
            or org_name
        )
        expected_s1 = (
            configured_name_by_client.get((client_id, "SentinelOne"))
            or names.get("SentinelOne")
            or org_name
        )
        expected_lmi = (
            configured_name_by_client.get((client_id, "LogMeIn"))
            or names.get("LogMeIn")
            or org_name
        )
        statuses = {
            "Ninja": _alignment_status(expected_ninja, norm_maps["Ninja"])
            if "Ninja" in required else "NA",
            "SentinelOne": _alignment_status(expected_s1, norm_maps["SentinelOne"])
            if "SentinelOne" in required else "NA",
            "LogMeIn": _alignment_status(expected_lmi, norm_maps["LogMeIn"])
            if "LogMeIn" in required else "NA",
        }
        sc_status = "CONFIGURED" if "ScreenConnect" in required else "NA"
        actionable = [v for v in statuses.values() if v != "NA"]
        if all(v == "MATCHED" for v in actionable):
            overall = "OK"
        elif any(v == "FUZZY" for v in actionable):
            overall = "OK - FUZZY"
        else:
            overall = "MISMATCH"
        rows.append((
            client_id,
            org_name,
            client_id in explicit_client_ids,
            statuses["Ninja"],
            sc_status,
            statuses["SentinelOne"],
            statuses["LogMeIn"],
            overall,
            expected_ninja,
            expected_s1,
            expected_lmi,
            sorted(set(merged_from_by_client.get(client_id, []))),
            _suggested_config(org_name, names),
            observed_at,
        ))

    if not rows:
        return
    cur.execute("DELETE FROM ninja_agent_compliance.org_alignment_current")
    cur.executemany(
        """
        INSERT INTO ninja_agent_compliance.org_alignment_current
            (client_id, org_name, is_configured, ninja_status, sc_status,
             s1_status, lmi_status, overall_status, ninja_platform_name,
             s1_platform_name, lmi_platform_name, merged_from,
             suggested_config, evaluated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )
    if run_id is not None:
        cur.executemany(
            """
            INSERT INTO ninja_agent_compliance.org_alignment_history
                (run_id, client_id, org_name, is_configured, ninja_status,
                 sc_status, s1_status, lmi_status, overall_status,
                 ninja_platform_name, s1_platform_name, lmi_platform_name,
                 merged_from, suggested_config, evaluated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(run_id, *row) for row in rows],
        )


def _alignment_status(expected: str | None, norm_map: dict[str, str]) -> str:
    if not expected:
        return "MISSING"
    expected_norm = normalize_org_name(expected)
    if expected_norm in norm_map:
        return "MATCHED"
    for key in norm_map:
        if len(key) > 2 and (expected_norm in key or key in expected_norm):
            return "FUZZY"
    return "MISSING"


def _suggested_config(org_name: str, names: dict[str, str]) -> str | None:
    parts = []
    if names.get("Ninja") and names["Ninja"] != org_name:
        parts.append(f'NinjaOrg="{names["Ninja"]}"')
    if names.get("SentinelOne") and names["SentinelOne"] != org_name:
        parts.append(f'S1Site="{names["SentinelOne"]}"')
    if names.get("LogMeIn") and names["LogMeIn"] != org_name:
        parts.append(f'LMIGroup="{names["LogMeIn"]}"')
    return "; ".join(parts) if parts else None


def promote_alignment_aliases(
    client_id: int,
    platform: str | None = None,
    alias_value: str | None = None,
    updated_by: str = "agent_compliance",
) -> int:
    """Promote a reviewed alias into manual aliases.

    When platform + alias_value are supplied, only that one row is
    promoted. The broader fallback remains for compatibility with
    older operator links."""
    platform = canonical_platform(platform or "") if platform else None
    if platform and alias_value is not None:
        alias_value = alias_value.strip()
        if not alias_value:
            return 0
        alias_type_by_platform = {
            "Ninja": "org_name",
            "SentinelOne": "site_name",
            "LogMeIn": "group_name",
        }
        alias_type = alias_type_by_platform.get(platform)
        if alias_type is None:
            return 0
        with db.transaction() as cur:
            cur.execute(
                """
                SELECT org_name
                FROM ninja_agent_compliance.org_alignment_current
                WHERE client_id = %s
                """,
                (client_id,),
            )
            row = cur.fetchone()
            if not row:
                return 0
            org_name = row[0]
            if normalize_org_name(alias_value) == normalize_org_name(org_name):
                return 0
            cur.execute(
                """
                INSERT INTO ninja_agent_compliance.client_aliases
                    (client_id, platform, alias_type, alias_value, source, notes, updated_by)
                VALUES (%s, %s, %s, %s, 'manual', %s, %s)
                ON CONFLICT (client_id, platform, (COALESCE(source_id, 0)), alias_type, alias_value)
                DO UPDATE SET
                    enabled = true,
                    source = 'manual',
                    notes = EXCLUDED.notes,
                    updated_at = now(),
                    updated_by = EXCLUDED.updated_by
                """,
                (
                    client_id,
                    platform,
                    alias_type,
                    alias_value,
                    "Promoted from alignment review",
                    updated_by,
                ),
            )
            return 1

    with db.transaction() as cur:
        cur.execute(
            """
            SELECT org_name, ninja_platform_name, s1_platform_name, lmi_platform_name
            FROM ninja_agent_compliance.org_alignment_current
            WHERE client_id = %s
            """,
            (client_id,),
        )
        row = cur.fetchone()
        if not row:
            return 0
        org_name, ninja_name, s1_name, lmi_name = row
        alias_rows: list[tuple[int, str, str, str, str]] = []
        for platform_name, alias_type, value in (
            ("Ninja", "org_name", ninja_name),
            ("SentinelOne", "site_name", s1_name),
            ("LogMeIn", "group_name", lmi_name),
        ):
            if not value:
                continue
            if normalize_org_name(value) == normalize_org_name(org_name):
                continue
            alias_rows.append((
                client_id,
                platform_name,
                alias_type,
                value,
                "Promoted from alignment review",
            ))
        if not alias_rows:
            return 0
        cur.executemany(
            """
            INSERT INTO ninja_agent_compliance.client_aliases
                (client_id, platform, alias_type, alias_value, source, notes, updated_by)
            VALUES (%s, %s, %s, %s, 'manual', %s, %s)
            ON CONFLICT (client_id, platform, (COALESCE(source_id, 0)), alias_type, alias_value)
            DO UPDATE SET
                enabled = true,
                source = 'manual',
                notes = EXCLUDED.notes,
                updated_at = now(),
                updated_by = EXCLUDED.updated_by
            """,
            [
                (client_id, platform_name, alias_type, value, notes, updated_by)
                for client_id, platform_name, alias_type, value, notes in alias_rows
            ],
        )
        return len(alias_rows)


def add_org_exclude(pattern: str, updated_by: str = "agent_compliance", notes: str | None = None) -> bool:
    """Add or promote a normalized org exclude."""
    normalized = pattern.strip().lower()
    if not normalized:
        return False
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO ninja_agent_compliance.org_excludes
                (pattern, source, notes, enabled, updated_by)
            VALUES (%s, 'manual', %s, true, %s)
            ON CONFLICT (pattern) DO UPDATE SET
                enabled = true,
                source = 'manual',
                notes = COALESCE(EXCLUDED.notes, ninja_agent_compliance.org_excludes.notes),
                updated_at = now(),
                updated_by = EXCLUDED.updated_by
            """,
            (normalized, notes, updated_by),
        )
    return True


def add_device_ignore(
    client_id: int,
    norm_name: str,
    updated_by: str = "agent_compliance",
    reason: str | None = None,
    display_name: str | None = None,
) -> bool:
    normalized = norm_name.strip().lower()
    if not normalized:
        return False
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO ninja_agent_compliance.alert_suppressions
                (client_id, norm_name, display_name, finding_type, affected_platform, reason, enabled, updated_by)
            VALUES (%s, %s, %s, NULL, NULL, %s, true, %s)
            ON CONFLICT (
                COALESCE(client_id, 0),
                COALESCE(norm_name, ''),
                COALESCE(finding_type, ''),
                COALESCE(affected_platform, '')
            ) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, ninja_agent_compliance.alert_suppressions.display_name),
                reason = EXCLUDED.reason,
                enabled = true,
                updated_at = now(),
                updated_by = EXCLUDED.updated_by
            """,
            (
                client_id,
                normalized,
                display_name,
                reason or "Ignored from device issues dashboard",
                updated_by,
            ),
        )
    return True


def remove_device_ignore(client_id: int, norm_name: str, updated_by: str = "agent_compliance") -> bool:
    normalized = norm_name.strip().lower()
    if not normalized:
        return False
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE ninja_agent_compliance.alert_suppressions
            SET enabled = false,
                updated_at = now(),
                updated_by = %s
            WHERE client_id = %s
              AND norm_name = %s
              AND finding_type IS NULL
              AND affected_platform IS NULL
              AND enabled
            """,
            (updated_by, client_id, normalized),
        )
        return cur.rowcount > 0


def remove_org_exclude(pattern: str, updated_by: str = "agent_compliance") -> bool:
    """Disable a manual org exclude without removing seed parity rows."""
    normalized = pattern.strip().lower()
    if not normalized:
        return False
    with db.transaction() as cur:
        cur.execute(
            """
            UPDATE ninja_agent_compliance.org_excludes
            SET enabled = false,
                updated_at = now(),
                updated_by = %s
            WHERE pattern = %s
              AND source = 'manual'
            """,
            (updated_by, normalized),
        )
        return cur.rowcount > 0


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
