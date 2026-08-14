"""Software classifier — Track 3 (BLUEPRINT §3).

Reads current software installations, the classifier rules, the
software catalog, and operator decisions; emits per-device findings.

Everything the classifier "knows" is data:
  * regex patterns → `software_classifier_rules`
   * non-capability presentation labels → `software_catalog`
  * approve / reject / investigate → `software_decisions` (device
    > client > global tier resolution)
   * capability truth → `catalog.v_product_capability_effective`
   * sanctioned product identities per client → `platform_product_map` joined
     to requirement-profile items or the global CoverageRequirement fallback

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
from ingest.config import settings

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
    # on ≥ N devices, uncategorized, and undecided at every scope. These
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
            capability_ready = _capability_schema_ready(cur)
            capabilities = _load_effective_capabilities(cur) if capability_ready else {}
            sanctioned = _load_sanctioned_product_identities(cur, tenant_id) if capability_ready else {}
            authorizations = _load_authorizations(cur, tenant_id) if capability_ready else {}
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
            scopes, suppressed_by_approval = _load_scopes(cur)

            # LEFT JOIN, not INNER: an installation with no catalog link must
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
                    "software_findings: %d of %d installation(s) have no catalog "
                    "link; those fall back to device-scoped findings.",
                    unlinked, len(installs),
                )

            # Installed package inventory cannot establish whether endpoint
            # protection is active. Keep the type disabled until a real signal
            # (for example Windows Security Center) exists.
            av_products_per_device: dict[uuid.UUID, set[str]] = {}

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
                approved = dec in ("approve", "approve_publisher")

                cat_entry = catalog.get(name.lower(), {})
                cat_list = cat_entry.get("categories", [])

                # 1. suspicious_name (unless whitelisted)
                if not approval_silences("suspicious_name", approved, suppressed_by_approval) and "whitelist" not in cat_list and _matches_rules(
                    name, rules.get("suspicious_name", [])
                ):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["suspicious_name"],
                        client_id, device_id, name, publisher, "high", now,
                        {"reason": "suspicious_name pattern match", "location": location},
                        emitted_keys, subj,
                    )

                # 2. install_path_suspicious — a fact about where the software
                # sits on disk. Approval does not relocate it.
                if not approval_silences("install_path_suspicious", approved, suppressed_by_approval) and location and _matches_rules(
                    location, rules.get("install_path_suspicious", [])
                ):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["install_path_suspicious"],
                        client_id, device_id, name, publisher, "high", now,
                        {"reason": "suspicious install path", "location": location},
                        emitted_keys, subj,
                    )

                # 3. Unauthorized capability: only effective alertable evidence
                # (vetted machine or operator confirmation) may alert. Policy
                # exemption is exact product identity, never a name substring.
                product_capabilities = capabilities.get(product_uuid, []) if product_uuid else []
                if settings.CAPABILITY_ENFORCEMENT_ENABLED:
                    for capability in product_capabilities:
                        if not capability["alertable"]:
                            continue
                        finding_name = capability["finding_type"]
                        if finding_name not in finding_type_ids:
                            continue
                        if approval_silences(finding_name, approved, suppressed_by_approval):
                            continue
                        permitted, basis = _permitted(
                            authorizations, sanctioned, client_id,
                            capability["capability"], product_uuid,
                        )
                        if permitted:
                            continue
                        affected += _emit(
                            cur, tenant_id, finding_type_ids[finding_name],
                            client_id, device_id, name, publisher, "high", now,
                            {
                                "reason": "alertable capability product is not authorized here",
                                "not_permitted_basis": basis,
                                "capability": capability["capability"],
                                "evidence_sources": capability["sources"],
                                "product_uuid": str(product_uuid),
                            },
                            emitted_keys, subj,
                        )

                # Candidate evidence is deliberately a review prompt, not an
                # unauthorized finding. It is off by default until the seeded
                # publisher-rule corpus has been inspected in shadow mode.
                if settings.CAPABILITY_REVIEW_FINDINGS_ENABLED:
                    for capability in product_capabilities:
                        if capability["state"] != "candidate":
                            continue
                        finding_name = "capability_review_candidate"
                        if finding_name not in finding_type_ids or product_uuid is None:
                            continue
                        affected += _emit(
                            cur, tenant_id, finding_type_ids[finding_name],
                            client_id, device_id, name, publisher, "low", now,
                            {
                                "reason": "candidate capability evidence needs curator review",
                                "capability": capability["capability"],
                                "evidence_sources": capability["sources"],
                                "product_uuid": str(product_uuid),
                            },
                            emitted_keys, subj,
                        )

                # 4. multi_av_conflict — DISABLED by default.
                #
                # Two installed security-related packages do not mean two active
                # AV engines: leftover components, management consoles and EDR
                # sensors are not interchangeable, and installed-package
                # inventory cannot prove active protection. The finding claims
                # more than its evidence supports.
                #
                # It is also not approval-gateable. The finding is device-wide
                # while `dec` belongs to whichever installation the loop is on,
                # so suppression would depend on row order. Note that removing
                # the old blanket `continue` would otherwise *expose* new
                # occurrences, since that skip incidentally suppressed some.
                # Disabling is therefore required before deploy, not after.
                #
                # Re-enable only against a real active-protection signal
                # (Windows Security Center), or rename and lower it to
                # "multiple endpoint-security packages installed", which is what
                # this data can actually support.
                if (
                    cfg.get("multi_av_conflict_enabled", False)
                    and len(av_products_per_device.get(device_id, set())) >= 2
                ):
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
                if (
                    cfg.get("rare_recent_enabled", True)
                    and first_seen
                    and not approval_silences("rare_recent", approved, suppressed_by_approval)
                ):
                    skip = False
                    # Any prior decision (approve, approve_publisher,
                    # reject, investigate) means an operator already
                    # looked. The finding is defined as "recent AND rare AND
                    # undecided", so approval genuinely does silence it —
                    # `approval_silences` above covers approve/approve_publisher
                    # and this covers reject/investigate.
                    if cfg.get("rare_recent_skip_decided", True) and dec:
                        skip = True
                    # Categorization no longer suppresses. `categories`
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

                # 6. eol_runtime — a fact about the release. Approving software
                # does not extend its vendor support.
                if not approval_silences("eol_runtime", approved, suppressed_by_approval) and _matches_rules(
                    name, rules.get("eol_runtime", [])
                ):
                    affected += _emit(
                        cur, tenant_id, finding_type_ids["eol_runtime"],
                        client_id, device_id, name, publisher, "medium", now,
                        {"reason": "matches end-of-life runtime pattern"},
                        emitted_keys, subj,
                    )

                # 8. vulnerable_software — installed title has a matched
                # CVE that is either actively exploited (KEV) or severe
                # (CVSS >= cutoff).
                #
                # This previously re-tested the decision locally *as well as*
                # being skipped by the loop head, so it was suppressed twice.
                # Approval is a trust statement and cannot make a CVE untrue,
                # so the registry now says this type is not silenced by it.
                vuln = vuln_titles.get(name.lower())
                if vuln and not approval_silences("vulnerable_software", approved, suppressed_by_approval):
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
                # hint (OSINT is noisy).
                #
                # Also previously double-suppressed: skipped by the loop head
                # and re-tested here. Threat-intel accumulation is evidence
                # about the software, not a trust question, so approval no
                # longer hides it.
                hits = threat_hits.get(name.lower(), 0)
                if (
                    hits >= int(cfg.get("known_malicious_hint_min_hits", 3))
                    and not approval_silences("known_malicious_hint", approved, suppressed_by_approval)
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
                # uncategorized" review candidate. Distinct from
                # rare_recent (which fires at the ≤ 2 devices end); the
                # two are mutually exclusive by device_count threshold.
                # Suppression tests *decided*, not *labeled* (ADR-0015 §3).
                # This previously also required `not cat_list`, so tagging a
                # title `av` — a statement about what it does, carrying no
                # judgement — silenced the decision prompt exactly as a trust
                # label did. Trust is a decision and is covered by `dec`.
                if (
                    cfg.get("whitelist_suggestion_enabled", True)
                    and not dec
                    and not approval_silences("whitelist_suggestion", approved, suppressed_by_approval)
                ):
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
                                "reason": "uncategorized + undecided + widespread",
                            },
                            emitted_keys, subj,
                        )

            # Do not close capability findings while their producer is either
            # unavailable or deliberately in shadow mode. Neither a missing
            # schema nor a feature flag set to false is evidence that a
            # capability disappeared. Keeping the pre-existing findings until
            # the reviewed enforcement gate opens is safer than silently
            # resolving them on deploy.
            preserve_types = set()
            if not capability_ready or not settings.CAPABILITY_ENFORCEMENT_ENABLED:
                preserve_types.update({
                    "unauthorized_av", "unauthorized_rmm", "unauthorized_remote_access",
                })
            if not capability_ready or not settings.CAPABILITY_REVIEW_FINDINGS_ENABLED:
                preserve_types.add("capability_review_candidate")
            _auto_resolve(cur, tenant_id, emitted_keys, now, preserve_types)

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


def approval_silences(
    finding_type: str, approved: bool, matrix: dict[str, bool]
) -> bool:
    """Does an `approve` software decision silence this finding type?

    Replaces a blanket `continue` that skipped every rule for an approved
    installation, so approving a title also silenced its CVEs, threat-intel
    hits, end-of-life state and suspicious install path. Approval is a
    statement about *trust*; it cannot make a fact untrue.

    `matrix` comes from `finding_types.suppressed_by_approval` (migration
    0136), not from a constant here: it maps a domain value to a behavior,
    which ADR-0012 section 6 requires to be data and which
    `test_no_hardcoded_domain_mappings` would otherwise flag.

    An unregistered finding type defaults to **suppressed**, preserving the
    previous behavior rather than silently opening a new finding up. The same
    default applies when the column does not exist yet -- see `_load_scopes`.
    """
    if not approved:
        return False
    return matrix.get(finding_type, True)


def _column_exists(cur, qualified_table: str, column: str) -> bool:
    """Catalog probe, so the optional column is never queried blindly.

    Deliberately not a `try/except UndefinedColumn`. A failed statement aborts
    the whole transaction, and recovering from it would mean rolling back --
    which would also discard the `SET LOCAL operations.tenant_id` this
    classifier runs under. Every RLS-protected read afterwards would then
    return nothing and the run would report a successful zero-row pass. Asking
    the catalog first costs one cheap query and cannot poison the transaction.

    `to_regclass` yields NULL for a missing table rather than raising, so an
    absent table answers False too.
    """
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_attribute
             WHERE attrelid = to_regclass(%s)
               AND attname = %s
               AND attnum > 0
               AND NOT attisdropped
        )
        """,
        (qualified_table, column),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def _load_scopes(cur) -> tuple[dict[str, str], dict[str, bool]]:
    """(subject_scope, suppressed_by_approval) per finding type.

    `suppressed_by_approval` arrives with Operations migration 0136, which a
    *different* container applies. Ingest and Operations start concurrently and
    neither waits for the other, so a classifier catch-up can run against a
    schema where the column does not exist yet. Falling back to the pre-0136
    behavior -- everything suppressed by approval, expressed as an empty
    matrix -- keeps that window behaving exactly as it did before this change.
    """
    if not _column_exists(cur, "operations.finding_types", "suppressed_by_approval"):
        log.info(
            "finding_types.suppressed_by_approval absent (Operations migration "
            "0136 not yet applied); treating every finding as suppressed by "
            "approval, which is the pre-0136 behavior"
        )
        cur.execute("SELECT name, subject_scope FROM operations.finding_types")
        return {name: scope for name, scope in cur.fetchall()}, {}

    cur.execute(
        "SELECT name, subject_scope, suppressed_by_approval "
        "FROM operations.finding_types"
    )
    scopes: dict[str, str] = {}
    suppressed: dict[str, bool] = {}
    for name, scope, flag in cur.fetchall():
        scopes[name] = scope
        suppressed[name] = bool(flag)
    return scopes, suppressed


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


def _capability_schema_ready(cur) -> bool:
    """Catalog probe that never aborts the classifier transaction."""
    cur.execute(
        """
        SELECT bool_and(to_regclass(name) IS NOT NULL)
          FROM unnest(%s::text[]) AS name
        """,
        ([
            "catalog.capability",
            "catalog.v_product_capability_effective",
            "operations.platform_product_map",
            # Authorization is what suppresses an unauthorized finding, so a
            # missing table must fail closed to "capability not ready" rather
            # than leave enforcement running with nothing able to permit.
            "operations.product_authorizations",
        ],),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return False
    return _column_exists(cur, "catalog.capability", "unauthorized_finding_type")


def _load_effective_capabilities(cur) -> dict:
    """Global product capability truth, including its registered finding name."""
    cur.execute(
        """
        SELECT e.product_uuid, e.capability, e.state, e.alertable,
               e.evidence_sources, c.unauthorized_finding_type
          FROM catalog.v_product_capability_effective e
          JOIN catalog.capability c ON c.key = e.capability
        """
    )
    out: dict = {}
    for product_uuid, capability, state, alertable, sources, finding_type in cur.fetchall():
        out.setdefault(product_uuid, []).append(
            {
                "capability": capability,
                "state": state,
                "alertable": bool(alertable),
                "sources": sources,
                "finding_type": finding_type,
            }
        )
    return out


def _permitted(authorizations: dict, sanctioned: dict, client_id, capability: str,
               product_uuid) -> tuple[bool, str]:
    """Is this product allowed to carry this capability at this client?

    Two questions that must not share a field. A coverage requirement says what
    a client *must* run; an authorization says what it is *allowed* to run.
    Deriving the second from the first is what made the MSP's own ScreenConnect
    read as unauthorized on 3,007 devices across 70 clients, because the only
    way to permit it was to mandate it everywhere.

    First match wins, most specific first. Deny precedes permit at each tier so
    a client can be excluded from something permitted fleet-wide -- the case a
    single boolean cannot express. The required-platform mapping stays last and
    unchanged, so coverage semantics do not shift.

    Returns the decision and the rule that produced it, so a finding can say
    why it was not permitted rather than leaving it to be re-derived.
    """
    for scope, label in ((client_id, "client"), (None, "global")):
        tier = authorizations.get(scope, {}).get(capability)
        if not tier:
            continue
        if product_uuid in tier["deny"]:
            return False, f"{label} deny"
        if product_uuid in tier["permit"]:
            return True, f"{label} permit"
    if product_uuid in sanctioned.get(client_id, {}).get(capability, set()):
        return True, "required platform"
    return False, "no authorization and not mapped to a required platform"


def _load_authorizations(cur, tenant_id: int) -> dict:
    """scope -> capability -> {"permit": set, "deny": set}.

    The scope key is the client UUID, or None for the global tier. Withdrawn
    rows are excluded here rather than at the call site: a withdrawn
    authorization has no force, and filtering later would make that depend on
    every caller remembering to.
    """
    cur.execute(
        """
        SELECT client_id, capability, polarity, product_uuid
          FROM operations.product_authorizations
         WHERE tenant_id = %s AND withdrawn_at IS NULL
        """,
        (tenant_id,),
    )
    out: dict = {}
    for client_id, capability, polarity, product_uuid in cur.fetchall():
        tier = out.setdefault(client_id, {}).setdefault(
            capability, {"permit": set(), "deny": set()}
        )
        tier["permit" if polarity else "deny"].add(product_uuid)
    return out


def _load_sanctioned_product_identities(cur, tenant_id: int) -> dict:
    """Per client: capability -> exact catalog product UUIDs allowed by policy."""
    cur.execute(
        """
        WITH profile_platforms AS (
            SELECT c.id AS client_id, rpi.platform
              FROM operations.clients c
              JOIN operations.requirement_profile_items rpi
                ON rpi.tenant_id = c.tenant_id
               AND rpi.profile_id = c.requirement_profile_id
             WHERE c.tenant_id = %s AND c.deleted_at IS NULL
               AND rpi.platform <> ''
        ), fallback_platforms AS (
            SELECT c.id AS client_id, cr.platform
              FROM operations.clients c
              JOIN operations.coverage_requirements cr
                ON cr.tenant_id = c.tenant_id
               AND cr.client_id IS NULL AND cr.enabled
             WHERE c.tenant_id = %s AND c.deleted_at IS NULL
               AND c.requirement_profile_id IS NULL AND cr.platform <> ''
        ), required_platforms AS (
            SELECT * FROM profile_platforms
            UNION ALL
            SELECT * FROM fallback_platforms
        )
        SELECT rp.client_id, ppm.capability, ppm.product_uuid
          FROM required_platforms rp
          JOIN operations.agents a ON a.name = rp.platform
          JOIN operations.platform_product_map ppm
            ON ppm.agent_id = a.id AND ppm.enabled
        """,
        (tenant_id, tenant_id),
    )
    out: dict = {}
    for client_id, capability, product_uuid in cur.fetchall():
        out.setdefault(client_id, {}).setdefault(capability, set()).add(product_uuid)
    return out


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
             'known_malicious_hint', 'capability_review_candidate'
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
    # is the pre-0130 behavior and the safe default for any caller not yet
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


def _auto_resolve(
    cur, tenant_id: int, emitted_keys: set[str], now: datetime,
    preserve_types: set[str] | None = None,
) -> None:
    """Close any open software finding NOT emitted this run — the install
    is gone or a decision approved it."""
    preserve_types = preserve_types or set()
    # An empty emission set can mean that an upstream input failed open. The
    # established conservative behavior is to leave findings untouched rather
    # than treating no output as proof that every condition is gone.
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
           AND NOT (ft.name = ANY(%s::text[]))
        """,
        (now, now, tenant_id, list(emitted_keys), list(preserve_types)),
    )
