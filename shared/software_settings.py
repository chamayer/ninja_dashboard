"""Software classifier settings: one definition for ingest and Operations.

The settings live in ``operations.evaluator_config`` (``software_classifier``)
as a JSON object. This module owns the defaults, the admin-editable fields and
their validation, so the admin page shows the value the classifier actually
uses. Unknown stored keys are always preserved: saving the page merges into the
stored object instead of replacing it.

Rare and non-approved software split the undecided titles at one boundary,
``rare_max_devices`` (design D15). Recency is a severity signal, not part of the
definition (D16).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

SEVERITIES = ("info", "low", "medium", "high", "critical")


@dataclass(frozen=True)
class SettingField:
    key: str
    section: str
    label: str
    hint: str
    kind: str  # "int", "float", "bool" or "severity"
    default: Any
    minimum: float | None = None
    maximum: float | None = None


FIELDS: tuple[SettingField, ...] = (
    SettingField(
        "installation_evidence_max_age_hours", "Software evidence freshness",
        "Maximum evidence age (hours)",
        "After this age a software record stays in inventory but no longer drives "
        "an active device finding.",
        "int", 24, 1, 720,
    ),
    SettingField(
        "inventory_hold_shrink_percent", "Software inventory", "Hold when a list shrinks by (%)",
        "If a computer's software list from Ninja is this much shorter than its previous "
        "list, its removals wait for an administrator instead of being applied. "
        "Additions and changes still apply.",
        "int", 50, 10, 100,
    ),
    SettingField(
        "inventory_hold_min_programs", "Software inventory",
        "Only for computers with at least (programs)",
        "Small lists change proportionally more, so the hold applies only when the "
        "previous list had at least this many programs.",
        "int", 20, 1, 10000,
    ),
    SettingField(
        "rare_enabled", "Rare and non-approved software", "Rare software findings",
        "Raise a finding for undecided software on very few devices.",
        "bool", True,
    ),
    SettingField(
        "non_approved_enabled", "Rare and non-approved software",
        "Non-approved software findings",
        "Raise a finding for undecided software installed on more devices than the "
        "rare limit.",
        "bool", True,
    ),
    SettingField(
        "rare_max_devices", "Rare and non-approved software", "Rare limit (devices)",
        "Undecided software on this many devices or fewer is rare; above it, it is "
        "non-approved. Every undecided title is exactly one of the two.",
        "int", 2, 1, 100,
    ),
    SettingField(
        "recent_days", "Rare and non-approved software", "Recent window (days)",
        "Software first seen within this many days carries the recent signal, which "
        "raises severity. It does not decide whether a finding exists.",
        "int", 7, 1, 90,
    ),
    SettingField(
        "rare_recent_severity", "Rare and non-approved software",
        "Severity: rare and recent", "Rare software first seen recently.",
        "severity", "medium",
    ),
    SettingField(
        "rare_older_severity", "Rare and non-approved software",
        "Severity: rare and older", "Rare software seen for longer than the window.",
        "severity", "low",
    ),
    SettingField(
        "non_approved_recent_severity", "Rare and non-approved software",
        "Severity: non-approved and recent",
        "Non-approved software first seen recently.",
        "severity", "medium",
    ),
    SettingField(
        "non_approved_severity", "Rare and non-approved software",
        "Severity: non-approved", "Non-approved software seen for longer than the window.",
        "severity", "low",
    ),
    SettingField(
        "rejected_installed_enabled", "Rare and non-approved software",
        "Rejected software findings",
        "Raise a finding while a title or publisher an operator rejected is still installed.",
        "bool", True,
    ),
    SettingField(
        "rejected_installed_severity", "Rare and non-approved software",
        "Severity: rejected software installed",
        "A title an operator rejected is still installed.",
        "severity", "high",
    ),
    SettingField(
        "vulnerable_software_enabled", "Vulnerable software", "Vulnerable software findings",
        "Raise a finding for installed versions with an exploited or severe CVE.",
        "bool", True,
    ),
    SettingField(
        "vulnerable_software_cvss_cutoff", "Vulnerable software", "CVSS cutoff",
        "A matched CVE at or above this score is severe.",
        "float", 7.0, 0, 10,
    ),
    SettingField(
        "vulnerable_software_severity_kev", "Vulnerable software",
        "Severity: actively exploited", "Matched CVE is on the CISA KEV list.",
        "severity", "critical",
    ),
    SettingField(
        "vulnerable_software_severity_high", "Vulnerable software",
        "Severity: severe CVE", "Matched CVE meets the CVSS cutoff.",
        "severity", "high",
    ),
    SettingField(
        "known_malicious_hint_enabled", "Threat intelligence", "Threat-intelligence hints",
        "Raise a hint when a title or publisher accumulates threat-intelligence hits.",
        "bool", True,
    ),
    SettingField(
        "known_malicious_hint_min_hits", "Threat intelligence", "Minimum hits",
        "Open threat-intelligence hits needed before a hint is raised.",
        "int", 3, 1, 100,
    ),
    SettingField(
        "known_malicious_hint_severity", "Threat intelligence", "Severity",
        "Threat-intelligence hints are noisy; keep this modest.",
        "severity", "low",
    ),
    SettingField(
        "suspicious_name_enabled", "Finding switches", "Suspicious-name findings",
        "Off stops this type without touching its open findings.",
        "bool", True,
    ),
    SettingField(
        "install_path_enabled", "Finding switches", "Suspicious install-path findings",
        "Off stops this type without touching its open findings.",
        "bool", True,
    ),
    SettingField(
        "eol_runtime_enabled", "Finding switches", "End-of-life runtime findings",
        "Off stops this type without touching its open findings.",
        "bool", True,
    ),
    SettingField(
        "reconcile_max_close_percent", "Safety", "Close limit (% of a type per run)",
        "A run that would resolve more than this share of a type's open findings "
        "resolves none of them and reports it, until an administrator allows it.",
        "int", 50, 1, 100,
    ),
    SettingField(
        "reconcile_allow_large_close", "Safety", "Allow a large close once",
        "Lets the next runs exceed the close limit. Turn it off again afterwards.",
        "bool", False,
    ),
    SettingField(
        "suggestion_min_clients", "Suggestions", "Approve-publisher: minimum clients",
        "Suggest approving a publisher only when its software is used by at least "
        "this many clients and nothing concerning is known.",
        "int", 5, 1, 1000,
    ),
    SettingField(
        "suggestion_min_age_days", "Suggestions", "Approve-publisher: minimum age (days)",
        "Suggest approving a publisher only when its software was first seen at "
        "least this many days ago.",
        "int", 30, 0, 3650,
    ),
)

DEFAULTS = MappingProxyType({field.key: field.default for field in FIELDS})

# Keys written by the previous admin page and read by the previous classifier.
# A stored legacy value is honoured until the canonical key is saved, and the
# effective settings mirror canonical values back under the legacy names so
# the previous classifier keeps working until it is retired.
LEGACY_ALIASES = MappingProxyType(
    {
        "rare_recent_max_devices": "rare_max_devices",
        "rare_recent_max_age_days": "recent_days",
        "rare_recent_enabled": "rare_enabled",
        "whitelist_suggestion_enabled": "non_approved_enabled",
    }
)


def effective(stored: dict[str, Any] | None) -> dict[str, Any]:
    """Return every stored key plus every canonical setting resolved.

    Precedence for a canonical setting: its stored value, then a stored legacy
    alias, then the default. Unknown keys pass through untouched.
    """
    stored = dict(stored) if isinstance(stored, dict) else {}
    result = dict(stored)
    for field in FIELDS:
        if field.key in stored:
            result[field.key] = stored[field.key]
            continue
        legacy = next(
            (old for old, new in LEGACY_ALIASES.items() if new == field.key and old in stored),
            None,
        )
        result[field.key] = stored[legacy] if legacy else field.default
    for old, new in LEGACY_ALIASES.items():
        result[old] = result[new]
    return result


def parse_form(form: Any) -> dict[str, Any]:
    """Validate submitted admin values; out-of-range numbers are clamped."""
    values: dict[str, Any] = {}
    for field in FIELDS:
        raw = form.get(field.key)
        if field.kind == "bool":
            values[field.key] = raw == "on"
        elif field.kind == "severity":
            value = (raw or "").strip()
            values[field.key] = value if value in SEVERITIES else field.default
        else:
            caster = int if field.kind == "int" else float
            try:
                number = caster(raw)
            except (TypeError, ValueError):
                number = field.default
            if field.minimum is not None:
                number = max(caster(field.minimum), number)
            if field.maximum is not None:
                number = min(caster(field.maximum), number)
            values[field.key] = number
    return values


def merge(stored: dict[str, Any] | None, submitted: dict[str, Any]) -> dict[str, Any]:
    """Merge validated values into the stored object without dropping keys."""
    merged = dict(stored) if isinstance(stored, dict) else {}
    merged.update(submitted)
    return merged


def sections() -> list[tuple[str, list[SettingField]]]:
    """Fields grouped by section, in definition order."""
    grouped: dict[str, list[SettingField]] = {}
    for field in FIELDS:
        grouped.setdefault(field.section, []).append(field)
    return list(grouped.items())
