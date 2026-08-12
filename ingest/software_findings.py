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

# Fallback defaults for the software classifier. Every knob can be
# overridden per-tenant via operations.evaluator_config rows keyed on
# evaluator_name = 'software_classifier'. Kept as constants only so a
# fresh tenant with no config row still runs cleanly.
_DEFAULT_CONFIG: dict = {
    "rare_recent_enabled": True,
    "rare_recent_max_age_days": 7,
    "rare_recent_max_devices": 2,
    "rare_recent_severity": "medium",
    "rare_recent_skip_categorized": True,
    "rare_recent_skip_decided": True,
    # whitelist_suggestion — the other side of rarity: titles installed
    # on ≥ N devices, uncategorised, and undecided at every scope. These
    # are the titles worth reviewing for a fleet-wide APPROVE decision.
    "whitelist_suggestion_enabled": True,
    "whitelist_suggestion_min_devices": 10,
    "whitelist_suggestion_severity": "low",
    # vulnerable_software — driven by intel matcher output. Fires when a
    # matched CVE is actively exploited (KEV) or severe (CVSS >= cutoff).
    "vulnerable_software_enabled": True,
    "vulnerable_software_cvss_cutoff": 7.0,
    "vulnerable_software_severity_kev": "critical",
    "vulnerable_software_severity_high": "high",
    # known_malicious_hint — driven by safety_signal accumulation. Fires
    # when a canonical title (or its publisher) has >= threshold open
    # threat-intel hits and no operator approval.
    "known_malicious_hint_enabled": True,
    "known_malicious_hint_min_hits": 3,
    "known_malicious_hint_severity": "low",
}


def _load_config(cur, tenant_id: int) -> dict:
    """Merge the tenant's evaluator_config row over the code defaults."""
    cur.execute(
        """
        SELECT config FROM operations.evaluator_config
        WHERE tenant_id = %s AND evaluator_name = 'software_classifier'
        LIMIT 1
        """,
        (tenant_id,),
    )
    row = cur.fetchone()
    stored = row[0] if row and isinstance(row[0], dict) else {}
    merged = dict(_DEFAULT_CONFIG)
    merged.update(stored)
    return merged


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
            cfg = _load_config(cur, tenant_id)
            vuln_titles = (
                _load_vulnerable_titles(
                    cur, tenant_id,
                    float(cfg.get("vulnerable_software_cvss_cutoff", 7.0)),
                )
                if cfg.get("vulnerable_software_enabled", True)
                and "vulnerable_software" in finding_type_ids
                else {}
            )
            threat_hits = (
                _load_threat_hit_counts(cur, tenant_id)
                if cfg.get("known_malicious_hint_enabled", True)
                and "known_malicious_hint" in finding_type_ids
                else {}
            )

            # What each finding type is *about* is a registry row, not a
            # constant here (migration 0130). An unknown name defaults to
            # device, so a newly registered type never emits against a
            # subject nobody chose for it.
            cur.execute("SELECT name, subject_scope FROM operations.finding_types")
            scopes: dict[str, str] = dict(cur.fetchall())

            # LEFT JOIN, not INNER: an installation with no catalogue link must
            # still be classified. It falls back to device scope and is counted
            # below rather than silently dropped.
            cur.execute(
                """
                SELECT sic.client_id, sic.device_id, sic.canonical_name,
                       COALESCE(sic.publisher,''), COALESCE(sic.install_location,''),
                       sic.first_observed_at,
                       p.product_uuid, sv.version_uuid,
                       sic.installation_uuid
                FROM operations.software_installations_current sic
                LEFT JOIN catalog.software_versions sv
                       ON sv.id = sic.software_version_id
                LEFT JOIN catalog.products p
                       ON p.id = sv.product_id
                WHERE sic.tenant_id = %s AND sic.stale_since IS NULL
                  AND sic.deleted_at IS NULL
                """,
                (tenant_id,),
            )
            installs = cur.fetchall()

            unlinked = sum(1 for row in installs if row[6] is None)
            if unlinked:
                log.warning(
                    "software_findings: %d of %d installation(s) have no catalogue "
                    "link; those fall back to device-scoped findings.",
                    unlinked, len(installs),
                )

            # Per-device AV product count for multi_av_conflict.
            av_products_per_device: dict[uuid.UUID, set[str]] = {}
            for client_id, device_id, name, _pub, _loc, _first, _pu, _vu, _iu in installs:
                entry = catalog.get(name.lower(), {})
                if "av" in entry.get("categories", []):
                    av_products_per_device.setdefault(device_id, set()).add(name)

            emitted_keys: set[str] = set()

            # finding_type_id -> registered scope, so _emit can resolve the
            # subject from the id it already receives.
            scope_by_id = {
                ft_id: scopes.get(ft_name, "device")
                for ft_name, ft_id in finding_type_ids.items()
            }

            for (client_id, device_id, name, publisher, location, first_seen,
                 product_uuid, version_uuid, installation_uuid) in installs:
                # Subject context for every _emit in this iteration.
                subj = (scope_by_id, product_uuid, version_uuid, installation_uuid)
                # Decision tier: title-scope (device > client > global) then
                # publisher-scope (device > client > global).
                dec = _resolve_decision(decisions, device_id, client_id, name, publisher)
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
                        emitted_keys, subj,
                    )

                # 2. install_path_suspicious
                if location and _matches_rules(
                    location, rules.get("install_path_suspicious", [])
                ):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["install_path_suspicious"],
                        client_id, device_id, name, publisher, "high", now,
                        {"reason": "suspicious install path", "location": location},
                        emitted_keys, subj,
                    )

                # 3. unauthorized_av / _rmm / _remote_access
                # Match sanctioned list case-insensitively with substring
                # containment either direction — the sanctioned set holds
                # Agent product names (e.g. "LogMeIn") while `name` is a
                # software canonical_name (e.g. "logmein client"), and
                # they rarely line up as exact strings.
                client_sanctioned = sanctioned.get(client_id, {})
                for cat in ("av", "rmm", "remote_access"):
                    if cat in cat_list and not _matches_sanctioned(
                        name, client_sanctioned.get(cat, set())
                    ):
                        finding_name = f"unauthorized_{cat}"
                        affected += _emit(
                            cur, tenant_id, finding_type_ids[finding_name],
                            client_id, device_id, name, publisher, "high", now,
                            {
                                "reason": f"{cat} product not in client's sanctioned set",
                                "category": cat,
                            },
                            emitted_keys, subj,
                        )

                # 4. multi_av_conflict (only emit once per device — key on 'multi_av')
                if len(av_products_per_device.get(device_id, set())) >= 2:
                    affected += _emit_scoped(
                        cur, tenant_id, finding_type_ids["multi_av_conflict"],
                        client_id, device_id, "multi_av", publisher, "high", now,
                        {"av_products": sorted(av_products_per_device[device_id])},
                        emitted_keys, subj,
                    )

                # 5. rare_recent — reframed per operator feedback:
                #    fire only for uncategorized + undecided titles that
                #    are recent AND rare across the fleet. Every gate is
                #    admin-tunable via evaluator_config.
                if cfg.get("rare_recent_enabled", True) and first_seen:
                    skip = False
                    # Any prior decision (approve, approve_publisher,
                    # reject, investigate) means an operator already
                    # looked. Approve/approve_publisher was caught by
                    # the loop-head early-continue; reject/investigate
                    # fall through to here — skip them.
                    if cfg.get("rare_recent_skip_decided", True) and dec:
                        skip = True
                    # Categorisation no longer suppresses. `categories`
                    # holds functional labels (av / rmm / remote_access) that
                    # say what software *does*, not whether it is trusted —
                    # ADR-0015 §3. Trust moved to `software_decisions`, which
                    # the `dec` test above already covers, so suppressing on a
                    # functional label would hide an undecided title merely
                    # because someone recorded its kind.
                    #
                    # `rare_recent_skip_categorized` is left in the config
                    # schema for compatibility but no longer suppresses:
                    # migration 0127 removed every trust label from the
                    # catalog, so a category can only be functional now.

                    if not skip:
                        if first_seen.tzinfo is None:
                            first_seen = first_seen.replace(tzinfo=timezone.utc)
                        age_days = (now - first_seen).total_seconds() / 86400
                        device_count = fleet_rarity.get(name.lower(), 0)
                        max_age = int(cfg.get("rare_recent_max_age_days", 7))
                        max_devices = int(cfg.get("rare_recent_max_devices", 2))
                        if age_days <= max_age and device_count <= max_devices:
                            severity = str(cfg.get("rare_recent_severity", "medium"))
                            affected += _emit(
                                cur, tenant_id, finding_type_ids["rare_recent"],
                                client_id, device_id, name, publisher, severity, now,
                                {
                                    "fleet_device_count": device_count,
                                    "first_seen_days": int(age_days),
                                },
                                emitted_keys,
                            )

                # 6. eol_runtime
                if _matches_rules(name, rules.get("eol_runtime", [])):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["eol_runtime"],
                        client_id, device_id, name, publisher, "medium", now,
                        {"reason": "matches end-of-life runtime pattern"},
                        emitted_keys, subj,
                    )

                # 8. vulnerable_software — installed title has a matched
                # CVE that is either actively exploited (KEV) or severe
                # (CVSS >= cutoff). Approval decisions still suppress:
                # the operator has explicitly accepted the risk.
                vuln = vuln_titles.get(name.lower())
                if vuln and dec not in ("approve", "approve_publisher"):
                    if vuln["kev"]:
                        severity = str(cfg.get("vulnerable_software_severity_kev", "critical"))
                        detail = {
                            "reason": "actively exploited vulnerability (CISA KEV)",
                            "kev_cves": vuln["kev"][:5],
                            "high_cves": vuln["high"][:5],
                            "worst_cvss": vuln["worst_cvss"],
                            "max_epss": vuln["max_epss"],
                        }
                    else:
                        severity = str(cfg.get("vulnerable_software_severity_high", "high"))
                        detail = {
                            "reason": "severe vulnerability (CVSS >= cutoff)",
                            "high_cves": vuln["high"][:5],
                            "worst_cvss": vuln["worst_cvss"],
                            "max_epss": vuln["max_epss"],
                        }
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["vulnerable_software"],
                        client_id, device_id, name, publisher, severity, now,
                        detail, emitted_keys, subj,
                    )

                # 9. known_malicious_hint — accumulated threat-intel
                # signals on the title or its publisher. Explicitly a
                # hint (OSINT is noisy). Suppressed by approve/approve_publisher.
                hits = threat_hits.get(name.lower(), 0)
                if (
                    hits >= int(cfg.get("known_malicious_hint_min_hits", 3))
                    and dec not in ("approve", "approve_publisher")
                    and "known_malicious_hint" in finding_type_ids
                ):
                    severity = str(cfg.get("known_malicious_hint_severity", "low"))
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["known_malicious_hint"],
                        client_id, device_id, name, publisher, severity, now,
                        {
                            "threat_hit_count": hits,
                            "reason": "community threat-intel accumulation",
                        },
                        emitted_keys, subj,
                    )

                # 7. whitelist_suggestion — the "≥ N devices, undecided,
                # uncategorised" review candidate. Distinct from
                # rare_recent (which fires at the ≤ 2 devices end); the
                # two are mutually exclusive by device_count threshold.
                # Suppression tests *decided*, not *labelled* (ADR-0015 §3).
                # This previously also required `not cat_list`, so tagging a
                # title `av` — a statement about what it does, carrying no
                # judgement — silenced the decision prompt exactly as a trust
                # label did. Trust is a decision and is covered by `dec`.
                if cfg.get("whitelist_suggestion_enabled", True) and not dec:
                    min_devices = int(cfg.get("whitelist_suggestion_min_devices", 10))
                    fleet_devices = fleet_rarity.get(name.lower(), 0)
                    if fleet_devices >= min_devices:
                        severity = str(cfg.get("whitelist_suggestion_severity", "low"))
                        affected += _emit(
                            cur, tenant_id, finding_type_ids["whitelist_suggestion"],
                            client_id, device_id, name, publisher, severity, now,
                            {
                                "fleet_device_count": fleet_devices,
                                "threshold": min_devices,
                                "reason": "uncategorised + undecided + widespread",
                            },
                            emitted_keys, subj,
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
    """Return a decision resolver dict with title- and publisher-scoped
    buckets at each scope tier:
    {
      'device':     {(device_id, name_lower): decision},
      'client':     {(client_id, name_lower): decision},
      'global':     {name_lower: decision},
      'device_pub': {(device_id, pub_lower): decision},
      'client_pub': {(client_id, pub_lower): decision},
      'global_pub': {pub_lower: decision},
    }
    """
    cur.execute(
        """
        SELECT client_id, device_id, canonical_name, publisher, decision
        FROM operations.software_decisions
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    out = {
        "device": {},
        "client": {},
        "global": {},
        "device_pub": {},
        "client_pub": {},
        "global_pub": {},
    }
    for client_id, device_id, name, publisher, dec in cur.fetchall():
        if name:
            n = name.lower()
            if device_id is not None:
                out["device"][(device_id, n)] = dec
            elif client_id is not None:
                out["client"][(client_id, n)] = dec
            else:
                out["global"][n] = dec
        elif publisher:
            p = publisher.lower()
            if device_id is not None:
                out["device_pub"][(device_id, p)] = dec
            elif client_id is not None:
                out["client_pub"][(client_id, p)] = dec
            else:
                out["global_pub"][p] = dec
    return out


def _resolve_decision(
    decisions: dict, device_id, client_id, name: str, publisher: str | None = None
) -> str | None:
    """Return the most specific decision. Title-scope wins over publisher-
    scope; within each, device > client > global."""
    n = (name or "").lower()
    p = (publisher or "").lower()
    if (device_id, n) in decisions["device"]:
        return decisions["device"][(device_id, n)]
    if (client_id, n) in decisions["client"]:
        return decisions["client"][(client_id, n)]
    if n in decisions["global"]:
        return decisions["global"][n]
    if p:
        if (device_id, p) in decisions["device_pub"]:
            return decisions["device_pub"][(device_id, p)]
        if (client_id, p) in decisions["client_pub"]:
            return decisions["client_pub"][(client_id, p)]
        if p in decisions["global_pub"]:
            return decisions["global_pub"][p]
    return None


def _matches_sanctioned(canonical: str, sanctioned: set) -> bool:
    """Case-insensitive containment match between a software canonical
    name and any Agent-product name in the sanctioned set. Either
    substring counts as a match — Agent name "LogMeIn" matches
    software "logmein client", Agent "Ninja" matches "ninjarmmagent",
    etc. Avoids false-positive `unauthorized_*` findings on required
    agents whose canonical software name isn't identical to their
    Agent-table name.
    """
    if not sanctioned:
        return False
    nl = (canonical or "").lower()
    if not nl:
        return False
    for a in sanctioned:
        al = str(a or "").lower()
        if not al:
            continue
        if al in nl or nl in al:
            return True
    return False


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
            'multi_av_conflict', 'rare_recent', 'eol_runtime',
            'whitelist_suggestion', 'vulnerable_software',
            'known_malicious_hint'
        )
        """
    )
    return {name: id for name, id in cur.fetchall()}


def _load_threat_hit_counts(cur, tenant_id: int) -> dict[str, int]:
    """Sum threat-intel hits per canonical title, including publisher-scope
    signals that apply to any title from that publisher."""
    cur.execute(
        """
        WITH title_hits AS (
            SELECT LOWER(canonical_name) AS canonical, COUNT(*) AS n
              FROM operations.safety_signal
             WHERE tenant_id = %s
               AND signal_type = 'threat_hit'
               AND canonical_name <> ''
             GROUP BY LOWER(canonical_name)
        ), publisher_hits AS (
            SELECT LOWER(publisher) AS publisher_lc, COUNT(*) AS n
              FROM operations.safety_signal
             WHERE tenant_id = %s
               AND signal_type = 'threat_hit'
               AND publisher <> ''
             GROUP BY LOWER(publisher)
        )
        SELECT LOWER(sic.canonical_name) AS canonical,
               COALESCE(th.n, 0) + COALESCE(ph.n, 0) AS hits
        FROM operations.software_installations_current sic
        LEFT JOIN title_hits th ON th.canonical = LOWER(sic.canonical_name)
        LEFT JOIN publisher_hits ph
               ON ph.publisher_lc = LOWER(COALESCE(sic.publisher, ''))
        WHERE sic.tenant_id = %s
          AND sic.deleted_at IS NULL
          AND sic.stale_since IS NULL
          AND sic.canonical_name <> ''
          AND (th.n IS NOT NULL OR ph.n IS NOT NULL)
        GROUP BY LOWER(sic.canonical_name), th.n, ph.n
        """,
        (tenant_id, tenant_id, tenant_id),
    )
    return {row[0]: int(row[1]) for row in cur.fetchall() if row[1]}


def _load_vulnerable_titles(cur, tenant_id: int, cvss_cutoff: float) -> dict:
    """Return {canonical_name_lower: {'kev': [cve...], 'high': [cve...],
    'worst_cvss': float, 'max_epss': float}} — every title whose cve_match
    rows include a KEV-flagged or high-CVSS CVE."""
    cur.execute(
        """
        SELECT LOWER(cm.canonical_name), c.cve_id, c.cvss_v3, c.epss_score, c.kev_flag
        FROM operations.cve_match cm
        JOIN intel.cves c ON c.cve_id = cm.cve_id
        WHERE cm.tenant_id = %s
          AND (c.kev_flag OR c.cvss_v3 >= %s)
        """,
        (tenant_id, cvss_cutoff),
    )
    out: dict[str, dict] = {}
    for canonical, cve_id, cvss, epss, kev in cur.fetchall():
        entry = out.setdefault(
            canonical,
            {"kev": [], "high": [], "worst_cvss": 0.0, "max_epss": 0.0},
        )
        if kev:
            entry["kev"].append(cve_id)
        elif cvss and float(cvss) >= cvss_cutoff:
            entry["high"].append(cve_id)
        if cvss and float(cvss) > entry["worst_cvss"]:
            entry["worst_cvss"] = float(cvss)
        if epss and float(epss) > entry["max_epss"]:
            entry["max_epss"] = float(epss)
    return out


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


def _subject_for(scope: str, device_id, product_uuid, version_uuid,
                 installation_uuid=None):
    """Resolve (subject_type, subject_id, client_id_used, key_client, key_device)
    for a finding type's registered scope.

    A software-scoped finding drops both client and device from its identity:
    the claim is about the title or the release, and who is exposed is derived
    by joining installations. Keeping either in the condition key is what
    produced 134,484 rows for ~1,831 distinct claims.

    `software_installation` is ADR-0015 §2's third subject kind and behaves
    differently from the two above: the install path belongs to the
    device-and-software *pair*, so the pair is the identity and neither
    endpoint is dropped. It is already unique per (device, title), so the
    condition key needs no client or device component either.

    Falls back to device scope when the required handle is missing rather than
    emitting a finding with a NULL subject. That is visible in the run log as a
    fallback count -- an unlinked installation is a real condition worth
    seeing, not something to swallow.
    """
    if scope == "software_product" and product_uuid is not None:
        return "software_product", product_uuid, None, None, None
    if scope == "software_version" and version_uuid is not None:
        return "software_version", version_uuid, None, None, None
    if scope == "software_installation" and installation_uuid is not None:
        return "software_installation", installation_uuid, None, None, None
    return "device", device_id, None, None, None


def _emit(cur, tenant_id, ft_id, client_id, device_id, canonical_name,
          publisher, severity, now, extra_details, emitted_keys,
          subj=None) -> int:
    return _emit_scoped(
        cur, tenant_id, ft_id, client_id, device_id, canonical_name,
        publisher, severity, now, extra_details, emitted_keys, subj,
    )


def _emit_scoped(cur, tenant_id, ft_id, client_id, device_id, canonical_key,
                 publisher, severity, now, extra_details, emitted_keys,
                 subj=None) -> int:
    # subj = (scope_by_finding_type_id, product_uuid, version_uuid,
    #         installation_uuid). Absent, everything stays device-scoped, which
    # is the pre-0130 behaviour and the safe default for any caller not yet
    # passing it. The 4-tuple is unpacked tolerantly so a 3-tuple caller keeps
    # working rather than raising.
    scope_by_id, product_uuid, version_uuid, installation_uuid = (
        tuple(subj) + (None,) if subj is not None and len(subj) == 3 else
        (subj or ({}, None, None, None))
    )
    scope = scope_by_id.get(ft_id, "device")
    subject_type, subject_id, _c, _kc, _kd = _subject_for(
        scope, device_id, product_uuid, version_uuid, installation_uuid
    )
    key_material = canonical_key
    if subject_type == "device":
        key_client, key_device = client_id, device_id
        row_client = client_id
    else:
        # Identity is the subject alone; client and device leave both the key
        # and the row. Finding.client is already nullable.
        key_client, key_device = None, None
        row_client = None
        # Version scope needs the version in the key, or two releases of one
        # title collapse onto each other. Key material only -- canonical_key
        # itself stays clean, because it is what finding_details reports.
        #
        # Installation scope needs it for a sharper reason: the subject is the
        # (device, title) pair, so dropping client and device from the key
        # would make the same title on two devices produce one identical key
        # and silently dedupe the second away in `emitted_keys`. The
        # installation uuid restores the per-pair identity that the subject
        # already carries.
        if subject_type in ("software_version", "software_installation"):
            key_material = f"{canonical_key}@{subject_id}"
    ckey = _condition_key(tenant_id, key_client, key_device, str(ft_id), key_material)
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
            %s, %s, %s::jsonb,
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
            tenant_id, ft_id, row_client, subject_type, subject_id,
            json.dumps(details), ckey, severity, now, now, now,
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
        SET status = 'resolved',
            last_seen_at = %s,
            -- closed_at is documented on the model as being set on any
            -- transition into a closed status, and this path never set it,
            -- so "was this active on date D" was unanswerable for every
            -- auto-resolved software finding.
            closed_at = COALESCE(f.closed_at, %s),
            -- ADR-0012: nothing is lost without when and why.
            finding_details = f.finding_details || jsonb_build_object(
                'resolution', jsonb_build_object(
                    'reason', 'no_longer_detected',
                    'detail', 'The installation is gone, or an operator '
                           || 'decision now approves it.'
                )
            )
        FROM operations.finding_types ft
        WHERE ft.id = f.finding_type_id
          AND ft.source_module = 'platform.software_findings'
          AND f.tenant_id = %s
          AND f.status IN ('open', 'acknowledged')
          AND NOT (f.condition_key = ANY(%s::text[]))
        """,
        (now, now, tenant_id, list(emitted_keys)),
    )
