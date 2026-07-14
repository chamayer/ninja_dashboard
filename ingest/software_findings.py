"""Software classifier — Track 3 (BLUEPRINT §3).

Reads current software installations, the classifier rules, the
software catalog, and operator decisions; emits per-device findings.

Everything the classifier "knows" is data:
  * regex patterns → `software_classifier_rules`
  * category / publisher hints → `software_catalog`
  * approve / reject / investigate → `software_decisions` (device
    > client > global tier resolution)
  * sanctioned agent set per client → derived from RequirementProfile
    items OR the global CoverageRequirement fallback

No hardcoded product lists.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from ingest import db

log = logging.getLogger(__name__)

_TENANT_ID = 1
_RARE_RECENT_MAX_DEVICES = 2
_RARE_RECENT_MAX_AGE_DAYS = 30


def classify(tenant_id: int = _TENANT_ID) -> int:
    """Run the software classifier. Returns count of findings upserted."""
    now = datetime.now(timezone.utc)
    error: str | None = None
    affected = 0

    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
            rules = _load_rules(cur)
            catalog = _load_catalog(cur, tenant_id)
            decisions = _load_decisions(cur, tenant_id)
            sanctioned = _load_sanctioned_per_client(cur, tenant_id)
            fleet_rarity = _load_fleet_rarity(cur, tenant_id)
            finding_type_ids = _finding_type_ids(cur)

            cur.execute(
                """
                SELECT client_id, device_id, canonical_name,
                       COALESCE(publisher,''), COALESCE(install_location,''),
                       first_observed_at
                FROM operations.software_installations_current
                WHERE tenant_id = %s AND stale_since IS NULL AND deleted_at IS NULL
                """,
                (tenant_id,),
            )
            installs = cur.fetchall()

            # Per-device AV product count for multi_av_conflict.
            av_products_per_device: dict[uuid.UUID, set[str]] = {}
            for client_id, device_id, name, _pub, _loc, _first in installs:
                entry = catalog.get(name.lower(), {})
                if "av" in entry.get("categories", []):
                    av_products_per_device.setdefault(device_id, set()).add(name)

            emitted_keys: set[str] = set()

            for client_id, device_id, name, publisher, location, first_seen in installs:
                # Decision tier: device > client > global
                dec = _resolve_decision(decisions, device_id, client_id, name)
                if dec in ("approve", "approve_publisher"):
                    continue  # approved, skip all rules

                cat_entry = catalog.get(name.lower(), {})
                cat_list = cat_entry.get("categories", [])

                # 1. suspicious_name (unless whitelisted)
                if "whitelist" not in cat_list and _matches_rules(
                    name, rules.get("suspicious_name", [])
                ):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["suspicious_name"],
                        client_id, device_id, name, publisher, "high", now,
                        {"reason": "suspicious_name pattern match", "location": location},
                        emitted_keys,
                    )

                # 2. install_path_suspicious
                if location and _matches_rules(
                    location, rules.get("install_path_suspicious", [])
                ):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["install_path_suspicious"],
                        client_id, device_id, name, publisher, "high", now,
                        {"reason": "suspicious install path", "location": location},
                        emitted_keys,
                    )

                # 3. unauthorized_av / _rmm / _remote_access
                client_sanctioned = sanctioned.get(client_id, {})
                for cat in ("av", "rmm", "remote_access"):
                    if cat in cat_list and name not in client_sanctioned.get(cat, set()):
                        finding_name = f"unauthorized_{cat}"
                        affected += _emit(
                            cur, tenant_id, finding_type_ids[finding_name],
                            client_id, device_id, name, publisher, "high", now,
                            {
                                "reason": f"{cat} product not in client's sanctioned set",
                                "category": cat,
                            },
                            emitted_keys,
                        )

                # 4. multi_av_conflict (only emit once per device — key on 'multi_av')
                if len(av_products_per_device.get(device_id, set())) >= 2:
                    affected += _emit_scoped(
                        cur, tenant_id, finding_type_ids["multi_av_conflict"],
                        client_id, device_id, "multi_av", publisher, "high", now,
                        {"av_products": sorted(av_products_per_device[device_id])},
                        emitted_keys,
                    )

                # 5. rare_recent
                if first_seen:
                    if first_seen.tzinfo is None:
                        first_seen = first_seen.replace(tzinfo=timezone.utc)
                    age_days = (now - first_seen).total_seconds() / 86400
                    device_count = fleet_rarity.get(name.lower(), 0)
                    if (
                        age_days <= _RARE_RECENT_MAX_AGE_DAYS
                        and device_count <= _RARE_RECENT_MAX_DEVICES
                    ):
                        affected += _emit(
                            cur, tenant_id, finding_type_ids["rare_recent"],
                            client_id, device_id, name, publisher, "medium", now,
                            {"fleet_device_count": device_count, "first_seen_days": int(age_days)},
                            emitted_keys,
                        )

                # 6. eol_runtime
                if _matches_rules(name, rules.get("eol_runtime", [])):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["eol_runtime"],
                        client_id, device_id, name, publisher, "medium", now,
                        {"reason": "matches end-of-life runtime pattern"},
                        emitted_keys,
                    )

            _auto_resolve(cur, tenant_id, emitted_keys, now)
    except Exception as exc:
        error = str(exc)[:2000]
        raise
    finally:
        try:
            with db.transaction() as cur:
                cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
                cur.execute(
                    """
                    INSERT INTO operations.run_log
                        (id, tenant_id, kind, subject_ref, started_at,
                         ended_at, ok, rows, error)
                    VALUES (gen_random_uuid(), %s, 'software_classifier',
                            '{}'::jsonb, %s, NOW(), %s, %s, %s)
                    """,
                    (tenant_id, now, error is None, affected, error or ""),
                )
        except Exception:
            log.exception("software_findings: run_log write failed")

    log.info("software_findings: tenant=%d affected=%d", tenant_id, affected)
    return affected


# ── loaders ─────────────────────────────────────────────────────────────


def _load_rules(cur) -> dict[str, list[tuple[str, bool]]]:
    """rule_type → list of (pattern, is_regex) for enabled rules."""
    cur.execute(
        """
        SELECT rule_type, pattern, is_regex
        FROM operations.software_classifier_rules
        WHERE enabled
        """
    )
    out: dict[str, list[tuple[str, bool]]] = {}
    for rt, pattern, is_regex in cur.fetchall():
        out.setdefault(rt, []).append((pattern, is_regex))
    return out


def _load_catalog(cur, tenant_id: int) -> dict[str, dict]:
    """canonical_name.lower() → {'categories': [...], 'publisher_hint': str}."""
    cur.execute(
        """
        SELECT canonical_name, categories, COALESCE(publisher_hint, '')
        FROM operations.software_catalog
        WHERE tenant_id IS NULL OR tenant_id = %s
        """,
        (tenant_id,),
    )
    out: dict[str, dict] = {}
    for name, cats, pub in cur.fetchall():
        # Later (tenant-specific) rows override earlier globals via later
        # iteration; SQL doesn't order, so ensure global first if any.
        out[name.lower()] = {"categories": list(cats or []), "publisher_hint": pub}
    return out


def _load_decisions(cur, tenant_id: int) -> dict:
    """Return a decision resolver dict:
    {
      'device': {(device_id, name_lower): decision},
      'client': {(client_id, name_lower): decision},
      'global': {name_lower: decision},
    }
    """
    cur.execute(
        """
        SELECT client_id, device_id, canonical_name, decision
        FROM operations.software_decisions
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    out = {"device": {}, "client": {}, "global": {}}
    for client_id, device_id, name, dec in cur.fetchall():
        n = name.lower()
        if device_id is not None:
            out["device"][(device_id, n)] = dec
        elif client_id is not None:
            out["client"][(client_id, n)] = dec
        else:
            out["global"][n] = dec
    return out


def _resolve_decision(decisions: dict, device_id, client_id, name: str) -> str | None:
    n = name.lower()
    if (device_id, n) in decisions["device"]:
        return decisions["device"][(device_id, n)]
    if (client_id, n) in decisions["client"]:
        return decisions["client"][(client_id, n)]
    if n in decisions["global"]:
        return decisions["global"][n]
    return None


def _load_sanctioned_per_client(cur, tenant_id: int) -> dict:
    """Per client: {category → set(canonical_names sanctioned by policy)}.

    Sanctioned = the platform name attached to any coverage requirement
    or profile item the client has under an agent.* entity_type. Maps
    each agent's platform to the classifier category (av/rmm/
    remote_access) via the Agent table.
    """
    # First, agent → category from Agent.entity_type
    cur.execute("SELECT name, entity_type FROM operations.agents")
    agent_to_cat: dict[str, str] = {}
    _entity_to_cat = {
        "agent.rmm": "rmm",
        "agent.edr": "av",
        "agent.remote_access": "remote_access",
    }
    for name, entity_type in cur.fetchall():
        cat = _entity_to_cat.get(entity_type)
        if cat:
            agent_to_cat[name] = cat

    # Per client sanctioned: profile items → each item's platform is
    # in the sanctioned set for that agent's category.
    cur.execute(
        """
        SELECT c.id, rpi.platform
        FROM operations.clients c
        JOIN operations.requirement_profile_items rpi
          ON rpi.tenant_id = c.tenant_id
         AND rpi.profile_id = c.requirement_profile_id
        WHERE c.tenant_id = %s AND c.deleted_at IS NULL
          AND rpi.platform <> ''
        """,
        (tenant_id,),
    )
    per_client: dict = {}
    for client_id, platform in cur.fetchall():
        cat = agent_to_cat.get(platform)
        if cat:
            per_client.setdefault(client_id, {}).setdefault(cat, set()).add(platform)

    # Global fallback for clients without a profile: use global
    # coverage_requirements (client_id NULL) as the sanctioned set for
    # each of those clients.
    cur.execute(
        """
        SELECT cr.platform FROM operations.coverage_requirements cr
        WHERE cr.tenant_id = %s AND cr.client_id IS NULL AND cr.enabled
          AND cr.platform <> ''
        """,
        (tenant_id,),
    )
    global_sanctioned: dict = {}
    for (platform,) in cur.fetchall():
        cat = agent_to_cat.get(platform)
        if cat:
            global_sanctioned.setdefault(cat, set()).add(platform)

    cur.execute(
        """
        SELECT id FROM operations.clients
        WHERE tenant_id = %s AND deleted_at IS NULL
          AND requirement_profile_id IS NULL
        """,
        (tenant_id,),
    )
    for (client_id,) in cur.fetchall():
        per_client[client_id] = {k: set(v) for k, v in global_sanctioned.items()}

    return per_client


def _load_fleet_rarity(cur, tenant_id: int) -> dict[str, int]:
    """canonical_name.lower() → distinct device count fleet-wide."""
    cur.execute(
        """
        SELECT LOWER(canonical_name), COUNT(DISTINCT device_id)
        FROM operations.software_installations_current
        WHERE tenant_id = %s AND stale_since IS NULL AND deleted_at IS NULL
        GROUP BY LOWER(canonical_name)
        """,
        (tenant_id,),
    )
    return {name: cnt for name, cnt in cur.fetchall()}


def _finding_type_ids(cur) -> dict[str, int]:
    cur.execute(
        """
        SELECT name, id FROM operations.finding_types
        WHERE name IN (
            'suspicious_name', 'install_path_suspicious',
            'unauthorized_av', 'unauthorized_rmm', 'unauthorized_remote_access',
            'multi_av_conflict', 'rare_recent', 'eol_runtime'
        )
        """
    )
    return {name: id for name, id in cur.fetchall()}


# ── matching / emission ────────────────────────────────────────────────


def _matches_rules(text: str, rules: list[tuple[str, bool]]) -> bool:
    if not text or not rules:
        return False
    lowered = text.lower()
    for pattern, is_regex in rules:
        if is_regex:
            try:
                if re.search(pattern, lowered, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        elif pattern.lower() in lowered:
            return True
    return False


def _condition_key(tenant_id: int, client_id, device_id, ft_name: str, canonical: str) -> str:
    raw = f"{tenant_id}:{client_id}:{device_id}:{ft_name}:{canonical.lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _emit(cur, tenant_id, ft_id, client_id, device_id, canonical_name,
          publisher, severity, now, extra_details, emitted_keys) -> int:
    return _emit_scoped(
        cur, tenant_id, ft_id, client_id, device_id, canonical_name,
        publisher, severity, now, extra_details, emitted_keys,
    )


def _emit_scoped(cur, tenant_id, ft_id, client_id, device_id, canonical_key,
                 publisher, severity, now, extra_details, emitted_keys) -> int:
    ckey = _condition_key(tenant_id, client_id, device_id, str(ft_id), canonical_key)
    if ckey in emitted_keys:
        return 0
    emitted_keys.add(ckey)
    details = {
        "canonical_name": canonical_key,
        "publisher": publisher,
    }
    details.update({k: v for k, v in extra_details.items() if not k.startswith("_")})
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, finding_details,
            condition_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s,
            'device', %s, %s::jsonb,
            %s, %s, 'confirmed', 'open',
            %s, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
        DO UPDATE SET
            last_seen_at     = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            finding_details  = EXCLUDED.finding_details,
            status           = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        """,
        (
            tenant_id, ft_id, client_id, device_id, json.dumps(details),
            ckey, severity, now, now, now,
        ),
    )
    return 1


def _auto_resolve(cur, tenant_id: int, emitted_keys: set[str], now: datetime) -> None:
    """Close any open software finding NOT emitted this run — the install
    is gone or a decision approved it."""
    if not emitted_keys:
        return
    cur.execute(
        """
        UPDATE operations.findings f
        SET status = 'resolved', last_seen_at = %s
        FROM operations.finding_types ft
        WHERE ft.id = f.finding_type_id
          AND ft.source_module = 'platform.software_findings'
          AND f.tenant_id = %s
          AND f.status IN ('open', 'acknowledged')
          AND NOT (f.condition_key = ANY(%s::text[]))
        """,
        (now, tenant_id, list(emitted_keys)),
    )
