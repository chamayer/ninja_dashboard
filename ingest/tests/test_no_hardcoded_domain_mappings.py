"""Ratchet: no new domain mappings in code.

Per ADR-0012 §6, any rule mapping one domain value to another is
operator-maintainable data, not a constant. A hardcoded mapping cannot be
corrected without a deploy, is invisible to the operator it affects, and
drifts from its data-driven siblings — `os_name -> os_family` is hardcoded in
`ingest/normalize.py` and again in SQL, while `os_family -> os_group` is a
table.

This is a ratchet, not a cleanup: every known offender is listed below with
its migration status. The test fails when a module-level collection of domain
strings appears that is not on the list, which is what a new hardcoded mapping
looks like. Removing an entry as it moves to data is the intended direction;
adding one requires justifying it here in review.

Exempt by design (ADR-0012 §6): function dispatch, normalisation regexes,
endpoint/timeout config, and documented fail-closed bootstrap fallbacks.
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
SCANNED = (REPO / "ingest", REPO / "operations" / "apps")

# name -> why it is allowed to exist today.
# Entries marked MIGRATE are ADR-0012 violations awaiting a data table; they
# are listed so the ratchet holds while they are worked through, not to bless
# them.
KNOWN: dict[str, str] = {
    "ACTIVE_FINDING_STATUSES": "BASELINE 2026-08-05 - not individually reviewed",
    "AV_EXEMPT_VALUES": "EXEMPT UI/dashboard definition",
    "COMMAND_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "COMPLIANCE_MISSING_STATES": "BASELINE 2026-08-05 - not individually reviewed",
    "DASHBOARD_NAMES": "EXEMPT UI/dashboard definition",
    "DEFAULTS": "BASELINE 2026-08-05 - not individually reviewed",
    "DETAIL_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "DEVICE_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "DEVICE_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "DEVICE_TAGS": "EXEMPT UI/dashboard definition",
    "DEVICE_TIMELINE_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "DEVICE_TIMELINE_TAGS": "EXEMPT UI/dashboard definition",
    "DEVICE_TYPE_VALUES": "EXEMPT UI/dashboard definition",
    "DOMAIN_BY_CATEGORY": "BASELINE 2026-08-05 - not individually reviewed",
    "DOMAIN_LABEL_BY_CATEGORY": "BASELINE 2026-08-05 - not individually reviewed",
    "FINDING_TYPE_VALUES": "EXEMPT UI/dashboard definition",
    "ISSUE_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "KNOWN": "BASELINE 2026-08-05 - not individually reviewed",
    "_PUBLISHER_DECISIONS": "EXEMPT decoder for the legacy decisions CSV format, not a domain mapping - the file format is fixed and dead (ADR-0015 step 1)",
    "_TITLE_DECISIONS": "EXEMPT decoder for the legacy decisions CSV format, not a domain mapping - the file format is fixed and dead (ADR-0015 step 1)",
    "NAV_DISPLAY_NAMES": "EXEMPT UI/dashboard definition",
    "NAV_LABELS": "EXEMPT UI/dashboard definition",
    "NINJA_MAP": "BASELINE 2026-08-05 - not individually reviewed",
    "ORG_OVERVIEW_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "OS_FAMILY_VALUES": "EXEMPT UI/dashboard definition",
    "OVERVIEW_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "PATCH_ACTIVITY_COLORS": "EXEMPT UI/dashboard definition",
    "PATCH_STATE_COLORS": "EXEMPT UI/dashboard definition",
    "PCOV_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "PLATFORM_VALUES": "EXEMPT UI/dashboard definition",
    "POLICY_CATEGORY_CHOICES": "BASELINE 2026-08-05 - not individually reviewed",
    "SERIAL_QUALITY_VALUES": "EXEMPT UI/dashboard definition",
    "SEVERITY_RANK": "BASELINE 2026-08-05 - not individually reviewed",
    "SEVERITY_VALUES": "EXEMPT UI/dashboard definition",
    "SOFTWARE_ACTIVITY_TYPES": "MIGRATE activity code -> triggers inventory rescan",
    "STATE_LABELS": "EXEMPT UI/dashboard definition",
    "STATE_PRIORITY": "BASELINE 2026-08-05 - not individually reviewed",
    "STATE_VALUES": "EXEMPT UI/dashboard definition",
    "TENANT_SCOPE_EXEMPT_PREFIXES": "BASELINE 2026-08-05 - not individually reviewed",
    "TRENDS_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "UTILITY_CARDS": "BASELINE 2026-08-05 - not individually reviewed",
    "VOLATILE_FIELDS": "MIGRATE defines which fields skip re-projection - drives the last_user lag",
    "_BUILTIN_NODE_CLASS_PATTERNS": (
        "EXEMPT bootstrap fallback for operations.node_class_mappings (0119); "
        "load_node_class_mappings() overrides it once per run, and it stays in "
        "effect if that query fails so the taxonomy never goes empty"
    ),
    "_ALERTS_FILTER_TAGS": "EXEMPT UI/dashboard definition",
    "_BACKGROUND_QUEUES": "BASELINE 2026-08-05 - not individually reviewed",
    "_BOOL_OPTIONS": "EXEMPT UI/dashboard definition",
    "_BOOTSTRAP_FALLBACK": "BASELINE 2026-08-05 - not individually reviewed",
    "_BOOTSTRAP_KIND_ENTITY_TYPE": "MIGRATE source kind -> entity type",
    "_BUILTIN_ALIASES": "MIGRATE alias mapping; alias TABLES already exist for client/platform/publisher",
    "_CANONICAL_SLUG_MAP": "BASELINE 2026-08-05 - not individually reviewed",
    "_CARD_TITLE_OVERRIDES": "BASELINE 2026-08-05 - not individually reviewed",
    "_CLASSIFIER_DEFAULTS": "MIGRATE classifier defaults; belongs in config rows",
    "_CLIENT_DOMAIN_LABELS": "EXEMPT UI/dashboard definition",
    "_CMD_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_CMD_PARAM_MAPPINGS_FULL": "BASELINE 2026-08-05 - not individually reviewed",
    "_CMD_TAGS": "EXEMPT UI/dashboard definition",
    "_CONFIDENCE_RANK": "MIGRATE confidence ordering",
    "_CURRENT_COLUMNS": "EXEMPT schema shape",
    "_CURRENT_UPDATE_COLUMNS": "EXEMPT schema shape",
    "_CUSTOMERS_FILTER_TAGS": "EXEMPT UI/dashboard definition",
    "_DASHBOARD_DOMAIN_CATEGORIES": "BASELINE 2026-08-05 - not individually reviewed",
    "_DASHBOARD_LEGACY_NAMES": "EXEMPT UI/dashboard definition",
    "_DASHBOARD_PRIORITY_LABELS": "EXEMPT UI/dashboard definition",
    "_DASHBOARD_STATE_LABELS": "EXEMPT UI/dashboard definition",
    "_DASHBOARD_STATE_PRIORITY": "BASELINE 2026-08-05 - not individually reviewed",
    "_DAYS_TAG": "BASELINE 2026-08-05 - not individually reviewed",
    "_DEFAULT_CONFIG": "MIGRATE software finding defaults; belongs in config rows",
    "_DEVICES_FILTER_TAGS": "EXEMPT UI/dashboard definition",
    "_DRILLDOWN_ACTIVITY_CODES": "MIGRATE activity code -> shown on device drilldown",
    "_DRILLDOWN_FILTER_TAGS": "EXEMPT UI/dashboard definition",
    "_ENTITY_TYPE_BY_SCOPE": "MIGRATE custom-field scope -> entity type",
    "_EXCLUDED_LAYOUTS": "MIGRATE Hudu layout -> skip; belongs in layout -> entity_class table",
    "_EXEMPTION_LABELS": "EXEMPT UI/dashboard definition",
    "_FETCHERS": "BASELINE 2026-08-05 - not individually reviewed",
    "_FILTER_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_FILTER_TAGS": "EXEMPT UI/dashboard definition",
    "_INTEGRATED_VENDORS": "MIGRATE vendor -> first-party; drives relay provenance",
    "_ISSUE_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_ISSUE_TAGS": "EXEMPT UI/dashboard definition",
    "_ISSUE_TYPE_OPTIONS": "EXEMPT UI/dashboard definition",
    "_JOB_CATALOG": "BASELINE 2026-08-05 - not individually reviewed",
    "_JUNK_MACS": "MIGRATE placeholder MAC detection; operator-tunable",
    "_JUNK_SERIALS": "MIGRATE placeholder serial detection; operator-tunable",
    "_LABELS": "EXEMPT UI/dashboard definition",
    "_LIFECYCLE_DIRECT_MODES": "BASELINE 2026-08-05 - not individually reviewed",
    "_LIFECYCLE_FINDING_ACTIVE_STATUSES": "BASELINE 2026-08-05 - not individually reviewed",
    "_LIFECYCLE_NEGATIVE_POWER_STATES": "MIGRATE power-state vocabulary",
    "_LIFECYCLE_POSITIVE_POWER_STATES": "MIGRATE power-state vocabulary",
    "_LIFECYCLE_REPORTED_MODES": "BASELINE 2026-08-05 - not individually reviewed",
    "_LOOKUP_SOURCES": "BASELINE 2026-08-05 - not individually reviewed",
    "_NAMESPACES": "BASELINE 2026-08-05 - not individually reviewed",
    "_NINJA_DEVICE_MATERIAL_FIELDS": "MIGRATE material projection definition",
    "_NINJA_HEALTH_MATERIAL_FIELDS": "MIGRATE material projection definition",
    "_NODE_CLASS_OPTIONS": "EXEMPT UI/dashboard definition",
    "_ORG_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_ORG_PARAM_MAPPINGS_FULL": "BASELINE 2026-08-05 - not individually reviewed",
    "_ORG_TAGS": "EXEMPT UI/dashboard definition",
    "_OS_FAMILY_OPTIONS": "EXEMPT UI/dashboard definition",
    "_BUILTIN_OS_FAMILY_PATTERNS": "EXEMPT documented bootstrap fallback; authoritative table is operations.os_family_mappings (migration 0118)",
    "_OUTCOME_OPTIONS": "EXEMPT UI/dashboard definition",
    "_OVERALL_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_OVERALL_PARAM_MAPPINGS_FULL": "BASELINE 2026-08-05 - not individually reviewed",
    "_OVERALL_TAGS": "EXEMPT UI/dashboard definition",
    "_PATCHING_SCOPE_OPTIONS": "EXEMPT UI/dashboard definition",
    "_PATCHING_TYPES": "BASELINE 2026-08-05 - not individually reviewed",
    "_PATCH_SEVERITY_CHOICES": "BASELINE 2026-08-05 - not individually reviewed",
    "_PATCH_STATUS_CHOICES": "BASELINE 2026-08-05 - not individually reviewed",
    "_PCOV_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_PCOV_STATUS_OPTIONS": "EXEMPT UI/dashboard definition",
    "_PCOV_TAGS": "EXEMPT UI/dashboard definition",
    "_POLICY_DEFAULTS": "MIGRATE policy defaults; belongs in config rows",
    "_PREFIX_TEMPLATES": "BASELINE 2026-08-05 - not individually reviewed",
    "_QUEUE_COLUMNS": "EXEMPT schema shape",
    "_RAW_FIELD_CATEGORIES": "BASELINE 2026-08-05 - not individually reviewed",
    "_RETIRED_DASHBOARD_NAMES": "EXEMPT UI/dashboard definition",
    "_SCALAR_ALERT_RULES": "BASELINE 2026-08-05 - not individually reviewed",
    "_SCALAR_SUFFIX_RULES": "BASELINE 2026-08-05 - not individually reviewed",
    "_SEVERITY_OPTIONS": "EXEMPT UI/dashboard definition",
    "_SEVERITY_RANK": "MIGRATE severity ordering",
    "_SOURCES_FALLBACK": "BASELINE 2026-08-05 - not individually reviewed",
    "_STATUS_OPTIONS": "EXEMPT UI/dashboard definition",
    "_STOP_TOKENS": "BASELINE 2026-08-05 - not individually reviewed",
    "_TIMELINE_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_TRENDS_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_TRENDS_PARAM_MAPPINGS_FULL": "BASELINE 2026-08-05 - not individually reviewed",
    "_TRENDS_TAGS": "EXEMPT UI/dashboard definition",
    "_TYPE_MAP": "MIGRATE parity type mapping",
    "_UTIL_PARAM_MAPPINGS": "BASELINE 2026-08-05 - not individually reviewed",
    "_UTIL_TAGS": "EXEMPT UI/dashboard definition",
    "_VISIBLE_TRENDS_CARD_KEYS": "EXEMPT UI/dashboard definition",
}

_COLLECTION = (ast.Set, ast.Dict, ast.List, ast.Tuple)


def _string_payload(node: ast.AST) -> int:
    """Count string constants in a collection, descending one level.

    Descends because the two mappings this rule was written for both evaded a
    shallow scan: `_OS_FAMILY_PATTERNS` is a list of (needle, family) tuples,
    and `_EXCLUDED_LAYOUTS` is a single-element set.
    """
    if isinstance(node, ast.Dict):
        items = [k for k in node.keys if k is not None] + list(node.values)
    elif isinstance(node, _COLLECTION):
        items = list(node.elts)
    else:
        return 0
    total = 0
    for i in items:
        if isinstance(i, ast.Constant) and isinstance(i.value, str):
            total += 1
        elif isinstance(i, _COLLECTION):
            total += sum(
                1
                for j in (i.elts if not isinstance(i, ast.Dict) else i.values)
                if isinstance(j, ast.Constant) and isinstance(j.value, str)
            )
    return total


def _candidates() -> list[tuple[str, str]]:
    """Module-level UPPER_CASE names bound to collections of >=2 strings."""
    found: list[tuple[str, str]] = []
    for root in SCANNED:
        for path in root.rglob("*.py"):
            if any(q.startswith("test") for q in path.parts) or "migrations" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                # frozenset({...}) / set([...]) wrappers
                if isinstance(value, ast.Call) and value.args:
                    value = value.args[0]
                # Threshold 1, not 2: `_EXCLUDED_LAYOUTS = {"people"}` is a
                # single-element set and is a genuine domain rule.
                if value is None or _string_payload(value) < 1:
                    continue
                for t in targets:
                    if isinstance(t, ast.Name) and t.id.lstrip("_").isupper():
                        found.append((t.id, str(path.relative_to(REPO))))
    return found


def test_no_new_hardcoded_domain_mappings() -> None:
    unlisted = sorted({(n, p) for n, p in _candidates() if n not in KNOWN})
    assert not unlisted, (
        "New module-level domain mapping(s) found. ADR-0012 §6 requires domain "
        "mappings to live in operator-maintainable data.\n"
        + "\n".join(f"  {n}  ({p})" for n, p in unlisted)
        + "\n\nIf this is genuinely dispatch, a regex, config, or a documented "
        "fail-closed fallback, add it to KNOWN with an EXEMPT reason."
    )
