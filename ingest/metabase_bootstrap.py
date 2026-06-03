"""Metabase dashboard bootstrap.

Provisions the "Ninja — Overview" dashboard in Metabase via its REST
API. Idempotent — re-running updates existing cards / dashboard
rather than creating duplicates. Iterate on SQL by editing
OVERVIEW_CARDS below and re-running.

Prerequisites (one-time, in the Metabase UI):
  1. Complete the first-run wizard — create the admin user.
  2. Add the Postgres data source. Display name MUST match --db-name
     (default "Ninja"). Host: postgres, Port: 5432, DB: ninja, user:
     ninja, password from the host .env.

Then from the host. Three ways to provide the password, in priority
order:

  # Interactive prompt (recommended — nothing in shell history)
  docker exec -it ninja-ingest python -m ingest.metabase_bootstrap \\
      --user you@example.com

  # From an environment variable
  METABASE_PASSWORD='...' docker exec -i \\
      -e METABASE_PASSWORD ninja-ingest \\
      python -m ingest.metabase_bootstrap --user you@example.com

  # From a file on the host (mounted into the container)
  docker exec -i ninja-ingest python -m ingest.metabase_bootstrap \\
      --user you@example.com \\
      --password-file /app/.env  # if you put MB_ADMIN_PASS=... there

Re-runs are safe — find cards/dashboards by name, update vs. create.

Layout uses Metabase's 24-column grid:
  Row 0 (y=0)  : 4 number cards, 6 cols each
  Row 1 (y=4)  : pie (12 cols) + worst-15 horizontal bar (12 cols)
  Row 2 (y=12) : all-orgs compliance table (full 24 cols)
  Row 3 (y=22) : devices-needing-reboot table (full 24 cols)
  Row 4 (y=30) : run-log table (full 24 cols)
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from ingest import db
from ingest.config import settings

log = logging.getLogger("metabase_bootstrap")

# ── Card specs ──────────────────────────────────────────────────────

OVERVIEW_CARDS: list[dict[str, Any]] = [
    {
        "key":        "active_devices",
        "name":       "Active Devices",
        "display":    "scalar",
        "row": 0, "col": 0, "size_x": 6, "size_y": 4,
        "query": """
SELECT COUNT(*) AS active_devices
FROM ninja_core.v_active_devices
""",
    },
    {
        "key":        "patches_ready",
        "name":       "Patches Ready to Install",
        "display":    "scalar",
        "row": 0, "col": 6, "size_x": 6, "size_y": 4,
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT COUNT(*) AS approved_queued
FROM current_state WHERE status = 'APPROVED'
""",
    },
    {
        "key":        "patches_manual",
        "name":       "Manual / Delayed",
        "display":    "scalar",
        "row": 0, "col": 12, "size_x": 6, "size_y": 4,
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT COUNT(*) AS patcheseeds_attention
FROM current_state WHERE status IN ('MANUAL', 'DELAYED')
""",
    },
    {
        "key":        "patches_failed",
        "name":       "Failed Installs",
        "display":    "scalar",
        "row": 0, "col": 18, "size_x": 6, "size_y": 4,
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT COUNT(*) AS failed
FROM current_state WHERE status = 'FAILED'
""",
    },
    {
        "key":     "ov_pcov_active",
        "name":    "Patching Active (last 7d)",
        "display": "scalar",
        "row": 4, "col": 0, "size_x": 8, "size_y": 4,
        "query": """
WITH dps AS (
    SELECT device_id, MAX(last_observed_at) AS last_seen_at
    FROM ninja_patches.patch_facts GROUP BY device_id
)
SELECT COUNT(*) AS active
FROM ninja_core.devices d
JOIN dps ON dps.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND dps.last_seen_at > NOW() - INTERVAL '7 days'
""",
    },
    {
        "key":     "ov_pcov_stale",
        "name":    "Patching Stale (>7d)",
        "display": "scalar",
        "row": 4, "col": 8, "size_x": 8, "size_y": 4,
        "query": """
WITH dps AS (
    SELECT device_id, MAX(last_observed_at) AS last_seen_at
    FROM ninja_patches.patch_facts GROUP BY device_id
)
SELECT COUNT(*) AS stale
FROM ninja_core.devices d
JOIN dps ON dps.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND dps.last_seen_at <= NOW() - INTERVAL '7 days'
""",
    },
    {
        "key":     "ov_pcov_none",
        "name":    "No Patch Data Ever",
        "display": "scalar",
        "row": 4, "col": 16, "size_x": 8, "size_y": 4,
        "query": """
SELECT COUNT(*) AS no_data
FROM ninja_core.devices d
LEFT JOIN ninja_patches.patch_facts pf ON pf.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND pf.device_id IS NULL
""",
    },
    {
        "key":        "patch_state_donut",
        "name":       "Patch State Breakdown",
        "display":    "pie",
        "row": 8, "col": 0, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "pie.dimension":       "status",
            "pie.metric":          "patches",
            # 0 = show every slice; default 2.5 buckets small ones into "Other"
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        # Click a status slice → open Detail filtered to that status.
        "click_behavior": {
            "target": DASH_DETAIL,
            "params": {"p_status": "status"},
        },
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT status, COUNT(*) AS patches
FROM current_state
GROUP BY status
ORDER BY n DESC
""",
    },
    {
        "key":        "compliance_worst",
        "name":       "Worst-Compliant Orgs (bottom 15)",
        "display":    "row",
        "row": 8, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["organization"],
            "graph.metrics":    ["pct_installed"],
        },
        # Click an org bar → open Detail filtered to that org.
        "click_behavior": {
            "target": DASH_DETAIL,
            "params": {"p_org": "organization"},
        },
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT
    o.name AS organization,
    ROUND(
      COUNT(*) FILTER (WHERE cs.status = 'INSTALLED') * 100.0
      / NULLIF(COUNT(*), 0),
      1
    ) AS pct_installed,
    COUNT(*) AS total_patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
GROUP BY o.name
HAVING COUNT(*) >= 50
ORDER BY pct_installed ASC
LIMIT 15
""",
    },
    {
        "key":        "compliance_all",
        "name":       "All Orgs Compliance",
        "display":    "table",
        "row": 16, "col": 0, "size_x": 24, "size_y": 10,
        "column_click_behaviors": {
            "organization": {
                "target": DASH_DETAIL,
                "params": {"p_org": "organization"},
            },
        },
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT
    o.name AS organization,
    ROUND(
      COUNT(*) FILTER (WHERE cs.status = 'INSTALLED') * 100.0
      / NULLIF(COUNT(*), 0),
      1
    ) AS pct_installed,
    COUNT(*) FILTER (WHERE cs.status = 'INSTALLED')                          AS installed,
    COUNT(*) FILTER (WHERE cs.status IN ('APPROVED','MANUAL','DELAYED'))     AS queued,
    COUNT(*) FILTER (WHERE cs.status = 'FAILED')                             AS failed,
    COUNT(*) FILTER (WHERE cs.status = 'REJECTED')                           AS rejected,
    COUNT(*)                                                                 AS total_patches,
    COUNT(DISTINCT cs.device_id)                                             AS devices
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
GROUP BY o.name
HAVING COUNT(*) >= 10
ORDER BY pct_installed ASC, total_patches DESC
""",
    },
    {
        "key":        "needs_reboot",
        "name":       "Devices Needing Reboot",
        "display":    "table",
        "row": 26, "col": 0, "size_x": 24, "size_y": 8,
        "column_click_behaviors": {
            "system_name": {
                "target": DASH_DRILLDOWN,
                "params": {"p_device": "system_name"},
            },
            "organization": {
                "target": DASH_DETAIL,
                "params": {"p_org": "organization"},
            },
        },
        "query": """
SELECT
    d.system_name,
    o.name AS organization,
    d.node_class,
    d.last_contact,
    d.last_snapshot_at AS reported_at
FROM ninja_core.v_active_devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE d.needs_reboot = TRUE
ORDER BY d.last_contact DESC
""",
    },
    {
        "key":        "ingest_health",
        "name":       "Ingest Health (last 24h)",
        "display":    "table",
        "row": 34, "col": 0, "size_x": 24, "size_y": 8,
        "query": """
SELECT
    domain,
    status,
    started_at,
    duration_ms,
    COALESCE(rows_inserted, 0) AS inserted,
    COALESCE(rows_upserted, 0) AS upserted,
    LEFT(COALESCE(error_text, ''), 80) AS error
FROM ninja_core.run_log
WHERE started_at > NOW() - INTERVAL '24 hours'
ORDER BY started_at DESC, run_id DESC
""",
    },
]

COLLECTION_NAME = "Ninja"

# Dashboard names — referenced by click_behavior specs for
# cross-dashboard drill-through. Keep these as constants so a rename
# doesn't break drill links silently.
DASH_OVERVIEW    = "Ninja — Overview"
DASH_DETAIL      = "Ninja — Patch Detail (Filterable)"
DASH_DRILLDOWN   = "Ninja — Device Drilldown"
DASH_PCOV        = "Ninja — Patch Coverage"


# ── Click behavior infrastructure ───────────────────────────────────
#
# Cards declare click_behavior in a friendly form; the second pass of
# run_bootstrap resolves dashboard names to IDs and writes the actual
# Metabase JSON into visualization_settings.
#
# Card spec gains:
#   "click_behavior": {           # whole-card (charts)
#       "target": "self" OR "<dashboard name>",
#       "params": {<dashboard_param_id>: <source_column_name>},
#   }
#   "column_click_behaviors": {   # per-column (tables)
#       "<column>": { "target": ..., "params": {...} },
#   }
#
# target="self" → crossfilter (set parameters on the current dashboard)
# target=<name> → link to that dashboard with parameters pre-set


def _build_param_mapping(params: dict[str, str]) -> dict[str, dict]:
    """Turn {param_id: source_column} into Metabase's parameterMapping JSON."""
    return {
        pid: {
            "id":     pid,
            "source": {"type": "column", "id": src, "name": src},
            "target": {"type": "parameter", "id": pid},
        }
        for pid, src in params.items()
    }


def _build_click_behavior_json(
    spec: dict, dash_id_by_name: dict[str, int],
) -> dict | None:
    target = spec.get("target")
    if target == "self":
        return {
            "type":             "crossfilter",
            "parameterMapping": _build_param_mapping(spec.get("params", {})),
        }
    target_id = dash_id_by_name.get(target)
    if target_id is None:
        log.warning("Click behavior: unknown target dashboard %r", target)
        return None
    return {
        "type":             "link",
        "linkType":         "dashboard",
        "targetId":         target_id,
        "parameterMapping": _build_param_mapping(spec.get("params", {})),
    }


def _apply_click_behaviors(
    client: httpx.Client,
    dashboards: list[dict],
    card_ids_by_dash: dict[str, dict[str, int]],
    dash_id_by_name: dict[str, int],
) -> None:
    """Second pass: merge click_behavior into each card's
    visualization_settings now that dashboard IDs are resolved."""
    for dash_spec in dashboards:
        card_ids = card_ids_by_dash[dash_spec["name"]]
        for card_spec in dash_spec["cards"]:
            extra: dict[str, Any] = {}

            if "click_behavior" in card_spec:
                cb = _build_click_behavior_json(card_spec["click_behavior"], dash_id_by_name)
                if cb:
                    extra["click_behavior"] = cb

            if "column_click_behaviors" in card_spec:
                column_settings: dict[str, dict] = {}
                for col, ccb in card_spec["column_click_behaviors"].items():
                    cb = _build_click_behavior_json(ccb, dash_id_by_name)
                    if cb:
                        # Metabase keys column_settings by JSON-encoded
                        # ["name", "<col>"] arrays.
                        key = f'["name","{col}"]'
                        column_settings[key] = {"click_behavior": cb}
                if column_settings:
                    extra["column_settings"] = column_settings

            if not extra:
                continue

            card_id = card_ids[card_spec["key"]]
            # Fetch current viz_settings so we don't clobber chart config.
            r = client.get(f"/api/card/{card_id}")
            r.raise_for_status()
            current = r.json().get("visualization_settings") or {}
            current.update(extra)
            r = client.put(
                f"/api/card/{card_id}",
                json={"visualization_settings": current},
            )
            r.raise_for_status()
            log.info("Click behaviors applied to: %s", card_spec["name"])


# ── Filterable Detail dashboard ─────────────────────────────────────
#
# Dashboard-level filters wire to card template tags via parameter
# mappings. The shape we use here:
#   - Card SQL has [[AND col = {{tag}}]] optional clauses
#   - Card.dataset_query.native["template-tags"] declares each tag
#   - Dashboard.parameters declares each filter (UI widget)
#   - Each dashcard.parameter_mappings ties dashboard param -> card tag

PARAM_ORG     = "p_org"
PARAM_STATUS  = "p_status"
PARAM_CLASS   = "p_class"
PARAM_SEV     = "p_severity"
PARAM_OS      = "p_os"
PARAM_KB      = "p_kb"
PARAM_DAYS    = "p_days"

# Static dropdown options for known small enums. Dynamic ones (orgs, OS
# names) are populated from the DB in build_detail_parameters().
_STATUS_OPTIONS = [
    "INSTALLED", "FAILED", "APPROVED", "PENDING", "REJECTED", "DELAYED", "MANUAL",
]
_NODE_CLASS_OPTIONS = [
    "WINDOWS_WORKSTATION", "WINDOWS_SERVER",
    "MAC", "MAC_SERVER",
    "LINUX_WORKSTATION", "LINUX_SERVER",
    "NMS_SWITCH", "NMS_ROUTER", "NMS_FIREWALL", "NMS_PRINTER", "NMS_OTHER",
    "VMWARE_VM_HOST", "VMWARE_VM_GUEST", "HYPERV_VMM_HOST", "HYPERV_VMM_GUEST",
]
_SEVERITY_OPTIONS = ["CRITICAL", "IMPORTANT", "OPTIONAL", "MODERATE", "LOW", "NONE"]


def _param_dropdown(
    pid: str, name: str, slug: str, values: list[str],
    default: Any = None,
) -> dict:
    """Build a Metabase dashboard parameter with a static-list dropdown."""
    p = {
        "id":                  pid,
        "name":                name,
        "slug":                slug,
        "type":                "category",
        "values_query_type":   "list",
        "values_source_type":  "static-list",
        "values_source_config": {"values": [[v] for v in values]},
    }
    if default is not None:
        p["default"] = default
    return p


def _param_text(pid: str, name: str, slug: str) -> dict:
    """Build a free-text dashboard parameter (no dropdown)."""
    return {
        "id":   pid,
        "name": name,
        "slug": slug,
        "type": "category",
    }


def build_detail_parameters(org_names: list[str], os_names: list[str]) -> list[dict]:
    """Construct the dashboard's parameter widgets. Dropdown values for
    Org and OS are populated from live data; Status/NodeClass/Severity
    use built-in enums; KB is a free-text search.

    Node Class defaults to WINDOWS_WORKSTATION so the MSP workflow
    "patch workstations across all clients first" is the default view.
    Operator picks WINDOWS_SERVER etc. from the dropdown when ready."""
    return [
        _param_dropdown(PARAM_ORG,    "Organization", "org",        org_names),
        _param_dropdown(PARAM_STATUS, "Status",       "status",     _STATUS_OPTIONS),
        _param_dropdown(PARAM_CLASS,  "Node Class",   "node_class", _NODE_CLASS_OPTIONS,
                        default="WINDOWS_WORKSTATION"),
        _param_dropdown(PARAM_SEV,    "Severity",     "severity",   _SEVERITY_OPTIONS),
        _param_dropdown(PARAM_OS,     "OS Name",      "os",         os_names),
        _param_text(    PARAM_KB,     "KB Number",    "kb"),
        _param_number(  PARAM_DAYS,   "Timeline window (days)", "days", 90),
    ]


# Each filtered card declares the same template tags + maps the dashboard
# parameters onto them.
_FILTER_TAGS = {
    "org":        {"id": "tt_org",        "name": "org",        "display-name": "Organization", "type": "text"},
    "status":     {"id": "tt_status",     "name": "status",     "display-name": "Status",       "type": "text"},
    "node_class": {"id": "tt_node_class", "name": "node_class", "display-name": "Node Class",   "type": "text"},
    "severity":   {"id": "tt_severity",   "name": "severity",   "display-name": "Severity",     "type": "text"},
    "os":         {"id": "tt_os",         "name": "os",         "display-name": "OS Name",      "type": "text"},
    "kb":         {"id": "tt_kb",         "name": "kb",         "display-name": "KB Number",    "type": "text"},
}

# Timeline-only template tag (only the install-timeline card maps the
# days parameter; the other Detail cards don't care about a window).
_DAYS_TAG = {
    "days": {
        "id": "tt_days", "name": "days",
        "display-name": "Timeline window (days)",
        "type": "number", "default": "90", "required": True,
    },
}

_FILTER_PARAM_MAPPINGS = {
    PARAM_ORG:    ["variable", ["template-tag", "org"]],
    PARAM_STATUS: ["variable", ["template-tag", "status"]],
    PARAM_CLASS:  ["variable", ["template-tag", "node_class"]],
    PARAM_SEV:    ["variable", ["template-tag", "severity"]],
    PARAM_OS:     ["variable", ["template-tag", "os"]],
    PARAM_KB:     ["variable", ["template-tag", "kb"]],
}

_TIMELINE_PARAM_MAPPINGS = {
    **_FILTER_PARAM_MAPPINGS,
    PARAM_DAYS: ["variable", ["template-tag", "days"]],
}

# Reused SQL fragments. Filter predicates include the new OS + KB filters.
_CTE_CURRENT_STATE = """
WITH current_state AS (
    SELECT DISTINCT ON (pf.device_id, pf.patch_uid)
        pf.device_id, pf.patch_uid, pf.status, pf.severity,
        pf.name AS patch_name, pf.kb_number, pf.installed_at,
        pf.last_observed_at
    FROM ninja_patches.patch_facts pf
    ORDER BY pf.device_id, pf.patch_uid, pf.last_observed_at DESC
)
"""
_FILTER_PREDICATES = """
  [[AND o.name = {{org}}]]
  [[AND cs.status = {{status}}]]
  [[AND d.node_class = {{node_class}}]]
  [[AND cs.severity = {{severity}}]]
  [[AND d.os_name = {{os}}]]
  [[AND cs.kb_number = {{kb}}]]
"""

DETAIL_CARDS = [
    {
        "key":            "detail_status_donut",
        "name":           "Patch Status (filtered)",
        "display":        "pie",
        "row": 0, "col": 0, "size_x": 8, "size_y": 6,
        "viz_settings":   {
            "pie.dimension":       "status",
            "pie.metric":          "patches",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": "self", "params": {"p_status": "status"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT cs.status, COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY cs.status
ORDER BY n DESC
""",
    },
    {
        "key":            "detail_severity_bar",
        "name":           "Severity Breakdown (filtered)",
        "display":        "bar",
        "row": 0, "col": 8, "size_x": 8, "size_y": 6,
        "viz_settings":   {"graph.dimensions": ["severity"], "graph.metrics": ["patches"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": "self", "params": {"p_severity": "severity"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT COALESCE(NULLIF(cs.severity, ''), 'NONE') AS severity, COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY 1
ORDER BY n DESC
""",
    },
    {
        "key":            "detail_top_devices",
        "name":           "Top 15 Devices (filtered)",
        "display":        "row",
        "row": 0, "col": 16, "size_x": 8, "size_y": 6,
        "viz_settings":   {"graph.dimensions": ["device"], "graph.metrics": ["patches"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    d.system_name AS device,
    COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY d.system_name
ORDER BY n DESC
LIMIT 15
""",
    },
    {
        "key":            "detail_top_kbs",
        "name":           "Top 20 KBs (filtered)",
        "display":        "row",
        "row": 6, "col": 0, "size_x": 12, "size_y": 8,
        "viz_settings":   {"graph.dimensions": ["kb_number"], "graph.metrics": ["patches"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": "self", "params": {"p_kb": "kb_number"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    COALESCE(NULLIF(cs.kb_number, ''), '(none)') AS kb_number,
    COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY kb_number
ORDER BY n DESC
LIMIT 20
""",
    },
    {
        "key":            "detail_installs_timeline",
        "name":           "Installs over time (filtered)",
        "display":        "line",
        "row": 6, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings":   {"graph.dimensions": ["day"], "graph.metrics": ["installs"]},
        "template_tags":  {**_FILTER_TAGS, **_DAYS_TAG},
        "param_mappings": _TIMELINE_PARAM_MAPPINGS,
        "query": f"""
SELECT
    DATE_TRUNC('day', pf.installed_at)::date AS day,
    COUNT(*) AS installs
FROM ninja_patches.patch_facts pf
JOIN ninja_core.v_active_devices d ON d.id = pf.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE pf.installed_at IS NOT NULL
  AND pf.installed_at > NOW() - (INTERVAL '1 day' * {{{{days}}}})
  AND d.approval_status = 'APPROVED'
  [[AND o.name = {{{{org}}}}]]
  [[AND pf.status = {{{{status}}}}]]
  [[AND d.node_class = {{{{node_class}}}}]]
  [[AND pf.severity = {{{{severity}}}}]]
  [[AND d.os_name = {{{{os}}}}]]
  [[AND pf.kb_number = {{{{kb}}}}]]
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":            "detail_all_devices",
        "name":           "All Devices by Patch Count (filtered)",
        "display":        "table",
        "row": 14, "col": 0, "size_x": 12, "size_y": 10,
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "organization": {"target": "self",         "params": {"p_org": "organization"}},
            "node_class":   {"target": "self",         "params": {"p_class": "node_class"}},
        },
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    d.system_name        AS device,
    o.name               AS organization,
    d.node_class,
    COUNT(*)             AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY d.system_name, o.name, d.node_class
ORDER BY patches DESC
""",
    },
    {
        "key":            "detail_all_kbs",
        "name":           "All KBs by Count (filtered)",
        "display":        "table",
        "row": 14, "col": 12, "size_x": 12, "size_y": 10,
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "kb_number": {"target": "self", "params": {"p_kb": "kb_number"}},
        },
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    COALESCE(NULLIF(cs.kb_number, ''), '(none)') AS kb_number,
    cs.patch_name,
    cs.severity,
    COUNT(DISTINCT cs.device_id) AS devices,
    COUNT(*)                     AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY 1, cs.patch_name, cs.severity
ORDER BY patches DESC
""",
    },
    {
        "key":            "detail_table",
        "name":           "Patch Detail Table (filtered)",
        "display":        "table",
        "row": 24, "col": 0, "size_x": 24, "size_y": 14,
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "organization": {"target": "self", "params": {"p_org":      "organization"}},
            "node_class":   {"target": "self", "params": {"p_class":    "node_class"}},
            "status":       {"target": "self", "params": {"p_status":   "status"}},
            "severity":     {"target": "self", "params": {"p_severity": "severity"}},
            "kb_number":    {"target": "self", "params": {"p_kb":       "kb_number"}},
        },
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    o.name           AS organization,
    d.system_name    AS device,
    d.node_class,
    cs.kb_number,
    cs.patch_name,
    cs.status,
    cs.severity,
    cs.installed_at,
    CASE WHEN cs.installed_at IS NULL THEN NULL
         ELSE ROUND(EXTRACT(EPOCH FROM (NOW() - cs.installed_at)) / 86400)
    END AS days_since_install,
    cs.last_observed_at
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
ORDER BY cs.last_observed_at DESC, cs.installed_at DESC NULLS LAST
LIMIT 1000
""",
    },
]


# ── Device Drilldown dashboard ──────────────────────────────────────
#
# Per-device deep dive. Filter is a free-text device name (matches
# system_name / display_name / dns_name case-insensitively, contains).
# Type a substring like "CL-35" or "DESKTOP-B1" to pull the device's
# full history.

PARAM_DEVICE      = "p_device"
PARAM_DEVICE_DAYS = "p_device_days"

DEVICE_TAGS = {
    "device": {"id": "tt_device", "name": "device", "display-name": "Device", "type": "text"},
}

DEVICE_TIMELINE_TAGS = {
    "device": {"id": "tt_device", "name": "device", "display-name": "Device", "type": "text"},
    "days": {
        "id": "tt_device_days", "name": "days",
        "display-name": "Timeline window (days)",
        "type": "number", "default": "180", "required": True,
    },
}

DEVICE_PARAM_MAPPINGS = {
    PARAM_DEVICE: ["variable", ["template-tag", "device"]],
}

DEVICE_TIMELINE_PARAM_MAPPINGS = {
    PARAM_DEVICE:      ["variable", ["template-tag", "device"]],
    PARAM_DEVICE_DAYS: ["variable", ["template-tag", "days"]],
}

_DEVICE_FILTER = "[[AND (d.system_name ILIKE '%' || {{device}} || '%' OR d.display_name ILIKE '%' || {{device}} || '%' OR d.dns_name ILIKE '%' || {{device}} || '%')]]"


def build_device_parameters() -> list[dict]:
    """Device search + timeline window."""
    return [
        _param_text(  PARAM_DEVICE,      "Device (name/substring)", "device"),
        _param_number(PARAM_DEVICE_DAYS, "Timeline window (days)",  "device_days", 180),
    ]


DEVICE_CARDS = [
    {
        "key":            "device_info",
        "name":           "Device(s) Matching Filter",
        "display":        "table",
        "row": 0, "col": 0, "size_x": 24, "size_y": 6,
        "template_tags":  DEVICE_TAGS,
        "param_mappings": DEVICE_PARAM_MAPPINGS,
        "query": f"""
WITH latest_snap AS (
    SELECT DISTINCT ON (device_id) *
    FROM ninja_core.device_snapshots
    ORDER BY device_id, snapshot_at DESC
)
SELECT
    d.id                   AS device_id,
    d.system_name,
    d.display_name,
    o.name                 AS organization,
    d.node_class,
    d.os_name,
    d.os_release_id,
    d.serial_number,
    d.manufacturer,
    d.model,
    ls.last_contact,
    ls.last_boot,
    ls.needs_reboot,
    ls.maintenance_status
FROM ninja_core.devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
LEFT JOIN latest_snap ls ON ls.device_id = d.id
WHERE d.approval_status = 'APPROVED'
{_DEVICE_FILTER}
ORDER BY d.system_name
LIMIT 100
""",
    },
    {
        "key":            "device_state_pie",
        "name":           "Patch State for Selected Device(s)",
        "display":        "pie",
        "row": 6, "col": 0, "size_x": 8, "size_y": 8,
        "viz_settings":   {
            "pie.dimension":       "status",
            "pie.metric":          "patches",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  DEVICE_TAGS,
        "param_mappings": DEVICE_PARAM_MAPPINGS,
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT cs.status, COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.devices d ON d.id = cs.device_id
WHERE d.approval_status = 'APPROVED'
{_DEVICE_FILTER}
GROUP BY cs.status
ORDER BY patches DESC
""",
    },
    {
        "key":            "device_install_timeline",
        "name":           "Installs Over Time (Selected Device(s))",
        "display":        "line",
        "row": 6, "col": 8, "size_x": 16, "size_y": 8,
        "viz_settings":   {"graph.dimensions": ["day"], "graph.metrics": ["installs"]},
        "template_tags":  DEVICE_TIMELINE_TAGS,
        "param_mappings": DEVICE_TIMELINE_PARAM_MAPPINGS,
        "query": f"""
SELECT
    DATE_TRUNC('day', pf.installed_at)::date AS day,
    COUNT(*) AS installs
FROM ninja_patches.patch_facts pf
JOIN ninja_core.devices d ON d.id = pf.device_id
WHERE pf.installed_at IS NOT NULL
  AND pf.installed_at > NOW() - (INTERVAL '1 day' * {{{{days}}}})
  AND d.approval_status = 'APPROVED'
  {_DEVICE_FILTER.replace('{{device}}', '{{{{device}}}}')}
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":            "device_patch_history",
        "name":           "Full Patch History for Selected Device(s)",
        "display":        "table",
        "row": 14, "col": 0, "size_x": 24, "size_y": 14,
        "template_tags":  DEVICE_TAGS,
        "param_mappings": DEVICE_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "kb_number": {"target": DASH_DETAIL, "params": {"p_kb": "kb_number"}},
        },
        "query": f"""
WITH all_observations AS (
    SELECT
        pf.device_id, pf.patch_uid, pf.status, pf.severity,
        pf.kb_number, pf.name AS patch_name, pf.installed_at,
        pf.first_observed_at, pf.last_observed_at
    FROM ninja_patches.patch_facts pf
)
SELECT
    d.system_name        AS device,
    ao.kb_number,
    ao.patch_name,
    ao.status,
    ao.severity,
    ao.installed_at,
    ao.first_observed_at AS first_seen_in_this_state,
    ao.last_observed_at  AS last_seen_in_this_state
FROM all_observations ao
JOIN ninja_core.devices d ON d.id = ao.device_id
WHERE d.approval_status = 'APPROVED'
{_DEVICE_FILTER}
ORDER BY
    d.system_name,
    ao.patch_uid,
    ao.last_observed_at DESC
LIMIT 5000
""",
    },
]


# ── Patch Coverage dashboard ────────────────────────────────────────
#
# Ninja's API doesn't return a "patch management enabled" flag on
# devices, so we infer status from observed patch_facts activity:
#   - active_patching  : MAX(last_observed_at) within last 7 days
#   - stale_patch_data : has rows but all older than 7 days
#   - no_patch_data    : no rows in patch_facts at all
# This catches devices the patch agent isn't reaching, regardless of
# whether the cause is config, agent failure, or decommissioning.

PARAM_PCOV_ORG    = "p_pcov_org"
PARAM_PCOV_CLASS  = "p_pcov_class"
PARAM_PCOV_OS     = "p_pcov_os"
PARAM_PCOV_STATUS = "p_pcov_status"
PARAM_PCOV_DAYS   = "p_pcov_days"

_PCOV_STATUS_OPTIONS = ["active_patching", "stale_patch_data", "no_patch_data"]


def _param_number(pid: str, name: str, slug: str, default: int) -> dict:
    """Numeric dashboard parameter with a default value."""
    return {
        "id":      pid,
        "name":    name,
        "slug":    slug,
        "type":    "number/=",
        "default": default,
    }


def build_pcov_parameters(org_names: list[str], os_names: list[str]) -> list[dict]:
    return [
        _param_dropdown(PARAM_PCOV_ORG,    "Organization",  "pcov_org",        org_names),
        _param_dropdown(PARAM_PCOV_CLASS,  "Node Class",    "pcov_node_class", _NODE_CLASS_OPTIONS,
                        default="WINDOWS_WORKSTATION"),
        _param_dropdown(PARAM_PCOV_OS,     "OS Name",       "pcov_os",         os_names),
        _param_dropdown(PARAM_PCOV_STATUS, "Patch Status",  "pcov_status",     _PCOV_STATUS_OPTIONS),
        _param_number(  PARAM_PCOV_DAYS,   "Stale threshold (days)", "pcov_days", 7),
    ]


_PCOV_TAGS = {
    "pcov_org":         {"id": "tt_pcov_org",    "name": "pcov_org",        "display-name": "Organization", "type": "text"},
    "pcov_node_class":  {"id": "tt_pcov_class",  "name": "pcov_node_class", "display-name": "Node Class",   "type": "text"},
    "pcov_os":          {"id": "tt_pcov_os",     "name": "pcov_os",         "display-name": "OS Name",      "type": "text"},
    "pcov_status":      {"id": "tt_pcov_status", "name": "pcov_status",     "display-name": "Patch Status", "type": "text"},
    "pcov_days":        {
        "id": "tt_pcov_days", "name": "pcov_days",
        "display-name": "Stale threshold (days)",
        "type": "number", "default": "7", "required": True,
    },
}

_PCOV_PARAM_MAPPINGS = {
    PARAM_PCOV_ORG:    ["variable", ["template-tag", "pcov_org"]],
    PARAM_PCOV_CLASS:  ["variable", ["template-tag", "pcov_node_class"]],
    PARAM_PCOV_OS:     ["variable", ["template-tag", "pcov_os"]],
    PARAM_PCOV_STATUS: ["variable", ["template-tag", "pcov_status"]],
    PARAM_PCOV_DAYS:   ["variable", ["template-tag", "pcov_days"]],
}

# Reused: classify every active device by its latest patch_facts signal.
# Threshold is configurable via the dashboard's "Stale threshold (days)"
# parameter; template tag default keeps queries valid even before the
# operator sets a value.
_PCOV_CTE = """
WITH device_patch_signal AS (
    SELECT device_id, MAX(last_observed_at) AS last_seen_at
    FROM ninja_patches.patch_facts
    GROUP BY device_id
),
classified AS (
    SELECT
        d.id              AS device_id,
        d.system_name,
        d.display_name,
        d.organization_id,
        d.node_class,
        d.os_name,
        dps.last_seen_at,
        CASE
            WHEN dps.last_seen_at IS NULL THEN 'no_patch_data'
            WHEN dps.last_seen_at < NOW() - (INTERVAL '1 day' * {{pcov_days}}) THEN 'stale_patch_data'
            ELSE 'active_patching'
        END AS patch_status
    FROM ninja_core.devices d
    LEFT JOIN device_patch_signal dps ON dps.device_id = d.id
    WHERE d.approval_status = 'APPROVED'
)
"""

_PCOV_FILTERS = """
  [[AND o.name = {{pcov_org}}]]
  [[AND c.node_class = {{pcov_node_class}}]]
  [[AND c.os_name = {{pcov_os}}]]
  [[AND c.patch_status = {{pcov_status}}]]
"""

PCOV_CARDS = [
    {
        "key":     "pcov_active",
        "name":    "Actively Patching",
        "display": "scalar",
        "row": 0, "col": 0, "size_x": 6, "size_y": 4,
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT COUNT(*) AS active
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE c.patch_status = 'active_patching'
{_PCOV_FILTERS}
""",
    },
    {
        "key":     "pcov_stale",
        "name":    "Stale Patch Data (no observation in 7d)",
        "display": "scalar",
        "row": 0, "col": 6, "size_x": 6, "size_y": 4,
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT COUNT(*) AS stale
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE c.patch_status = 'stale_patch_data'
{_PCOV_FILTERS}
""",
    },
    {
        "key":     "pcov_none",
        "name":    "No Patch Data Ever",
        "display": "scalar",
        "row": 0, "col": 12, "size_x": 6, "size_y": 4,
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT COUNT(*) AS no_data
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE c.patch_status = 'no_patch_data'
{_PCOV_FILTERS}
""",
    },
    {
        "key":     "pcov_total",
        "name":    "Total Approved Devices",
        "display": "scalar",
        "row": 0, "col": 18, "size_x": 6, "size_y": 4,
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT COUNT(*) AS devices
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
""",
    },
    {
        "key":     "pcov_status_pie",
        "name":    "Patch Coverage Breakdown (by status)",
        "display": "pie",
        "row": 4, "col": 0, "size_x": 8, "size_y": 8,
        "click_behavior": {"target": "self", "params": {"p_pcov_status": "patch_status"}},
        "viz_settings": {
            "pie.dimension":       "patch_status",
            "pie.metric":          "devices",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT c.patch_status, COUNT(*) AS devices
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY c.patch_status
ORDER BY devices DESC
""",
    },
    {
        "key":     "pcov_class_pie",
        "name":    "Coverage by Node Class",
        "display": "pie",
        "row": 4, "col": 8, "size_x": 8, "size_y": 8,
        "click_behavior": {"target": "self", "params": {"p_pcov_class": "node_class"}},
        "viz_settings": {
            "pie.dimension":       "node_class",
            "pie.metric":          "devices",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT c.node_class, COUNT(*) AS devices
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY c.node_class
ORDER BY devices DESC
""",
    },
    {
        "key":     "pcov_os_stacked",
        "name":    "Patch Coverage by OS (top 20)",
        "display": "bar",
        "row": 4, "col": 16, "size_x": 8, "size_y": 8,
        "click_behavior": {"target": "self", "params": {"p_pcov_os": "os_name"}},
        "viz_settings": {
            "graph.dimensions":      ["os_name"],
            "graph.metrics":         ["active", "stale", "no_data"],
            "stackable.stack_type":  "stacked",
            "graph.show_values":     False,
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT
    COALESCE(NULLIF(c.os_name, ''), '(unknown)') AS os_name,
    COUNT(*) FILTER (WHERE c.patch_status = 'active_patching')  AS active,
    COUNT(*) FILTER (WHERE c.patch_status = 'stale_patch_data') AS stale,
    COUNT(*) FILTER (WHERE c.patch_status = 'no_patch_data')    AS no_data
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY 1
ORDER BY (active + stale + no_data) DESC
LIMIT 20
""",
    },
    {
        "key":     "pcov_by_org",
        "name":    "Coverage by Organization",
        "display": "table",
        "row": 12, "col": 0, "size_x": 24, "size_y": 8,
        "column_click_behaviors": {
            "organization": {"target": "self", "params": {"p_pcov_org": "organization"}},
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT
    o.name AS organization,
    COUNT(*) FILTER (WHERE c.patch_status = 'active_patching')  AS active,
    COUNT(*) FILTER (WHERE c.patch_status = 'stale_patch_data') AS stale,
    COUNT(*) FILTER (WHERE c.patch_status = 'no_patch_data')    AS no_data,
    COUNT(*)                                                    AS total,
    ROUND(
        COUNT(*) FILTER (WHERE c.patch_status = 'active_patching') * 100.0
        / NULLIF(COUNT(*), 0), 1
    ) AS pct_active
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY o.name
ORDER BY pct_active ASC, total DESC
""",
    },
    {
        "key":     "pcov_all_devices",
        "name":    "All Devices with Patch Status",
        "display": "table",
        "row": 20, "col": 0, "size_x": 24, "size_y": 14,
        "column_click_behaviors": {
            "system_name":  {"target": DASH_DRILLDOWN, "params": {"p_device":      "system_name"}},
            "organization": {"target": "self",         "params": {"p_pcov_org":    "organization"}},
            "node_class":   {"target": "self",         "params": {"p_pcov_class":  "node_class"}},
            "os_name":      {"target": "self",         "params": {"p_pcov_os":     "os_name"}},
            "patch_status": {"target": "self",         "params": {"p_pcov_status": "patch_status"}},
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE},
latest_contact AS (
    SELECT DISTINCT ON (device_id) device_id, last_contact
    FROM ninja_core.device_snapshots
    ORDER BY device_id, snapshot_at DESC
)
SELECT
    c.device_id,
    c.system_name,
    o.name AS organization,
    c.node_class,
    c.os_name,
    c.patch_status,
    c.last_seen_at AS patch_last_seen,
    lc.last_contact,
    CASE WHEN c.last_seen_at IS NULL THEN NULL
         ELSE EXTRACT(DAY FROM (NOW() - c.last_seen_at))::int
    END AS days_since_patch_seen,
    CASE WHEN lc.last_contact IS NULL THEN NULL
         ELSE EXTRACT(DAY FROM (NOW() - lc.last_contact))::int
    END AS days_since_contact
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
LEFT JOIN latest_contact lc ON lc.device_id = c.device_id
WHERE 1=1
{_PCOV_FILTERS}
ORDER BY
    CASE c.patch_status
        WHEN 'no_patch_data' THEN 0
        WHEN 'stale_patch_data' THEN 1
        ELSE 2
    END,
    c.last_seen_at ASC NULLS FIRST,
    o.name, c.system_name
""",
    },
]


def build_dashboards(org_names: list[str], os_names: list[str]) -> list[dict]:
    """All dashboards this script provisions. Detail / Patch Coverage
    dropdowns are populated from the live data passed in."""
    return [
        {
            "name":       "Ninja — Overview",
            "parameters": [],
            "cards":      OVERVIEW_CARDS,
        },
        {
            "name":       "Ninja — Patch Detail (Filterable)",
            "parameters": build_detail_parameters(org_names, os_names),
            "cards":      DETAIL_CARDS,
        },
        {
            "name":       "Ninja — Device Drilldown",
            "parameters": build_device_parameters(),
            "cards":      DEVICE_CARDS,
        },
        {
            "name":       "Ninja — Patch Coverage",
            "parameters": build_pcov_parameters(org_names, os_names),
            "cards":      PCOV_CARDS,
        },
    ]


def _fetch_dropdown_sources() -> tuple[list[str], list[str]]:
    """Query Postgres for the current orgs and distinct OS names.
    Returns (org_names, os_names), each sorted alphabetically."""
    db.init(settings.postgres_dsn)
    with db.transaction() as cur:
        cur.execute("SELECT name FROM ninja_core.organizations ORDER BY name")
        org_names = [r[0] for r in cur.fetchall() if r[0]]
        cur.execute(
            "SELECT DISTINCT os_name FROM ninja_core.devices "
            "WHERE os_name IS NOT NULL AND os_name <> '' "
            "ORDER BY os_name"
        )
        os_names = [r[0] for r in cur.fetchall() if r[0]]
    log.info("Dropdown sources: %d orgs, %d OS names", len(org_names), len(os_names))
    return org_names, os_names


# ── HTTP helpers ────────────────────────────────────────────────────

def _authenticate(client: httpx.Client, user: str, password: str) -> None:
    log.info("Authenticating as %s", user)
    r = client.post("/api/session", json={"username": user, "password": password})
    r.raise_for_status()
    client.headers["X-Metabase-Session"] = r.json()["id"]


def _find_database(client: httpx.Client, name: str) -> int:
    r = client.get("/api/database")
    r.raise_for_status()
    payload = r.json()
    # Metabase wraps in {data: [...], total: N} on some versions; flat list on others.
    dbs = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    for db in dbs:
        if str(db.get("name", "")).lower() == name.lower():
            return int(db["id"])
    names = [db.get("name") for db in dbs]
    raise SystemExit(
        f"Database '{name}' not found in Metabase.\n"
        f"  Available: {names}\n"
        f"  Add it via Settings → Databases (host: postgres, db: ninja, user: ninja)."
    )


def _upsert_collection(client: httpx.Client, name: str) -> int:
    r = client.get("/api/collection")
    r.raise_for_status()
    for col in r.json():
        if col.get("name") == name and not col.get("archived", False):
            log.info("Using existing collection: %s (id=%s)", name, col["id"])
            return int(col["id"])
    r = client.post("/api/collection", json={"name": name, "color": "#509EE3"})
    r.raise_for_status()
    cid = int(r.json()["id"])
    log.info("Created collection: %s (id=%d)", name, cid)
    return cid


def _list_cards_in_collection(client: httpx.Client, collection_id: int) -> dict[str, dict]:
    """Return {card_name: card_dict} for cards in the collection."""
    r = client.get(f"/api/collection/{collection_id}/items", params={"models": "card"})
    r.raise_for_status()
    payload = r.json()
    items = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    return {c["name"]: c for c in items if c.get("model") == "card"}


def _upsert_card(
    client: httpx.Client, spec: dict, db_id: int, collection_id: int,
    existing_by_name: dict[str, dict],
) -> int:
    native: dict[str, Any] = {"query": spec["query"].strip()}
    if "template_tags" in spec:
        native["template-tags"] = spec["template_tags"]
    body = {
        "name":                   spec["name"],
        "display":                spec["display"],
        "visualization_settings": spec.get("viz_settings", {}),
        "collection_id":          collection_id,
        "dataset_query": {
            "type":     "native",
            "database": db_id,
            "native":   native,
        },
    }
    existing = existing_by_name.get(spec["name"])
    if existing:
        cid = int(existing["id"])
        r = client.put(f"/api/card/{cid}", json=body)
        r.raise_for_status()
        log.info("Updated card: %s (id=%d)", spec["name"], cid)
        return cid
    r = client.post("/api/card", json=body)
    r.raise_for_status()
    cid = int(r.json()["id"])
    log.info("Created card: %s (id=%d)", spec["name"], cid)
    return cid


def _upsert_dashboard(
    client: httpx.Client, name: str, collection_id: int,
    parameters: list[dict] | None = None,
) -> dict[str, Any]:
    r = client.get("/api/dashboard")
    r.raise_for_status()
    existing = None
    for d in r.json():
        if d.get("name") == name and d.get("collection_id") == collection_id:
            existing = d
            break

    if existing is None:
        r = client.post("/api/dashboard", json={
            "name": name, "collection_id": collection_id,
        })
        r.raise_for_status()
        dash = r.json()
        log.info("Created dashboard: %s (id=%d)", name, dash["id"])
    else:
        r = client.get(f"/api/dashboard/{existing['id']}")
        r.raise_for_status()
        dash = r.json()
        log.info("Using existing dashboard: %s (id=%s)", name, dash["id"])

    if parameters is not None:
        # Update parameters (dashboard-level filter widgets).
        r = client.put(
            f"/api/dashboard/{dash['id']}",
            json={"parameters": parameters},
        )
        r.raise_for_status()
        dash = r.json()
    return dash


def _set_dashboard_layout(
    client: httpx.Client, dashboard: dict, specs: list[dict],
    card_ids: dict[str, int],
) -> None:
    """Replace the dashboard's dashcards with our layout. Uses PUT
    /api/dashboard/:id with a full `dashcards` array — modern
    Metabase replaces dashcards atomically. Each dashcard's
    parameter_mappings wire dashboard filters into the card's
    template tags."""
    dashcards = []
    for i, spec in enumerate(specs):
        card_id = card_ids[spec["key"]]
        param_mappings = [
            {"parameter_id": pid, "card_id": card_id, "target": target}
            for pid, target in spec.get("param_mappings", {}).items()
        ]
        dashcards.append({
            "id":                     -(i + 1),  # negative = new dashcard
            "card_id":                card_id,
            "row":                    spec["row"],
            "col":                    spec["col"],
            "size_x":                 spec["size_x"],
            "size_y":                 spec["size_y"],
            "parameter_mappings":     param_mappings,
            "visualization_settings": {},
        })
    r = client.put(
        f"/api/dashboard/{dashboard['id']}",
        json={"dashcards": dashcards},
    )
    r.raise_for_status()
    log.info("Set dashboard layout: %d cards", len(dashcards))


# ── Entry point ─────────────────────────────────────────────────────

def _resolve_password(args: argparse.Namespace) -> str:
    """Priority: --password flag > --password-file > METABASE_PASSWORD env >
    interactive prompt. Last option is the recommended one."""
    if args.password:
        return args.password
    if args.password_file:
        text = Path(args.password_file).read_text(encoding="utf-8")
        # Allow plain "<password>" OR a .env-style "KEY=value" line where
        # KEY is configurable via --password-file-key (default MB_ADMIN_PASS).
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == args.password_file_key:
                    return v.strip().strip('"').strip("'")
            else:
                return line
        raise SystemExit(
            f"No password found in {args.password_file} "
            f"(looking for key {args.password_file_key}=... or first non-comment line)"
        )
    env_pw = os.environ.get("METABASE_PASSWORD")
    if env_pw:
        return env_pw
    if not sys.stdin.isatty():
        raise SystemExit(
            "No password provided. Use --password, --password-file, "
            "METABASE_PASSWORD env var, or run interactively for a prompt."
        )
    return getpass.getpass("Metabase password: ")


def run_bootstrap(
    url: str, user: str, password: str, db_name: str = "Ninja",
) -> list[str]:
    """Provision all dashboards in Metabase. Two passes:
      1. Create / update cards, dashboards, layouts.
      2. Once all dashboard IDs are known, apply click_behavior
         (cross-dashboard drill-through and crossfilter).
    Raises on auth / API errors."""
    org_names, os_names = _fetch_dropdown_sources()
    dashboards = build_dashboards(org_names, os_names)

    urls: list[str] = []
    dash_id_by_name: dict[str, int] = {}
    card_ids_by_dash: dict[str, dict[str, int]] = {}

    with httpx.Client(base_url=url, timeout=60) as client:
        _authenticate(client, user, password)
        db_id = _find_database(client, db_name)
        log.info("Using database: %s (id=%d)", db_name, db_id)

        col_id = _upsert_collection(client, COLLECTION_NAME)
        existing_cards = _list_cards_in_collection(client, col_id)

        # Pass 1 — cards, dashboards, layouts.
        for dash_spec in dashboards:
            log.info("── Provisioning dashboard: %s ──", dash_spec["name"])
            card_ids: dict[str, int] = {}
            for card_spec in dash_spec["cards"]:
                card_ids[card_spec["key"]] = _upsert_card(
                    client, card_spec, db_id, col_id, existing_cards,
                )
            dashboard = _upsert_dashboard(
                client, dash_spec["name"], col_id,
                parameters=dash_spec.get("parameters"),
            )
            _set_dashboard_layout(
                client, dashboard, dash_spec["cards"], card_ids,
            )
            dash_id_by_name[dash_spec["name"]] = int(dashboard["id"])
            card_ids_by_dash[dash_spec["name"]] = card_ids
            urls.append(f"{url}/dashboard/{dashboard['id']}  ({dash_spec['name']})")

        # Pass 2 — click behaviors (need dashboard IDs from pass 1).
        log.info("── Applying click behaviors ──")
        _apply_click_behaviors(client, dashboards, card_ids_by_dash, dash_id_by_name)

    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the Ninja Overview dashboard in Metabase")
    parser.add_argument("--url", default="http://metabase:3000",
                        help="Metabase base URL (default: http://metabase:3000)")
    parser.add_argument("--user", required=True, help="Metabase admin email")
    parser.add_argument("--password",
                        help="Metabase admin password (avoid — visible in process list)")
    parser.add_argument("--password-file",
                        help="Read password from file. Plain content OR a .env-style line")
    parser.add_argument("--password-file-key", default="MB_ADMIN_PASS",
                        help="Env-var key to read in --password-file (default: MB_ADMIN_PASS)")
    parser.add_argument("--db-name", default="Ninja",
                        help="Display name of the Postgres data source in Metabase (default: Ninja)")
    args = parser.parse_args()

    logging.basicConfig(
        level="INFO", format="%(asctime)s %(levelname)s %(message)s",
    )

    password = _resolve_password(args)
    urls = run_bootstrap(args.url, args.user, password, args.db_name)
    print()
    print("✓ Dashboards ready:")
    for url in urls:
        print(f"  - {url}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
