"""Software findings by desired-state reconciliation (rebuild design v2).

Each run computes, for every software finding type, the complete set of
findings that should be open now, then reconciles it with the open findings:
new conditions open, current ones refresh, and ones no longer true resolve with
a recorded reason. Facts are computed at their natural grain: title and version
facts once per title or version, device readiness once per device
(``software_readiness``), never once per installation and finding.

Assessments follow design D1/D4: a title-level finding has no per-device
assessment rows; its aggregate assessment comes from the condition engine and
is executable or notifiable only while at least one exposed device is ready.

Guardrails (no shadow period, D10): a per-type switch in the classifier
settings stops a type without touching its open findings; a close-rate limit
refuses to resolve a large share of a type's open findings in one run unless an
administrator allows it; every resolution records when and why.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ingest import db, software_capabilities, software_readiness
from ingest.conditions import load_active_profile
from ingest.config import settings
from shared import software_coverage, software_settings
from shared.conditions.contracts import Condition, EvaluationCoverage, Participant
from shared.conditions.engine import assess

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("open", "acknowledged", "investigating", "suppressed")
RESOLVABLE_STATUSES = ("open", "acknowledged")
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"

# Effective decision per installation and what it covers (shared with Operations).
EFFECTIVE_DECISION_JOINS = software_coverage.EFFECTIVE_DECISION_JOINS
_TITLE_DECISION = software_coverage.TITLE_DECISION
_PUBLISHER_DECISION = software_coverage.PUBLISHER_DECISION
_LIVE = "i.tenant_id = %(tenant_id)s AND i.stale_since IS NULL AND i.deleted_at IS NULL"

TITLE_FACTS_SQL = f"""
WITH installs AS (
    SELECT lower(i.canonical_name) AS title_key, i.canonical_name,
           COALESCE(i.publisher, '') AS publisher, i.device_id, i.client_id,
           i.first_observed_at, product.product_uuid,
           {_TITLE_DECISION} AS title_decision,
           {_PUBLISHER_DECISION} AS publisher_decision,
           {software_coverage.UNDECIDED} AS undecided_install,
           {software_coverage.TITLE_OPEN} AS title_open_install
      FROM operations.software_installations_current i
      LEFT JOIN catalog.software_versions version ON version.id = i.software_version_id
      LEFT JOIN catalog.products product ON product.id = version.product_id
      {EFFECTIVE_DECISION_JOINS}
     WHERE {_LIVE} AND i.canonical_name <> '' /*title_scope*/
)
SELECT title_key,
       max(canonical_name) AS canonical_name,
       mode() WITHIN GROUP (ORDER BY publisher) AS publisher,
       count(DISTINCT device_id) AS devices,
       count(DISTINCT client_id) AS clients,
       min(first_observed_at) AS first_seen,
       (array_agg(DISTINCT product_uuid) FILTER (WHERE product_uuid IS NOT NULL))[1]
           AS product_uuid,
       bool_or(COALESCE(title_decision, publisher_decision, '')
               NOT IN ('approve', 'approve_publisher')) AS has_unapproved,
       bool_or(title_decision IS NULL
               AND publisher_decision IN ('approve', 'approve_publisher'))
           AS has_publisher_only_approval,
       -- The installations no decision covers, which a prompt describes
       -- (ADR-0039), and those only a publisher approval covers (design D9).
       count(DISTINCT device_id) FILTER (WHERE undecided_install) AS undecided_devices,
       count(DISTINCT client_id) FILTER (WHERE undecided_install) AS undecided_clients,
       min(first_observed_at) FILTER (WHERE undecided_install) AS undecided_first_seen,
       mode() WITHIN GROUP (ORDER BY publisher) FILTER (WHERE undecided_install)
           AS undecided_publisher,
       array_agg(DISTINCT publisher) FILTER (WHERE undecided_install) AS undecided_publishers,
       count(DISTINCT device_id) FILTER (WHERE title_open_install) AS title_open_devices,
       count(DISTINCT client_id) FILTER (WHERE title_open_install) AS title_open_clients,
       min(first_observed_at) FILTER (WHERE title_open_install) AS title_open_first_seen,
       mode() WITHIN GROUP (ORDER BY publisher) FILTER (WHERE title_open_install)
           AS title_open_publisher,
       array_agg(DISTINCT publisher) FILTER (WHERE title_open_install) AS title_open_publishers,
       count(DISTINCT device_id) FILTER (
           WHERE COALESCE(title_decision, publisher_decision) = 'reject') AS rejected_devices,
       count(DISTINCT client_id) FILTER (
           WHERE COALESCE(title_decision, publisher_decision) = 'reject') AS rejected_clients
  FROM installs
 GROUP BY title_key
"""

VENDORS_SQL = "SELECT DISTINCT regexp_replace(lower(vendor), '[^a-z0-9]+', '_', 'g') FROM intel.cpes"

PUBLISHER_APPROVED_SQL = f"""
SELECT lower(COALESCE(i.publisher, '')), count(DISTINCT lower(i.canonical_name))
  FROM operations.software_installations_current i
  {EFFECTIVE_DECISION_JOINS}
 WHERE {_LIVE} AND i.canonical_name <> '' AND COALESCE(i.publisher, '') <> ''
   AND {_TITLE_DECISION} IN ('approve', 'approve_publisher')
 GROUP BY 1
"""

VERSION_FACTS_SQL = f"""
SELECT lower(i.canonical_name) AS title_key, version.version_uuid,
       max(version.version) AS version, count(DISTINCT i.device_id) AS devices
  FROM operations.software_installations_current i
  JOIN catalog.software_versions version ON version.id = i.software_version_id
 WHERE {_LIVE} AND i.canonical_name <> '' AND version.version_uuid IS NOT NULL /*title_scope*/
 GROUP BY lower(i.canonical_name), version.version_uuid
"""

VULNERABLE_SQL = """
SELECT lower(match.canonical_name), cve.cve_id, cve.cvss_v3, cve.epss_score, cve.kev_flag
  FROM operations.cve_match match
  JOIN intel.cves cve ON cve.cve_id = match.cve_id
 WHERE match.tenant_id = %(tenant_id)s /*match_scope*/
   AND (cve.kev_flag OR cve.cvss_v3 >= %(cvss_cutoff)s)
"""

THREAT_HITS_SQL = """
SELECT lower(canonical_name), lower(publisher), count(*)
  FROM operations.safety_signal
 WHERE tenant_id = %(tenant_id)s AND signal_type = 'threat_hit'
 GROUP BY 1, 2
"""

LOCATIONS_SQL = f"""
SELECT DISTINCT lower(i.install_location)
  FROM operations.software_installations_current i
 WHERE {_LIVE} AND COALESCE(i.install_location, '') <> ''
"""

PATH_INSTALLS_SQL = f"""
SELECT i.installation_uuid, i.device_id, i.client_id, lower(i.canonical_name),
       i.canonical_name, COALESCE(i.publisher, ''), i.install_location,
       {_TITLE_DECISION}, {_PUBLISHER_DECISION}
  FROM operations.software_installations_current i
  {EFFECTIVE_DECISION_JOINS}
 WHERE {_LIVE} AND lower(i.install_location) = ANY(%(locations)s) /*title_scope*/
   AND i.installation_uuid IS NOT NULL
"""

CAPABILITY_INSTALLS_SQL = f"""
SELECT i.device_id, i.client_id, lower(i.canonical_name), i.canonical_name,
       COALESCE(i.publisher, ''), product.product_uuid,
       {_TITLE_DECISION}, {_PUBLISHER_DECISION}
  FROM operations.software_installations_current i
  JOIN catalog.software_versions version ON version.id = i.software_version_id
  JOIN catalog.products product ON product.id = version.product_id
  {EFFECTIVE_DECISION_JOINS}
 WHERE {_LIVE} AND product.product_uuid = ANY(%(products)s) /*title_scope*/
"""

TYPES_SQL = """
SELECT id, name, subject_scope, suppressed_by_approval, concern_signal,
       default_severity, auto_resolvable
  FROM operations.finding_types
 WHERE source_module IN ('platform.software_findings', 'platform.capability_match')
"""


@dataclass(frozen=True)
class FindingType:
    id: int
    name: str
    subject_scope: str
    suppressed_by_approval: bool
    concern_signal: bool
    default_severity: str
    auto_resolvable: bool


@dataclass
class Desired:
    """One finding that should be open: the reconcile unit."""

    type_name: str
    condition_key: str
    subject_type: str
    subject_id: str
    client_id: str | None
    severity: str
    details: dict[str, Any]
    title_key: str = ""
    device_id: str | None = None


@dataclass
class RunReport:
    opened: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    refreshed: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    resolved: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    held_by_limit: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    disabled: list[str] = field(default_factory=list)
    unlinked: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    labels: dict[str, str] = field(default_factory=dict)
    scope_titles: int | None = None

    def describe(self) -> str:
        """One plain-English line for the Jobs pages, largest changes first."""
        opened, resolved = sum(self.opened.values()), sum(self.resolved.values())
        refreshed = sum(self.refreshed.values())
        scope = (
            "whole fleet" if self.scope_titles is None
            else f"{self.scope_titles:,} changed title{'s' if self.scope_titles != 1 else ''}"
        )
        text = (
            f"Software findings ({scope}): {opened:,} opened, {resolved:,} resolved, "
            f"{refreshed:,} still current."
        )
        changes = sorted(
            (
                (self.opened.get(name, 0) + self.resolved.get(name, 0), name)
                for name in set(self.opened) | set(self.resolved)
            ),
            reverse=True,
        )
        parts = [
            f"{self.labels.get(name, name.replace('_', ' '))}: "
            f"+{self.opened.get(name, 0):,} / -{self.resolved.get(name, 0):,}"
            for total, name in changes if total
        ]
        if parts:
            text += " " + "; ".join(parts[:6]) + ("; ..." if len(parts) > 6 else "") + "."
        held = sum(self.held_by_limit.values())
        if held:
            text += f" {held:,} resolutions held by the close limit for an administrator."
        return text

    def as_result(self) -> dict[str, Any]:
        return {
            "summary": self.describe(),
            "opened": dict(self.opened),
            "refreshed": dict(self.refreshed),
            "resolved": dict(self.resolved),
            "held_by_close_limit": dict(self.held_by_limit),
            "disabled_types": sorted(self.disabled),
            "unlinked_subjects": dict(self.unlinked),
        }


def condition_key(tenant_id: int, client_id: Any, device_id: Any, type_id: int, material: str) -> str:
    """Byte-identical to the previous classifier's keys (verified on production)."""
    raw = f"{tenant_id}:{client_id}:{device_id}:{type_id}:{material.lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def compile_rules(rows: Iterable[tuple[str, str, bool]]) -> dict[str, Callable[[str], bool]]:
    """rule_type -> predicate, matching the previous classifier's semantics."""
    grouped: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for rule_type, pattern, is_regex in rows:
        grouped[rule_type].append((pattern, bool(is_regex)))

    def predicate(rules: list[tuple[str, bool]]) -> Callable[[str], bool]:
        compiled = []
        literals = []
        for pattern, is_regex in rules:
            if is_regex:
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    log.warning("software_reconcile: invalid rule pattern skipped: %r", pattern)
            else:
                literals.append(pattern.lower())

        def matches(text: str) -> bool:
            lowered = (text or "").lower()
            return any(rule.search(lowered) for rule in compiled) or any(
                literal in lowered for literal in literals if lowered
            )

        return matches

    return {rule_type: predicate(rules) for rule_type, rules in grouped.items()}


def _never(_text: str) -> bool:
    return False


def _approved(decision: str | None) -> bool:
    return decision in ("approve", "approve_publisher")


def silenced(
    finding_type: FindingType,
    title_decision: str | None,
    publisher_decision: str | None,
    other_concern: bool,
) -> bool:
    """Does an approval silence this finding for one installation (design D9)?

    A title-level approval silences per the registry. A publisher-level approval
    silences only when no other signal of concern exists on the title or
    installation, because a publisher string is set by the installer.
    """
    if not finding_type.suppressed_by_approval:
        return False
    if _approved(title_decision):
        return True
    return title_decision is None and _approved(publisher_decision) and not other_concern


def _recent(first_seen: datetime | None, now: datetime, days: int) -> bool:
    if first_seen is None:
        return False
    if first_seen.tzinfo is None:
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    return first_seen >= now - timedelta(days=days)


def suggestion_for(
    rules: list[tuple],
    signals: set[str],
) -> str:
    """First enabled rule whose signals are present, adverse rules first.

    A rule is (priority, signal, adverse, suggestion[, requires]); it applies when
    its signal and every required signal are present.
    """
    ordered = sorted(rules, key=lambda rule: (not rule[2], rule[0]))
    for rule in ordered:
        signal, suggestion = rule[1], rule[3]
        requires = rule[4] if len(rule) > 4 and rule[4] else ()
        if (signal in signals or signal == "fallback") and all(
            required in signals for required in requires
        ):
            return suggestion
    return "none"


# Legal-form words dropped when comparing a publisher with a vendor name.
_LEGAL_FORMS = frozenset(
    "incorporated inc corporation corp limited ltd llc gmbh co company plc ag sa bv the".split()
)


def vendor_key(publisher: str) -> str:
    """Normalize a publisher the way vendor names are written in the CPE list."""
    words = re.findall(r"[a-z0-9]+", (publisher or "").lower())
    return "_".join(word for word in words if word not in _LEGAL_FORMS)


# ── Desired state ──────────────────────────────────────────────────────


@dataclass
class Context:
    tenant_id: int
    now: datetime
    cfg: dict[str, Any]
    types: dict[str, FindingType]
    rules: dict[str, Callable[[str], bool]]
    suggestion_rules: list[tuple]
    titles: dict[str, dict[str, Any]]
    versions: list[tuple[str, str, str, int]]
    vulnerable: dict[str, dict[str, Any]]
    threat_hits: dict[str, int]
    path_installs: list[tuple]
    capability_installs: list[tuple]
    capabilities: dict[Any, list[dict[str, Any]]]
    authorizations: dict
    sanctioned: dict
    # Publisher names of vendors in the vulnerability database, and how many
    # titles of each publisher are already approved here (lower-case keys).
    known_vendors: frozenset[str] = frozenset()
    publisher_approved: dict[str, int] = field(default_factory=dict)


def _rule(ctx: Context, name: str) -> Callable[[str], bool]:
    return ctx.rules.get(name, _never)


UNCOVERED_PUBLISHERS_SHOWN = 5


def prompt_scope(facts: dict[str, Any], rare_concern: bool, rare_max: int) -> str | None:
    """Which installations an undecided-software prompt is about, if one is due.

    A prompt is about the installations no decision covers. A rare title with
    another concern is also not answered by a publisher approval (design D9),
    so its prompt covers every installation without a title decision.
    """
    if rare_concern and 0 < facts["title_open_devices"] <= rare_max:
        return software_coverage.SCOPE_TITLE_OPEN
    if facts["undecided_devices"]:
        return software_coverage.SCOPE_UNDECIDED
    return None


def compute_desired(ctx: Context, report: RunReport) -> dict[str, list[Desired]]:
    """Return desired findings per enabled type. Pure over the loaded context."""
    cfg, types, tid = ctx.cfg, ctx.types, ctx.tenant_id
    rare_max = int(cfg["rare_max_devices"])
    recent_days = int(cfg["recent_days"])
    suspicious_name = _rule(ctx, "suspicious_name")
    eol_rule = _rule(ctx, "eol_runtime")
    junk_publisher = _rule(ctx, "junk_publisher")

    # Signals per title, before any approval: the evidence the concern rule and
    # the suggestions read.
    title_signals: dict[str, set[str]] = defaultdict(set)
    for title_key, facts in ctx.titles.items():
        if suspicious_name(facts["canonical_name"]):
            title_signals[title_key].add("suspicious_name")
        if ctx.threat_hits.get(title_key, 0) > 0:
            title_signals[title_key].add("threat_hit")
        if not facts["publisher"] or junk_publisher(facts["publisher"]):
            title_signals[title_key].add("junk_publisher")
    for row in ctx.path_installs:
        title_signals[row[3]].add("install_path")
    unauthorized_types: dict[str, set[str]] = defaultdict(set)

    # Which signals count as a concern is data: the finding type's
    # concern_signal flag, and for the junk-publisher rule (not a finding type)
    # whether its suggestion rule is adverse.
    signal_finding_type = {
        "suspicious_name": "suspicious_name",
        "install_path": "install_path_suspicious",
        "threat_hit": "known_malicious_hint",
    }
    junk_is_concern = any(
        rule[1] == "junk_publisher" and rule[2] for rule in ctx.suggestion_rules
    )

    def has_other_concern(title_key: str, exclude: str) -> bool:
        present = {
            signal_finding_type[s] for s in title_signals[title_key] if s in signal_finding_type
        } | unauthorized_types[title_key]
        concerns = {name for name in present if name in types and types[name].concern_signal}
        if junk_is_concern and "junk_publisher" in title_signals[title_key]:
            concerns.add("junk_publisher")
        return bool(concerns - {exclude})

    # Facts that support a decision rather than warn against it.
    supporting = {"prevalent", "established_publisher", "known_vendor", "publisher_approved"}
    desired: dict[str, list[Desired]] = defaultdict(list)

    def enabled(type_name: str, setting: str | None) -> bool:
        if type_name not in types:
            return False
        if setting and not bool(cfg.get(setting, True)):
            report.disabled.append(type_name)
            return False
        return True

    # Device-level: unauthorized capability (fail-closed gate, ADR-0018).
    if settings.CAPABILITY_ENFORCEMENT_ENABLED:
        for (device_id, client_id, title_key, name, publisher, product_uuid,
             title_decision, publisher_decision) in ctx.capability_installs:
            for capability in ctx.capabilities.get(product_uuid, []):
                finding_name = capability["finding_type"]
                if not capability["alertable"] or finding_name not in types:
                    continue
                permitted, basis = _permitted(
                    ctx.authorizations, ctx.sanctioned, client_id, capability["capability"],
                    product_uuid,
                )
                if permitted:
                    continue
                unauthorized_types[title_key].add(finding_name)
                ft = types[finding_name]
                if silenced(ft, title_decision, publisher_decision,
                            has_other_concern(title_key, finding_name)):
                    continue
                desired[finding_name].append(Desired(
                    finding_name,
                    condition_key(tid, client_id, device_id, ft.id, name),
                    "device", str(device_id), str(client_id) if client_id else None,
                    ft.default_severity,
                    {
                        "canonical_name": name, "publisher": publisher,
                        "reason": "alertable capability product is not authorized here",
                        "not_permitted_basis": basis,
                        "capability": capability["capability"],
                        "evidence_sources": capability["sources"],
                        "product_uuid": str(product_uuid),
                    },
                    title_key=title_key, device_id=str(device_id),
                ))

    # Installation-level: suspicious install path (a fact; not silenced).
    if enabled("install_path_suspicious", "install_path_enabled"):
        ft = types["install_path_suspicious"]
        for (installation_uuid, device_id, client_id, title_key, name, publisher, location,
             title_decision, publisher_decision) in ctx.path_installs:
            if silenced(ft, title_decision, publisher_decision,
                        has_other_concern(title_key, "install_path_suspicious")):
                continue
            desired[ft.name].append(Desired(
                ft.name,
                condition_key(tid, None, None, ft.id, f"{name}@{installation_uuid}"),
                "software_installation", str(installation_uuid), None, ft.default_severity,
                {"canonical_name": name, "publisher": publisher,
                 "reason": "suspicious install path", "location": location},
                title_key=title_key, device_id=str(device_id),
            ))

    for title_key, facts in ctx.titles.items():
        name, publisher, product_uuid = (
            facts["canonical_name"], facts["publisher"], facts["product_uuid"],
        )
        base = {"canonical_name": name, "publisher": publisher}

        def product_finding(type_name: str, severity: str, extra: dict[str, Any]) -> None:
            ft = types[type_name]
            if product_uuid is None:
                report.unlinked[type_name] += 1
                return
            desired[type_name].append(Desired(
                type_name, condition_key(tid, None, None, ft.id, name),
                "software_product", str(product_uuid), None, severity,
                {**base, **extra}, title_key=title_key,
            ))

        def silenced_title(type_name: str) -> bool:
            ft = types[type_name]
            if not ft.suppressed_by_approval or facts["has_unapproved"]:
                return False
            if facts["has_publisher_only_approval"]:
                return not has_other_concern(title_key, type_name)
            return True

        if ("suspicious_name" in title_signals[title_key]
                and enabled("suspicious_name", "suspicious_name_enabled")):
            if not silenced_title("suspicious_name"):
                product_finding("suspicious_name", types["suspicious_name"].default_severity,
                                {"reason": "suspicious_name pattern match"})

        # A rejection is a decision, not a signal an approval can silence: the
        # finding stays while any installation's effective decision is reject.
        if (facts.get("rejected_devices")
                and enabled("rejected_software_installed", "rejected_installed_enabled")):
            product_finding("rejected_software_installed",
                            str(cfg["rejected_installed_severity"]),
                            {"rejected_device_count": facts["rejected_devices"],
                             "rejected_client_count": facts.get("rejected_clients") or 0,
                             "reason": "rejected software is still installed"})

        hits = ctx.threat_hits.get(title_key, 0)
        if (hits >= int(cfg["known_malicious_hint_min_hits"])
                and enabled("known_malicious_hint", "known_malicious_hint_enabled")
                and not silenced_title("known_malicious_hint")):
            product_finding("known_malicious_hint", str(cfg["known_malicious_hint_severity"]),
                            {"threat_hit_count": hits,
                             "reason": "community threat-intel accumulation"})

        scope = prompt_scope(facts, has_other_concern(title_key, "rare_recent"), rare_max)
        if scope:
            # The prompt describes only the installations it is about: their
            # count decides rare, their publisher groups and closes it, and
            # their first sighting dates it (ADR-0039). Fleet-wide facts stay
            # as supporting evidence.
            uncovered = facts[f"{scope}_devices"]
            publisher_now = facts[f"{scope}_publisher"] or ""
            publishers = sorted(facts[f"{scope}_publishers"] or [])
            first_seen = facts[f"{scope}_first_seen"]
            rare = uncovered <= rare_max
            recent = _recent(first_seen, ctx.now, recent_days)
            signals = set(title_signals[title_key])
            if unauthorized_types[title_key]:
                signals.add("unauthorized_capability")
            if (facts["clients"] >= int(cfg["suggestion_min_clients"])
                    and not _recent(facts["first_seen"], ctx.now,
                                    int(cfg["suggestion_min_age_days"]))):
                signals.add("established_publisher")
            if facts["devices"] > rare_max:
                signals.add("prevalent")
            if vendor_key(publisher_now) in ctx.known_vendors:
                signals.add("known_vendor")
            if (ctx.publisher_approved.get(publisher_now.lower(), 0)
                    >= int(cfg["suggestion_min_approved_titles"])):
                signals.add("publisher_approved")
            details = {
                "publisher": publisher_now,
                "title_publisher": facts["publisher"],
                "coverage_scope": scope,
                "fleet_device_count": facts["devices"],
                "client_count": facts["clients"],
                "uncovered_device_count": uncovered,
                "uncovered_client_count": facts[f"{scope}_clients"],
                "uncovered_publishers": publishers[:UNCOVERED_PUBLISHERS_SHOWN],
                "uncovered_publisher_count": len(publishers),
                "first_seen_at": first_seen.isoformat() if first_seen else None,
                "recent": recent,
                "signals": sorted(signals - supporting),
                "evidence": sorted(signals & supporting),
                "suggestion": suggestion_for(ctx.suggestion_rules, signals),
            }
            if rare:
                if enabled("rare_recent", "rare_enabled"):
                    severity = cfg["rare_recent_severity"] if recent else cfg["rare_older_severity"]
                    product_finding("rare_recent", str(severity),
                                    {**details, "reason": "undecided software on few devices"})
            elif enabled("whitelist_suggestion", "non_approved_enabled"):
                severity = (cfg["non_approved_recent_severity"] if recent
                            else cfg["non_approved_severity"])
                product_finding("whitelist_suggestion", str(severity),
                                {**details, "reason": "undecided software"})

    vulnerable_on = enabled("vulnerable_software", "vulnerable_software_enabled")
    eol_on = enabled("eol_runtime", "eol_runtime_enabled")
    for title_key, version_uuid, version, devices in ctx.versions:
        facts = ctx.titles.get(title_key)
        if facts is None:
            continue
        name, publisher = facts["canonical_name"], facts["publisher"]
        vuln = ctx.vulnerable.get(title_key)
        if vulnerable_on and vuln:
            ft = types["vulnerable_software"]
            if vuln["kev"]:
                severity = str(cfg["vulnerable_software_severity_kev"])
                extra = {"reason": "actively exploited vulnerability (CISA KEV)",
                         "kev_cves": vuln["kev"][:5], "high_cves": vuln["high"][:5]}
            else:
                severity = str(cfg["vulnerable_software_severity_high"])
                extra = {"reason": "severe vulnerability (CVSS >= cutoff)",
                         "high_cves": vuln["high"][:5]}
            desired[ft.name].append(Desired(
                ft.name, condition_key(tid, None, None, ft.id, f"{name}@{version_uuid}"),
                "software_version", str(version_uuid), None, severity,
                {"canonical_name": name, "publisher": publisher, "version": version,
                 "device_count": devices, "worst_cvss": vuln["worst_cvss"],
                 "max_epss": vuln["max_epss"], **extra},
                title_key=title_key,
            ))
        if eol_on and eol_rule(name):
            ft = types["eol_runtime"]
            desired[ft.name].append(Desired(
                ft.name, condition_key(tid, None, None, ft.id, f"{name}@{version_uuid}"),
                "software_version", str(version_uuid), None, ft.default_severity,
                {"canonical_name": name, "publisher": publisher, "version": version,
                 "device_count": devices, "reason": "matches end-of-life runtime pattern"},
                title_key=title_key,
            ))
    return desired


def _permitted(authorizations: dict, sanctioned: dict, client_id: Any, capability: str,
               product_uuid: Any) -> tuple[bool, str]:
    """Most specific first; deny before permit; required platform last (ADR-0018)."""
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


# ── Loading ────────────────────────────────────────────────────────────


def scoped(sql: str, titles: list[str] | None) -> str:
    """Limit a query to the given title keys; None keeps the whole fleet."""
    if titles is None:
        return sql.replace("/*title_scope*/", "").replace("/*match_scope*/", "")
    return sql.replace(
        "/*title_scope*/", "AND lower(i.canonical_name) = ANY(%(titles)s)"
    ).replace("/*match_scope*/", "AND lower(match.canonical_name) = ANY(%(titles)s)")


def load_context(
    cur: Any, tenant_id: int, now: datetime, scope_titles: list[str] | None = None
) -> Context:
    cur.execute(
        "SELECT config FROM operations.evaluator_config "
        "WHERE tenant_id = %s AND evaluator_name = 'software_classifier'",
        (tenant_id,),
    )
    row = cur.fetchone()
    cfg = software_settings.effective(row[0] if row and isinstance(row[0], dict) else {})
    params = {"tenant_id": tenant_id, "titles": scope_titles}

    cur.execute(TYPES_SQL)
    types = {r[1]: FindingType(*r) for r in cur.fetchall()}
    cur.execute(
        "SELECT rule_type, pattern, is_regex FROM operations.software_classifier_rules WHERE enabled"
    )
    rules = compile_rules(cur.fetchall())
    cur.execute(
        "SELECT priority, signal, adverse, suggestion, requires "
        "FROM operations.software_suggestion_rules WHERE enabled ORDER BY priority, id"
    )
    suggestion_rules = [tuple(r) for r in cur.fetchall()]

    known_vendors: frozenset[str] = frozenset()
    cur.execute("SELECT to_regclass('intel.cpes')")
    if cur.fetchone()[0] is not None:
        cur.execute(VENDORS_SQL)
        known_vendors = frozenset(r[0] for r in cur.fetchall() if r[0])
    cur.execute(PUBLISHER_APPROVED_SQL, params)
    publisher_approved = {r[0]: int(r[1]) for r in cur.fetchall()}

    cur.execute(scoped(TITLE_FACTS_SQL, scope_titles), params)
    columns = [d[0] for d in cur.description]
    titles = {r[0]: dict(zip(columns, r)) for r in cur.fetchall()}
    cur.execute(scoped(VERSION_FACTS_SQL, scope_titles), params)
    versions = [(r[0], str(r[1]), r[2] or "", int(r[3])) for r in cur.fetchall()]

    cur.execute(scoped(VULNERABLE_SQL, scope_titles), {**params, "cvss_cutoff": float(cfg["vulnerable_software_cvss_cutoff"])})
    vulnerable: dict[str, dict[str, Any]] = {}
    cutoff = float(cfg["vulnerable_software_cvss_cutoff"])
    for title_key, cve_id, cvss, epss, kev in cur.fetchall():
        entry = vulnerable.setdefault(
            title_key, {"kev": [], "high": [], "worst_cvss": 0.0, "max_epss": 0.0}
        )
        if kev:
            entry["kev"].append(cve_id)
        elif cvss is not None and float(cvss) >= cutoff:
            entry["high"].append(cve_id)
        if cvss is not None:
            entry["worst_cvss"] = max(entry["worst_cvss"], float(cvss))
        if epss is not None:
            entry["max_epss"] = max(entry["max_epss"], float(epss))

    cur.execute(THREAT_HITS_SQL, params)
    title_hits: dict[str, int] = defaultdict(int)
    publisher_hits: dict[str, int] = defaultdict(int)
    for title_key, publisher_key, count in cur.fetchall():
        if title_key:
            title_hits[title_key] += int(count)
        if publisher_key:
            publisher_hits[publisher_key] += int(count)
    threat_hits = {
        key: title_hits.get(key, 0) + publisher_hits.get((facts["publisher"] or "").lower(), 0)
        for key, facts in titles.items()
    }
    threat_hits = {key: hits for key, hits in threat_hits.items() if hits}

    path_rule = rules.get("install_path_suspicious", _never)
    cur.execute(LOCATIONS_SQL, params)
    locations = [r[0] for r in cur.fetchall() if path_rule(r[0])]
    path_installs: list[tuple] = []
    if locations:
        cur.execute(scoped(PATH_INSTALLS_SQL, scope_titles), {**params, "locations": locations})
        path_installs = list(cur.fetchall())

    capabilities: dict = {}
    authorizations: dict = {}
    sanctioned: dict = {}
    capability_installs: list[tuple] = []
    if software_capabilities.capability_schema_ready(cur):
        capabilities = software_capabilities.load_effective_capabilities(cur)
        authorizations = software_capabilities.load_authorizations(cur, tenant_id)
        sanctioned = software_capabilities.load_sanctioned_product_identities(cur, tenant_id)
        alertable = [p for p, caps in capabilities.items() if any(c["alertable"] for c in caps)]
        if alertable:
            cur.execute(scoped(CAPABILITY_INSTALLS_SQL, scope_titles), {**params, "products": alertable})
            capability_installs = list(cur.fetchall())

    return Context(
        tenant_id, now, cfg, types, rules, suggestion_rules, titles, versions, vulnerable,
        threat_hits, path_installs, capability_installs, capabilities, authorizations, sanctioned,
        known_vendors, publisher_approved,
    )


# ── Reconcile ──────────────────────────────────────────────────────────


def _copy(cur: Any, table: str, columns: str, types: list[str], rows: Iterable[tuple]) -> None:
    with cur.copy(f"COPY {table} ({columns}) FROM STDIN") as copy:
        copy.set_types(types)
        for row in rows:
            copy.write_row(row)


def reconcile_type(
    cur: Any,
    ctx: Context,
    finding_type: FindingType,
    rows: list[Desired],
    report: RunReport,
    titles: list[str] | None = None,
) -> None:
    """Open, refresh and resolve one type's findings against its desired set.

    With ``titles`` only findings of those title keys are compared: the desired
    set was computed for them alone, so findings of other titles are outside
    this run and stay as they are.
    """
    tid, now = ctx.tenant_id, ctx.now
    cur.execute(
        "CREATE TEMP TABLE IF NOT EXISTS software_desired ("
        " condition_key TEXT, client_id UUID, subject_type TEXT, subject_id UUID,"
        " severity TEXT, details JSONB) ON COMMIT DROP"
    )
    cur.execute("TRUNCATE software_desired")
    unique: dict[str, Desired] = {}
    for row in rows:
        unique.setdefault(row.condition_key, row)
    _copy(
        cur, "software_desired",
        "condition_key, client_id, subject_type, subject_id, severity, details",
        ["text", "uuid", "text", "uuid", "text", "jsonb"],
        ((r.condition_key, r.client_id, r.subject_type, r.subject_id, r.severity,
          json.dumps(r.details, default=str)) for r in unique.values()),
    )
    active = list(ACTIVE_STATUSES)
    cur.execute(
        """
        UPDATE operations.findings finding
           SET last_seen_at = %(now)s, last_detected_at = %(now)s,
               finding_details = desired.details, severity = desired.severity
          FROM software_desired desired
         WHERE finding.tenant_id = %(tid)s AND finding.finding_type_id = %(type_id)s
           AND finding.condition_key = desired.condition_key
           AND finding.status = ANY(%(active)s)
        """,
        {"now": now, "tid": tid, "type_id": finding_type.id, "active": active},
    )
    report.refreshed[finding_type.name] += max(cur.rowcount, 0)
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id, subject_type, subject_id,
            finding_details, condition_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        )
        SELECT gen_random_uuid(), 1, %(tid)s, %(type_id)s, desired.client_id,
               desired.subject_type, desired.subject_id, desired.details,
               desired.condition_key, desired.severity, 'confirmed', 'open',
               %(now)s, %(now)s, %(now)s
          FROM software_desired desired
         WHERE NOT EXISTS (
             SELECT 1 FROM operations.findings existing
              WHERE existing.tenant_id = %(tid)s
                AND existing.condition_key = desired.condition_key
                AND existing.status = ANY(%(active)s)
         )
        """,
        {"now": now, "tid": tid, "type_id": finding_type.id, "active": active},
    )
    report.opened[finding_type.name] += max(cur.rowcount, 0)

    if not finding_type.auto_resolvable:
        return
    resolution = {
        "resolution": {
            "reason": "no_longer_detected",
            "detail": "The condition no longer holds: the software is gone, a decision "
                      "covers it, or its evidence changed.",
            "resolved_by": "software_reconcile",
            "resolved_at": now.isoformat(),
        }
    }
    # Grain change: findings whose subject kind no longer matches the type's
    # registered scope are superseded, outside the close-rate limit.
    cur.execute(
        """
        UPDATE operations.findings finding
           SET status = 'resolved', closed_at = COALESCE(finding.closed_at, %(now)s),
               last_seen_at = %(now)s,
               finding_details = finding.finding_details || %(resolution)s::jsonb
         WHERE finding.tenant_id = %(tid)s AND finding.finding_type_id = %(type_id)s
           AND finding.status = ANY(%(resolvable)s)
           AND finding.subject_type <> %(scope)s
           AND (%(titles)s::text[] IS NULL OR lower(finding.finding_details->>'canonical_name') = ANY(%(titles)s::text[]))
        """,
        {
            "titles": titles,
            "now": now, "tid": tid, "type_id": finding_type.id,
            "resolvable": list(RESOLVABLE_STATUSES), "scope": finding_type.subject_scope,
            "resolution": json.dumps({"resolution": {
                **resolution["resolution"], "reason": "subject_regrained",
                "detail": "This type is now raised per "
                          f"{finding_type.subject_scope.replace('_', ' ')}; the previous "
                          "finding is superseded by one at that grain.",
            }}),
        },
    )
    report.resolved[finding_type.name] += max(cur.rowcount, 0)

    cur.execute(
        """
        SELECT count(*) FILTER (WHERE desired.condition_key IS NULL), count(*)
          FROM operations.findings finding
          LEFT JOIN software_desired desired ON desired.condition_key = finding.condition_key
         WHERE finding.tenant_id = %(tid)s AND finding.finding_type_id = %(type_id)s
           AND finding.status = ANY(%(resolvable)s)
           AND (%(titles)s::text[] IS NULL OR lower(finding.finding_details->>'canonical_name') = ANY(%(titles)s::text[]))
        """,
        {"tid": tid, "type_id": finding_type.id, "resolvable": list(RESOLVABLE_STATUSES),
         "titles": titles},
    )
    to_close, open_total = cur.fetchone()
    limit = int(ctx.cfg["reconcile_max_close_percent"])
    if (to_close and open_total >= 20 and to_close * 100 > open_total * limit
            and not ctx.cfg["reconcile_allow_large_close"]):
        report.held_by_limit[finding_type.name] = int(to_close)
        log.warning(
            "software_reconcile: %s would resolve %d of %d open findings (> %d%%); held",
            finding_type.name, to_close, open_total, limit,
        )
        return
    cur.execute(
        """
        UPDATE operations.findings finding
           SET status = 'resolved', closed_at = COALESCE(finding.closed_at, %(now)s),
               last_seen_at = %(now)s,
               finding_details = finding.finding_details || %(resolution)s::jsonb
         WHERE finding.tenant_id = %(tid)s AND finding.finding_type_id = %(type_id)s
           AND finding.status = ANY(%(resolvable)s)
           AND NOT EXISTS (
               SELECT 1 FROM software_desired desired
                WHERE desired.condition_key = finding.condition_key
           )
           AND (%(titles)s::text[] IS NULL OR lower(finding.finding_details->>'canonical_name') = ANY(%(titles)s::text[]))
        """,
        {"now": now, "tid": tid, "type_id": finding_type.id, "titles": titles,
         "resolvable": list(RESOLVABLE_STATUSES), "resolution": json.dumps(resolution)},
    )
    report.resolved[finding_type.name] += max(cur.rowcount, 0)


# ── Assessments (D1, D4) ───────────────────────────────────────────────

ACTIVE_FINDINGS_SQL = """
SELECT finding.id::text, finding_type.id, finding_type.name, finding.condition_key,
       finding.status, finding.snoozed_until, finding.subject_type, finding.subject_id::text,
       installation.device_id::text
  FROM operations.findings finding
  JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
  LEFT JOIN operations.software_installations_current installation
    ON finding.subject_type = 'software_installation'
   AND installation.installation_uuid = finding.subject_id
 WHERE finding.tenant_id = %(tid)s AND finding_type.id = ANY(%(type_ids)s)
   AND finding.status = ANY(%(active)s)
   AND (%(titles)s::text[] IS NULL OR lower(finding.finding_details->>'canonical_name') = ANY(%(titles)s::text[]))
"""

# Any ready device among a title-level finding's installations, per finding.
READY_EXPOSURE_SQL = """
WITH title_findings AS (
    SELECT finding.id, finding.finding_type_id, finding.subject_type, finding.subject_id
      FROM operations.findings finding
     WHERE finding.tenant_id = %(tid)s AND finding.finding_type_id = ANY(%(type_ids)s)
       AND finding.status = ANY(%(active)s)
       AND finding.subject_type IN ('software_product', 'software_version')
       AND (%(titles)s::text[] IS NULL OR lower(finding.finding_details->>'canonical_name') = ANY(%(titles)s::text[]))
), exposed AS (
    SELECT finding.id, installation.device_id, finding.finding_type_id
      FROM title_findings finding
      JOIN catalog.products product ON product.product_uuid = finding.subject_id
      JOIN catalog.software_versions version ON version.product_id = product.id
      JOIN operations.software_installations_current installation
        ON installation.software_version_id = version.id
     WHERE finding.subject_type = 'software_product'
       AND installation.tenant_id = %(tid)s
       AND installation.stale_since IS NULL AND installation.deleted_at IS NULL
    UNION
    SELECT finding.id, installation.device_id, finding.finding_type_id
      FROM title_findings finding
      JOIN catalog.software_versions version ON version.version_uuid = finding.subject_id
      JOIN operations.software_installations_current installation
        ON installation.software_version_id = version.id
     WHERE finding.subject_type = 'software_version'
       AND installation.tenant_id = %(tid)s
       AND installation.stale_since IS NULL AND installation.deleted_at IS NULL
)
SELECT exposed.id::text,
       bool_or(readiness.may_execute) AS any_execute,
       bool_or(readiness.may_notify) AS any_notify,
       count(*) FILTER (WHERE readiness.may_execute) AS ready_devices,
       count(*) AS exposed_devices
  FROM exposed
  LEFT JOIN operations.software_device_readiness readiness
    ON readiness.tenant_id = %(tid)s AND readiness.device_id = exposed.device_id
   AND readiness.finding_type_id = exposed.finding_type_id
 GROUP BY exposed.id
"""

READINESS_SQL = """
SELECT device_id::text, finding_type_id, disposition, may_notify, may_execute, reasons, blockers
  FROM operations.software_device_readiness
 WHERE tenant_id = %(tid)s
"""


def _response(identity: str, participant: Participant | None, disposition: str,
              may_notify: bool, may_execute: bool, reasons: list[str],
              blockers: list[str], coverage: EvaluationCoverage) -> dict[str, Any]:
    return {
        "condition_identity": identity,
        "participant": None if participant is None else {
            "kind": participant.kind, "reference": participant.reference,
            "role": participant.role, "tenant_id": participant.tenant_id,
        },
        "disposition": disposition,
        "may_evaluate": disposition not in ("blocked", "unknown"),
        "may_notify": may_notify,
        "may_execute": may_execute,
        "may_clear": may_execute and coverage.permits_clearing,
        "coverage_recovery_required": not coverage.permits_clearing,
        "reasons": sorted(set(reasons)),
        "blockers": sorted(set(blockers)),
    }


def assessment_rows(
    *,
    tenant_id: int,
    now: datetime,
    profile: Any,
    findings: Iterable[tuple],
    ready_exposure: dict[str, tuple[bool, bool, int, int]],
    readiness: dict[tuple[str, int], tuple],
) -> tuple[list[tuple], list[tuple]]:
    """Participants and assessments for every active reconciled finding. Pure."""
    coverage = EvaluationCoverage(True, True, True, True)
    coverage_json = json.dumps({"succeeded": True, "complete": True, "fresh": True,
                                "scope_matches": True})
    participants: list[tuple] = []
    assessments: list[tuple] = []
    for (finding_id, type_id, type_name, key, status, snoozed_until, subject_type,
         subject_id, installation_device) in findings:
        if subject_type in ("software_product", "software_version"):
            members = (Participant(subject_type, subject_id, "affected", tenant_id),)
        elif subject_type == "software_installation":
            members = tuple(
                p for p in (
                    Participant("device", installation_device, "affected", tenant_id)
                    if installation_device else None,
                    Participant("software_installation", subject_id, "affected", tenant_id),
                ) if p is not None
            )
        else:
            members = (Participant("device", subject_id, "affected", tenant_id),)
        condition = Condition(tenant_id, "entity", finding_id, type_name, key, status,
                              members, snoozed_until)
        identity = condition.identity
        handling_ok = not (status in ("suppressed", "wontfix") or (
            snoozed_until is not None and snoozed_until > now))
        membership = hashlib.sha256(json.dumps(
            [[m.kind, m.reference, m.role] for m in members]).encode()).hexdigest()

        def emit(participant: Participant | None, disposition: str, notify: bool,
                 execute: bool, reasons: list[str], blockers: list[str]) -> None:
            response = _response(identity, participant, disposition, notify, execute,
                                 reasons, blockers, coverage)
            watermark = hashlib.sha256(json.dumps(
                [profile.digest, response, membership], sort_keys=True, default=str
            ).encode()).hexdigest()[:24]
            kind, ref, role = (
                ("condition", _ZERO_UUID, "aggregate") if participant is None
                else (participant.kind, participant.reference, participant.role)
            )
            assessments.append((
                tenant_id, "entity", finding_id, kind, ref, role, identity,
                profile.version, profile.digest, coverage_json, json.dumps(response),
                f"software:{key}:{watermark}",
                json.dumps({"evidence": watermark, "membership": membership,
                            "handling": status}),
                now,
            ))

        if subject_type in ("software_product", "software_version"):
            decision = assess(condition, profile, (), now, None)
            any_execute, any_notify, ready, exposed = ready_exposure.get(
                finding_id, (False, False, 0, 0))
            reasons = list(decision.reasons)
            disposition = decision.disposition
            execute = decision.may_execute and bool(any_execute)
            notify = decision.may_notify and bool(any_notify)
            if decision.disposition == "eligible" and not any_execute:
                disposition = "unknown"
                reasons.append("exposure:no_ready_device" if exposed else "exposure:no_live_install")
            emit(None, disposition, notify, execute, reasons, list(decision.blockers))
            subject_decision = assess(condition, profile, (), now, members[0])
            emit(members[0], subject_decision.disposition, subject_decision.may_notify,
                 subject_decision.may_execute, list(subject_decision.reasons),
                 list(subject_decision.blockers))
        else:
            device = next((m for m in members if m.kind == "device"), None)
            state = readiness.get((device.reference, type_id)) if device else None
            if state is None:
                disposition, notify, execute = "unknown", False, False
                reasons, blockers = ["readiness:not_measured"], []
            else:
                disposition, notify, execute, reasons, blockers = state
                reasons, blockers = list(reasons or []), list(blockers or [])
            if not handling_ok and disposition == "eligible":
                disposition, notify, execute = "suppressed", False, False
                reasons.append("existing_operator_suppression")
            for member in (None, *members):
                emit(member, disposition, notify, execute, reasons, blockers)
        participants.extend(
            (tenant_id, "entity", finding_id, m.kind, m.reference, m.role) for m in members
        )
    return participants, assessments


def write_assessments(
    cur: Any, ctx: Context, type_ids: list[int], profile: Any, titles: list[str] | None = None
) -> int:
    """Rewrite participants and assessments of the run's findings (``titles`` scopes it)."""
    params = {"tid": ctx.tenant_id, "type_ids": type_ids, "active": list(ACTIVE_STATUSES),
              "titles": titles}
    cur.execute(ACTIVE_FINDINGS_SQL, params)
    findings = cur.fetchall()
    cur.execute(READY_EXPOSURE_SQL, params)
    ready = {r[0]: (r[1], r[2], int(r[3]), int(r[4])) for r in cur.fetchall()}
    cur.execute(READINESS_SQL, params)
    readiness = {(r[0], r[1]): (r[2], r[3], r[4], r[5], r[6]) for r in cur.fetchall()}
    participants, assessments = assessment_rows(
        tenant_id=ctx.tenant_id, now=ctx.now, profile=profile, findings=findings,
        ready_exposure=ready, readiness=readiness,
    )
    cur.execute(
        "CREATE TEMP TABLE software_participants_next "
        "(LIKE operations.condition_participants) ON COMMIT DROP"
    )
    _copy(cur, "software_participants_next",
          "tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role",
          ["bigint", "text", "uuid", "text", "uuid", "text"], participants)
    cur.execute(
        "CREATE TEMP TABLE software_assessments_next "
        "(LIKE operations.condition_assessments INCLUDING DEFAULTS) ON COMMIT DROP"
    )
    _copy(cur, "software_assessments_next",
          "tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role, "
          "condition_identity, policy_version, policy_digest, coverage, response, "
          "reevaluation_key, currentness, assessed_at",
          ["bigint", "text", "uuid", "text", "uuid", "text", "text", "text", "text",
           "jsonb", "jsonb", "text", "jsonb", "timestamptz"], assessments)
    finding_ids = sorted({f[0] for f in findings})
    scope = {"tid": ctx.tenant_id, "ids": finding_ids}
    # Remove members and assessments the derived model no longer has, including
    # the per-device rows title findings carried before (design D1).
    cur.execute(
        """
        DELETE FROM operations.condition_participants current
         WHERE current.tenant_id = %(tid)s AND current.row_kind = 'entity'
           AND current.finding_id = ANY(%(ids)s::uuid[])
           AND NOT EXISTS (
               SELECT 1 FROM software_participants_next next
                WHERE next.finding_id = current.finding_id
                  AND next.participant_kind = current.participant_kind
                  AND next.participant_id = current.participant_id
                  AND next.participant_role = current.participant_role)
        """, scope,
    )
    cur.execute(
        """
        DELETE FROM operations.condition_assessments current
         WHERE current.tenant_id = %(tid)s AND current.row_kind = 'entity'
           AND current.finding_id = ANY(%(ids)s::uuid[])
           AND NOT EXISTS (
               SELECT 1 FROM software_assessments_next next
                WHERE next.finding_id = current.finding_id
                  AND next.participant_kind = current.participant_kind
                  AND next.participant_id = current.participant_id
                  AND next.participant_role = current.participant_role)
        """, scope,
    )
    cur.execute(
        """
        INSERT INTO operations.condition_participants
        SELECT * FROM software_participants_next
        ON CONFLICT DO NOTHING
        """
    )
    cur.execute(
        """
        INSERT INTO operations.condition_assessments (
            tenant_id, row_kind, finding_id, participant_kind, participant_id,
            participant_role, condition_identity, policy_version, policy_digest, coverage,
            response, reevaluation_key, currentness, assessed_at)
        SELECT tenant_id, row_kind, finding_id, participant_kind, participant_id,
               participant_role, condition_identity, policy_version, policy_digest, coverage,
               response, reevaluation_key, currentness, assessed_at
          FROM software_assessments_next
        ON CONFLICT (tenant_id, row_kind, finding_id, participant_kind, participant_id,
                     participant_role) DO UPDATE SET
            condition_identity = EXCLUDED.condition_identity,
            policy_version = EXCLUDED.policy_version,
            policy_digest = EXCLUDED.policy_digest,
            coverage = EXCLUDED.coverage, response = EXCLUDED.response,
            reevaluation_key = EXCLUDED.reevaluation_key,
            currentness = EXCLUDED.currentness, assessed_at = EXCLUDED.assessed_at
        """
    )
    return len(assessments)


# ── Change feed ────────────────────────────────────────────────────────
#
# ``operations.software_reclassification_targets`` says which titles changed:
# the inventory apply records titles with new, changed, removed or relinked
# installations; vulnerability matching records titles and versions whose
# matches changed. A producer that cannot name titles (threat feeds, catalog
# projections) records the whole-fleet marker. The routine findings run
# reconciles just the named titles; the daily full run and every decision run
# cover everything and clear whatever is pending.

WHOLE_FLEET_KEY = "all"

PENDING_TARGETS_SQL = """
SELECT target.id, target.target_key, lower(target.canonical_name), target.software_version_id
  FROM operations.software_reclassification_targets target
 WHERE target.tenant_id = %(tid)s AND target.consumed_at IS NULL
"""

VERSION_TITLES_SQL = """
SELECT DISTINCT lower(installation.canonical_name)
  FROM operations.software_installations_current installation
 WHERE installation.tenant_id = %(tid)s
   AND installation.software_version_id = ANY(%(versions)s)
"""

CONSUME_TARGETS_SQL = """
UPDATE operations.software_reclassification_targets
   SET consumed_at = now()
 WHERE tenant_id = %(tid)s AND id = ANY(%(ids)s::uuid[]) AND consumed_at IS NULL
"""

RECORD_WHOLE_FLEET_SQL = """
INSERT INTO operations.software_reclassification_targets
    (tenant_id, target_key, canonical_name, source)
VALUES (%(tid)s, 'all', '*', %(source)s)
ON CONFLICT (tenant_id, target_key, source) WHERE consumed_at IS NULL DO NOTHING
"""


def scope_from_targets(
    targets: Iterable[tuple], version_titles: Iterable[str] = ()
) -> list[str] | None:
    """Title keys to reconcile, or None for the whole fleet. Pure.

    No pending target means the run was not asked for specific titles (a
    manual run, a schedule, a recovery), so it covers the fleet.
    """
    targets = list(targets)
    if not targets or any(row[1] == WHOLE_FLEET_KEY for row in targets):
        return None
    titles = {row[2] for row in targets if row[2] and row[2] != "*"}
    titles.update(title for title in version_titles if title)
    return sorted(titles)


def pending_scope(tenant_id: int, *, whole_fleet: bool) -> tuple[list[str], list[str] | None]:
    """(target ids this run will consume, title scope or None for the fleet)."""
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
        cur.execute(PENDING_TARGETS_SQL, {"tid": tenant_id})
        targets = cur.fetchall()
        ids = [str(row[0]) for row in targets]
        if whole_fleet:
            return ids, None
        versions = [row[3] for row in targets if row[3] is not None]
        version_titles: list[str] = []
        if versions and not any(row[1] == WHOLE_FLEET_KEY for row in targets):
            cur.execute(VERSION_TITLES_SQL, {"tid": tenant_id, "versions": versions})
            version_titles = [row[0] for row in cur.fetchall()]
    return ids, scope_from_targets(targets, version_titles)


def consume_targets(tenant_id: int, ids: list[str]) -> None:
    if not ids:
        return
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
        cur.execute(CONSUME_TARGETS_SQL, {"tid": tenant_id, "ids": ids})


def record_whole_fleet(cur: Any, tenant_id: int, source: str) -> None:
    """Ask the next findings run to cover the whole fleet (``source`` names why)."""
    cur.execute(RECORD_WHOLE_FLEET_SQL, {"tid": tenant_id, "source": source[:80]})


# ── Entry point ────────────────────────────────────────────────────────


def _record_run(tenant_id: int, started_at: datetime, report: RunReport | None,
                error: str | None) -> None:
    """Keep the classifier's run-log contract (catch-up scheduler, Data pages)."""
    rows = 0 if report is None else (
        sum(report.opened.values()) + sum(report.refreshed.values())
        + sum(report.resolved.values())
    )
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
            cur.execute(
                """
                INSERT INTO operations.run_log
                    (id, tenant_id, kind, subject_ref, started_at, ended_at, ok, rows, error)
                VALUES (gen_random_uuid(), %s, 'software_classifier',
                        jsonb_build_object('mode', %s::text), %s, now(), %s, %s, %s)
                """,
                (tenant_id, "reconcile", started_at, error is None, rows, error or ""),
            )
    except Exception:
        log.exception("software_reconcile: run_log write failed")


def run(
    tenant_id: int = 1,
    *,
    progress: Callable[[str, str], None] | None = None,
    count: Callable[[int, int | None, str], None] | None = None,
    titles: list[str] | None = None,
) -> RunReport:
    """Rebuild readiness, reconcile every software finding type, write assessments.

    ``titles`` limits the run to those title keys (lower-cased canonical names):
    their evidence is loaded, their findings reconciled and re-assessed, and
    every other finding is left as it is. None runs the whole fleet.
    ``count`` receives (finding types reconciled, types to reconcile, unit).
    """
    started_at = datetime.now(timezone.utc)
    try:
        report = _run(tenant_id, progress, count, titles)
    except Exception as exc:
        _record_run(tenant_id, started_at, None, str(exc)[:2000])
        raise
    _record_run(tenant_id, started_at, report, None)
    return report


def _run(
    tenant_id: int,
    progress: Callable[[str, str], None] | None,
    count: Callable[[int, int | None, str], None] | None = None,
    titles: list[str] | None = None,
) -> RunReport:
    def stage(name: str, detail: str) -> None:
        log.info("software_reconcile: %s - %s", name, detail)
        if progress is not None:
            progress(name, detail)

    now = datetime.now(timezone.utc)
    report = RunReport(scope_titles=None if titles is None else len(titles))
    stage("Assessing device readiness", "One decision per device and software type.")
    software_readiness.refresh(tenant_id, now=now)

    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
        stage("Loading software evidence", "Titles, versions, intelligence and rules.")
        ctx = load_context(cur, tenant_id, now, titles)
        profile = load_active_profile(cur)
    report.labels = {
        name: str(item.get("label") or name) for name, item in profile.definitions.items()
    }
    stage("Computing desired findings", f"{len(ctx.titles)} titles, {len(ctx.versions)} versions.")
    desired = compute_desired(ctx, report)

    # The types this module owns. Capability review candidates and the disabled
    # multi-AV type are produced elsewhere or not at all, so they are never
    # reconciled here: an empty desired set would resolve them.
    owned = {
        "suspicious_name", "known_malicious_hint", "rare_recent", "whitelist_suggestion",
        "vulnerable_software", "eol_runtime", "install_path_suspicious",
        "rejected_software_installed",
    }
    if settings.CAPABILITY_ENFORCEMENT_ENABLED:
        owned |= {"unauthorized_av", "unauthorized_rmm", "unauthorized_remote_access"}
    reconciled: list[int] = []
    to_reconcile = [
        name for name in sorted(owned & ctx.types.keys()) if name not in report.disabled
    ]
    for done, type_name in enumerate(to_reconcile):
        if count is not None:
            count(done, len(to_reconcile), "finding types")
        finding_type = ctx.types[type_name]
        stage("Reconciling findings", report.labels.get(type_name, type_name.replace("_", " ")))
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
            reconcile_type(cur, ctx, finding_type, desired.get(type_name, []), report, titles)
        reconciled.append(finding_type.id)
    if count is not None:
        count(len(to_reconcile), len(to_reconcile), "finding types")

    stage("Recording condition assessments", f"{len(reconciled)} finding types.")
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
        written = write_assessments(cur, ctx, reconciled, profile, titles)
    log.info("software_reconcile: %s assessments=%d", report.as_result(), written)
    return report
