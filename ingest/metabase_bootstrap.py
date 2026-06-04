"""Metabase dashboard bootstrap.

Provisions Ninja patch operator dashboards in Metabase via its REST
API. Idempotent — re-running updates existing cards / dashboards
rather than creating duplicates. Iterate on SQL by editing the card
spec lists below and re-running.

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

Layout uses Metabase's 24-column grid.

The former "Ninja — Patch Coverage" dashboard is now named
"Ninja — Patching Status"; bootstrap renames the legacy dashboard in
place when present.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

from ingest import db
from ingest.config import settings

log = logging.getLogger("metabase_bootstrap")

COLLECTION_NAME = "Ninja"

# Dashboard names — defined early so card-spec click_behaviors below
# can reference them. Don't rename without updating drill targets.
DASH_COMMAND     = "Ninja — Patch Command Center"
DASH_OVERVIEW    = "Ninja — Overall Patching Status"
DASH_ORG         = "Ninja — Org Overview"
DASH_DETAIL      = "Ninja — Patch Detail (Filterable)"
DASH_DRILLDOWN   = "Ninja — Device Drilldown"
DASH_PCOV        = "Ninja — Device Patching Status"
DASH_TRENDS      = "Ninja — Trends"

DEFAULT_STALE_PATCH_DAYS = 35

OS_FAMILY_SQL = """
CASE
    WHEN {alias}.os_name ILIKE '%Windows 11%' THEN 'Windows 11'
    WHEN {alias}.os_name ILIKE '%Windows 10%' THEN 'Windows 10'
    WHEN {alias}.os_name ILIKE '%Windows Server%' THEN 'Windows Server'
    WHEN {alias}.os_name ILIKE '%Windows%' THEN 'Other Windows'
    ELSE 'Unknown'
END
"""

PATCH_ACTIVITY_LABEL_SQL = """
CASE {expr}
    WHEN 'active_patching' THEN 'Patching Devices'
    WHEN 'stale_patch_data' THEN 'Stalled Devices'
    WHEN 'no_patch_data' THEN 'Never-Patched Devices'
    ELSE 'Unknown'
END
"""

# Shared color palettes for pie / bar / series viz_settings. Green =
# good, amber = attention, red = critical. Used in pie.colors and
# series_settings.<series>.color.
PATCH_STATE_COLORS = {
    "INSTALLED": "#2e7d32",   # green — done
    "APPROVED":  "#1976d2",   # blue — queued for install
    "DELAYED":   "#1565c0",   # darker blue — auto-approval pending
    "MANUAL":    "#f9a825",   # amber — admin action required
    "FAILED":    "#c62828",   # red — install failed
    "REJECTED":  "#757575",   # grey — rejected by policy
    "PENDING":   "#9e9e9e",   # light grey
    "Unknown":   "#bdbdbd",
}

PATCH_ACTIVITY_COLORS = {
    "Patching Devices":      "#2e7d32",  # green
    "Stalled Devices":       "#f9a825",  # amber
    "Never-Patched Devices": "#c62828",  # red
    "Unknown":               "#bdbdbd",
}

# Canonical patch-lifecycle and reboot activity codes for the
# Device Drilldown "Recent Patch & Reboot Activity" card and the
# Command Center "Recent Patch Activity (Fleet)" card. Restricting at
# the dashboard layer means the cards stay focused even if the ingest
# TYPES_INCLUDE has broader codes. PATCH_MANAGEMENT_MESSAGE is left
# OUT — it's the noisy generic info message code.
_DRILLDOWN_ACTIVITY_CODES = (
    "PATCH_MANAGEMENT_APPLY_PATCH_STARTED",
    "PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED",
    "PATCH_MANAGEMENT_FAILURE",
    "PATCH_MANAGEMENT_ROLLBACK_PATCH_REQUESTED",
    "PATCH_MANAGEMENT_ROLLBACK_PATCH_STARTED",
    "PATCH_MANAGEMENT_ROLLBACK_PATCH_COMPLETED",
    "PATCH_MANAGEMENT_PATCH_APPROVED",
    "PATCH_MANAGEMENT_PATCH_REJECTED",
    "SYSTEM_REBOOTED",
)
_DRILLDOWN_ACTIVITY_CODES_SQL = ", ".join(
    f"'{c}'" for c in _DRILLDOWN_ACTIVITY_CODES
)

OS_FAMILY_D = OS_FAMILY_SQL.format(alias="d").strip()
OS_FAMILY_C = OS_FAMILY_SQL.format(alias="c").strip()
PATCH_ACTIVITY_LABEL_C = PATCH_ACTIVITY_LABEL_SQL.format(expr="c.patch_status").strip()
DEVICE_TYPE_D = """
CASE d.node_class
    WHEN 'WINDOWS_WORKSTATION' THEN 'Windows Workstation'
    WHEN 'WINDOWS_SERVER' THEN 'Windows Server'
    ELSE d.node_class
END
""".strip()
DEVICE_TYPE_C = """
CASE c.node_class
    WHEN 'WINDOWS_WORKSTATION' THEN 'Windows Workstation'
    WHEN 'WINDOWS_SERVER' THEN 'Windows Server'
    ELSE c.node_class
END
""".strip()


# ── Card specs ──────────────────────────────────────────────────────

COMMAND_CARDS: list[dict[str, Any]] = [
    # Row 0 — Devices (canonical order: Active, Patching, Stalled,
    # Never-Patched, Needs Reboot). Sizes: 5+5+5+5+4 = 24.
    {
        "key":     "cmd_active_devices",
        "name":    "Active Devices",
        "display": "scalar",
        "row": 0, "col": 0, "size_x": 5, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {}},
        "query": """
SELECT COUNT(*) AS devices
FROM ninja_core.v_active_devices
""",
    },
    {
        "key":     "cmd_patching",
        "name":    "Patching Devices",
        "display": "scalar",
        "row": 0, "col": 5, "size_x": 5, "size_y": 4,
        "click_behavior": {"target": DASH_PCOV, "preset": {"pcov_status": "Patching Devices"}},
        "query": f"""
WITH last_install AS (
    SELECT device_id, MAX(installed_at) AS last_install_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
)
SELECT COUNT(*) AS devices
FROM ninja_core.devices d
JOIN last_install li ON li.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
  AND li.last_install_at >= NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS})
""",
    },
    {
        "key":     "cmd_stale",
        "name":    "Stalled Devices",
        "display": "scalar",
        "row": 0, "col": 10, "size_x": 5, "size_y": 4,
        "click_behavior": {"target": DASH_PCOV, "preset": {"pcov_status": "Stalled Devices"}},
        "query": f"""
WITH last_install AS (
    SELECT device_id, MAX(installed_at) AS last_install_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
)
SELECT COUNT(*) AS devices
FROM ninja_core.devices d
JOIN last_install li ON li.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
  AND li.last_install_at < NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS})
""",
    },
    {
        "key":     "cmd_never",
        "name":    "Never-Patched Devices",
        "display": "scalar",
        "row": 0, "col": 15, "size_x": 5, "size_y": 4,
        "click_behavior": {"target": DASH_PCOV, "preset": {"pcov_status": "Never-Patched Devices"}},
        "query": """
SELECT COUNT(*) AS devices
FROM ninja_core.devices d
LEFT JOIN ninja_patches.patch_facts pf
  ON pf.device_id = d.id
 AND pf.fact_type = 'install_outcome'
 AND pf.installed_at IS NOT NULL
WHERE d.approval_status = 'APPROVED'
  AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
  AND pf.device_id IS NULL
""",
    },
    {
        "key":     "cmd_reboot",
        "name":    "Needs Reboot",
        "display": "scalar",
        "row": 0, "col": 20, "size_x": 4, "size_y": 4,
        "query": """
SELECT COUNT(*) AS devices
FROM ninja_core.v_active_devices
WHERE needs_reboot = TRUE
""",
    },
    # Row 4 — Patches (canonical order: Approved, Manual, Delayed,
    # Failed). Sizes: 6+6+6+6 = 24.
    {
        "key":     "cmd_approved",
        "name":    "Approved Patches",
        "display": "scalar",
        "row": 4, "col": 0, "size_x": 6, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {"status": "APPROVED"}},
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT COUNT(*) AS patches
FROM current_state
WHERE status = 'APPROVED'
""",
    },
    {
        "key":     "cmd_manual",
        "name":    "Manual Approval",
        "display": "scalar",
        "row": 4, "col": 6, "size_x": 6, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {"status": "MANUAL"}},
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT COUNT(*) AS patches
FROM current_state
WHERE status = 'MANUAL'
""",
    },
    {
        "key":     "cmd_delayed",
        "name":    "Delayed Patches",
        "display": "scalar",
        "row": 4, "col": 12, "size_x": 6, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {"status": "DELAYED"}},
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT COUNT(*) AS patches
FROM current_state
WHERE status = 'DELAYED'
""",
    },
    {
        "key":     "cmd_failed",
        "name":    "Failed Patches",
        "display": "scalar",
        "row": 4, "col": 18, "size_x": 6, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {"install_outcome": "FAILED"}},
        "query": """
WITH latest_install_result AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
)
SELECT COUNT(*) AS patches
FROM latest_install_result
WHERE status = 'FAILED'
""",
    },
    {
        "key":     "cmd_clients",
        "name":    "Clients Needing Attention",
        "display": "table",
        "row": 8, "col": 0, "size_x": 24, "size_y": 10,
        "column_click_behaviors": {
            "organization": {"target": DASH_ORG, "params": {"p_org": "organization"}},
        },
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
),
latest_install_result AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
),
last_install AS (
    SELECT device_id, MAX(installed_at) AS last_install_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
),
device_status AS (
    SELECT
        d.id,
        d.organization_id,
        CASE
            WHEN li.last_install_at IS NULL THEN 'never'
            WHEN li.last_install_at < NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS}) THEN 'stale'
            ELSE 'recent'
        END AS patch_activity
    FROM ninja_core.devices d
    LEFT JOIN last_install li ON li.device_id = d.id
    WHERE d.approval_status = 'APPROVED'
      AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
)
SELECT
    o.name AS organization,
    COUNT(DISTINCT d.id) AS "Active Devices",
    COUNT(*) FILTER (WHERE lio.status = 'FAILED') AS "Failed Patches",
    COUNT(*) FILTER (WHERE cs.status = 'MANUAL') AS "Manual Approval Patches",
    COUNT(*) FILTER (WHERE cs.status = 'DELAYED') AS "Delayed Install Patches",
    COUNT(DISTINCT ds.id) FILTER (WHERE ds.patch_activity = 'stale') AS "Stalled Devices",
    COUNT(DISTINCT ds.id) FILTER (WHERE ds.patch_activity = 'never') AS "Never-Patched Devices",
    COUNT(DISTINCT d.id) FILTER (WHERE d.needs_reboot = TRUE) AS "Devices Needing Reboot"
FROM ninja_core.v_active_devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
LEFT JOIN current_state cs ON cs.device_id = d.id
LEFT JOIN latest_install_result lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
LEFT JOIN device_status ds ON ds.id = d.id
GROUP BY o.name
HAVING
    COUNT(*) FILTER (WHERE lio.status = 'FAILED') > 0
    OR COUNT(*) FILTER (WHERE cs.status IN ('MANUAL','DELAYED')) > 0
    OR COUNT(DISTINCT ds.id) FILTER (WHERE ds.patch_activity IN ('stale','never')) > 0
    OR COUNT(DISTINCT d.id) FILTER (WHERE d.needs_reboot = TRUE) > 0
ORDER BY
    "Failed Patches" DESC,
    "Manual Approval Patches" DESC,
    "Delayed Install Patches" DESC,
    "Stalled Devices" DESC,
    "Never-Patched Devices" DESC,
    organization
LIMIT 50
""",
    },
    {
        "key":     "cmd_failed_queue",
        "name":    "Failed Patch Queue",
        "display": "table",
        "row": 18, "col": 0, "size_x": 24, "size_y": 10,
        "column_click_behaviors": {
            "organization": {"target": DASH_ORG,       "params": {"p_org": "organization"}},
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "kb_number":    {"target": DASH_DETAIL,    "params": {"p_kb": "kb_number"}},
        },
        "query": """
WITH latest_install_result AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status, severity, kb_number, name AS patch_name,
        installed_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
)
SELECT
    o.name AS organization,
    d.system_name AS device,
    COALESCE(NULLIF(lir.kb_number, ''), '(none)') AS kb_number,
    lir.patch_name AS "Patch",
    lir.severity AS "Severity",
    lir.status AS "Install Results",
    lir.installed_at AS "Last Install Attempt",
    CASE WHEN lir.installed_at IS NULL THEN NULL
         ELSE ROUND(EXTRACT(EPOCH FROM (NOW() - lir.installed_at)) / 86400)
    END AS "Days Since Attempt"
FROM latest_install_result lir
JOIN ninja_core.v_active_devices d ON d.id = lir.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE lir.status = 'FAILED'
ORDER BY lir.installed_at DESC NULLS LAST, o.name, d.system_name
LIMIT 100
""",
    },
    {
        "key":     "cmd_approval_queue",
        "name":    "Manual and Delayed Patches",
        "display": "table",
        "row": 28, "col": 0, "size_x": 12, "size_y": 10,
        "column_click_behaviors": {
            "organization":        {"target": DASH_ORG,    "params": {"p_org": "organization"}},
            "device":              {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "current_patch_state": {"target": DASH_DETAIL, "params": {"p_status": "current_patch_state"}},
            "kb_number":           {"target": DASH_DETAIL, "params": {"p_kb": "kb_number"}},
        },
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status, severity, kb_number, name AS patch_name,
        last_observed_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT
    o.name AS organization,
    d.system_name AS device,
    cs.status AS current_patch_state,
    COALESCE(NULLIF(cs.kb_number, ''), '(none)') AS kb_number,
    cs.patch_name AS "Patch",
    cs.severity AS "Severity",
    cs.last_observed_at AS "Last Seen"
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE cs.status IN ('MANUAL', 'DELAYED')
ORDER BY
    CASE cs.status WHEN 'MANUAL' THEN 0 ELSE 1 END,
    cs.last_observed_at DESC,
    o.name,
    d.system_name
LIMIT 100
""",
    },
    {
        "key":     "cmd_patch_activity_queue",
        "name":    "Stalled Devices",
        "display": "table",
        "row": 28, "col": 12, "size_x": 12, "size_y": 10,
        "column_click_behaviors": {
            "organization":    {"target": DASH_ORG,       "params": {"p_org": "organization"}},
            "device":          {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "patching_status": {"target": DASH_PCOV,      "params": {"p_pcov_status": "patching_status"}},
        },
        "query": f"""
WITH last_install AS (
    SELECT device_id, MAX(installed_at) AS last_install_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
),
classified AS (
    SELECT
        d.id,
        d.system_name,
        d.organization_id,
        d.node_class,
        d.os_name,
        li.last_install_at,
        CASE
            WHEN li.last_install_at IS NULL THEN 'no_patch_data'
            WHEN li.last_install_at < NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS}) THEN 'stale_patch_data'
            ELSE 'active_patching'
        END AS patch_status
    FROM ninja_core.devices d
    LEFT JOIN last_install li ON li.device_id = d.id
    WHERE d.approval_status = 'APPROVED'
      AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
)
SELECT
    o.name AS organization,
    c.system_name AS device,
    {PATCH_ACTIVITY_LABEL_C} AS patching_status,
    c.last_install_at AS "Last Install Attempt",
    CASE WHEN c.last_install_at IS NULL THEN NULL
         ELSE ROUND(EXTRACT(EPOCH FROM (NOW() - c.last_install_at)) / 86400)
    END AS "Days Since Attempt",
    CASE c.node_class
        WHEN 'WINDOWS_WORKSTATION' THEN 'Windows Workstation'
        WHEN 'WINDOWS_SERVER' THEN 'Windows Server'
        ELSE c.node_class
    END AS "Device Type",
    {OS_FAMILY_C} AS "Operating System Family"
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE c.patch_status IN ('stale_patch_data', 'no_patch_data')
ORDER BY
    CASE c.patch_status WHEN 'no_patch_data' THEN 0 ELSE 1 END,
    c.last_install_at ASC NULLS FIRST,
    o.name,
    c.system_name
LIMIT 100
""",
    },
    # Row 38 — Devices with installed patches still pending reboot.
    # Join INSTALLED patches × needs_reboot=true × no SYSTEM_REBOOTED
    # activity since last install. Common patching-loop gap: install
    # landed, reboot didn't happen, the patch hasn't really "taken".
    {
        "key":     "cmd_awaiting_reboot",
        "name":    "Patches Installed Awaiting Reboot",
        "display": "table",
        "row": 38, "col": 0, "size_x": 24, "size_y": 10,
        "column_click_behaviors": {
            "organization": {"target": DASH_ORG,       "params": {"p_org": "organization"}},
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
        },
        "query": """
WITH last_install AS (
    SELECT device_id,
           MAX(installed_at) AS last_install_at,
           COUNT(*)          AS install_count
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND status    = 'INSTALLED'
      AND installed_at IS NOT NULL
    GROUP BY device_id
),
last_reboot AS (
    SELECT device_id, MAX(activity_time) AS last_reboot_at
    FROM ninja_activities.activities
    WHERE activity_type = 'SYSTEM_REBOOTED'
      AND device_id IS NOT NULL
    GROUP BY device_id
)
SELECT
    o.name AS organization,
    d.system_name AS device,
    li.last_install_at AS "Last Install",
    lr.last_reboot_at  AS "Last Reboot",
    li.install_count   AS "Installs",
    ROUND(EXTRACT(EPOCH FROM (NOW() - li.last_install_at))/3600)::int
        AS "Hours Since Install"
FROM ninja_core.v_active_devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
JOIN last_install li ON li.device_id = d.id
LEFT JOIN last_reboot lr ON lr.device_id = d.id
WHERE d.needs_reboot = TRUE
  AND (lr.last_reboot_at IS NULL OR lr.last_reboot_at < li.last_install_at)
ORDER BY li.last_install_at DESC
LIMIT 100
""",
    },
    # Row 48 — Fleet-wide patch + reboot activity stream. Same
    # allowlist as the Device Drilldown card so the noise/signal
    # mix matches.
    {
        "key":     "cmd_recent_activity",
        "name":    "Recent Patch Activity (Fleet)",
        "display": "table",
        "row": 48, "col": 0, "size_x": 24, "size_y": 10,
        "column_click_behaviors": {
            "organization": {"target": DASH_ORG,       "params": {"p_org": "organization"}},
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
        },
        "query": f"""
SELECT
    a.activity_time AS "Time",
    d.system_name   AS device,
    o.name          AS organization,
    a.activity_type AS "Event Code",
    a.subject       AS "Event",
    a.message       AS "Message"
FROM ninja_activities.activities a
JOIN ninja_core.devices d ON d.id = a.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE a.activity_type IN ({_DRILLDOWN_ACTIVITY_CODES_SQL})
ORDER BY a.activity_time DESC
LIMIT 100
""",
    },
]

OVERVIEW_CARDS: list[dict[str, Any]] = [
    # Row 0 — Compliance headline + Data Freshness sidekick.
    {
        "key":        "overall_compliance",
        "name":       "Patch Compliance",
        "display":    "scalar",
        "row": 0, "col": 0, "size_x": 18, "size_y": 4,
        # Fleet-wide compliance %: installed (device, patch) pairs over
        # the universe of all known (device, patch) on active Windows
        # devices.
        "query": """
WITH all_patches AS (
    SELECT DISTINCT pf.device_id, pf.patch_uid
    FROM ninja_patches.patch_facts pf
    JOIN ninja_core.v_active_devices d ON d.id = pf.device_id
    WHERE d.approval_status = 'APPROVED'
),
installed_patches AS (
    SELECT DISTINCT device_id, patch_uid
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome' AND status = 'INSTALLED'
)
SELECT ROUND(
    COUNT(*) FILTER (WHERE ip.device_id IS NOT NULL) * 100.0
    / NULLIF(COUNT(*), 0),
    1
) AS percent_installed
FROM all_patches ap
LEFT JOIN installed_patches ip USING (device_id, patch_uid)
""",
    },
    {
        # Data freshness indicator. If ingest is broken, every other
        # number on the dashboard is stale — this card surfaces that
        # explicitly. Reads the most recent successful run from
        # run_log. Bold if older than the warning threshold.
        "key":     "overall_data_freshness",
        "name":    "Data Freshness",
        "display": "scalar",
        "row": 0, "col": 18, "size_x": 6, "size_y": 4,
        "query": """
SELECT
    CASE
        WHEN max_ts IS NULL THEN 'no ingest yet'
        WHEN max_ts < NOW() - INTERVAL '3 hours' THEN
            'STALE — last ok run ' ||
            ROUND(EXTRACT(EPOCH FROM (NOW() - max_ts)) / 3600)::text ||
            ' h ago'
        ELSE
            ROUND(EXTRACT(EPOCH FROM (NOW() - max_ts)) / 60)::text ||
            ' min ago'
    END AS data_freshness
FROM (
    SELECT MAX(started_at) AS max_ts
    FROM ninja_core.run_log
    WHERE status = 'ok'
) latest
""",
    },
    # Row 4 — Devices (canonical order: Active, Patching, Stalled,
    # Never-Patched, Needs Reboot). 5 scalars at sizes 5+5+5+5+4 = 24.
    {
        "key":        "active_devices",
        "name":       "Active Devices",
        "display":    "scalar",
        "row": 4, "col": 0, "size_x": 5, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {}},
        "query": """
SELECT COUNT(*) AS devices
FROM ninja_core.v_active_devices
""",
    },
    # Row 8 — Patches (canonical order: Approved, Manual, Delayed,
    # Failed). 4 scalars at size 6 each = 24.
    {
        "key":        "patches_ready",
        "name":       "Approved Patches",
        "display":    "scalar",
        "row": 8, "col": 0, "size_x": 6, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {"status": "APPROVED"}},
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT COUNT(*) AS approved_queued
FROM current_state WHERE status = 'APPROVED'
""",
    },
    {
        "key":        "patches_manual",
        "name":       "Manual Approval",
        "display":    "scalar",
        "row": 8, "col": 6, "size_x": 6, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {"status": "MANUAL"}},
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT COUNT(*) AS manual
FROM current_state WHERE status = 'MANUAL'
""",
    },
    {
        "key":        "patches_delayed",
        "name":       "Delayed Patches",
        "display":    "scalar",
        "row": 8, "col": 12, "size_x": 6, "size_y": 4,
        "click_behavior": {"target": DASH_DETAIL, "preset": {"status": "DELAYED"}},
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT COUNT(*) AS delayed
FROM current_state WHERE status = 'DELAYED'
""",
    },
    {
        "key":        "patches_failed",
        "name":       "Failed Patches",
        "display":    "scalar",
        "row": 8, "col": 18, "size_x": 6, "size_y": 4,
        "click_behavior": {
            "target": DASH_DETAIL,
            "preset": {"install_outcome": "FAILED"},
        },
        "query": """
WITH latest_install_outcome AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
)
SELECT COUNT(*) AS failed
FROM latest_install_outcome
WHERE status = 'FAILED'
""",
    },
    # Row 4 — Devices group continuation: Patching, Stalled, Never-
    # Patched sit alongside active_devices (col 0) for the canonical
    # device row. 4 scalars at size 6 each.
    {
        "key":     "ov_pcov_active",
        "name":    "Patching Devices",
        "display": "scalar",
        "row": 4, "col": 5, "size_x": 5, "size_y": 4,
        "click_behavior": {
            "target": DASH_PCOV,
            "preset": {"pcov_status": "Patching Devices"},
        },
        "query": f"""
WITH dps AS (
    SELECT device_id, MAX(installed_at) AS last_seen_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
)
SELECT COUNT(*) AS active
FROM ninja_core.devices d
JOIN dps ON dps.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND dps.last_seen_at > NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS})
""",
    },
    {
        "key":     "ov_pcov_stale",
        "name":    "Stalled Devices",
        "display": "scalar",
        "row": 4, "col": 10, "size_x": 5, "size_y": 4,
        "click_behavior": {
            "target": DASH_PCOV,
            "preset": {"pcov_status": "Stalled Devices"},
        },
        "query": f"""
WITH dps AS (
    SELECT device_id, MAX(installed_at) AS last_seen_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
)
SELECT COUNT(*) AS stale
FROM ninja_core.devices d
JOIN dps ON dps.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND dps.last_seen_at <= NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS})
""",
    },
    {
        "key":     "ov_pcov_none",
        "name":    "Never-Patched Devices",
        "display": "scalar",
        "row": 4, "col": 15, "size_x": 5, "size_y": 4,
        "click_behavior": {
            "target": DASH_PCOV,
            "preset": {"pcov_status": "Never-Patched Devices"},
        },
        "query": """
SELECT COUNT(*) AS no_data
FROM ninja_core.devices d
LEFT JOIN ninja_patches.patch_facts pf
  ON pf.device_id = d.id
 AND pf.fact_type = 'install_outcome'
 AND pf.installed_at IS NOT NULL
WHERE d.approval_status = 'APPROVED'
  AND pf.device_id IS NULL
""",
    },
    {
        "key":     "overall_reboot",
        "name":    "Needs Reboot",
        "display": "scalar",
        "row": 4, "col": 20, "size_x": 4, "size_y": 4,
        "query": """
SELECT COUNT(*) AS devices
FROM ninja_core.v_active_devices
WHERE needs_reboot = TRUE
""",
    },
    # Row 12 — Charts: Current Patch State pie + Worst Compliance bar.
    {
        "key":        "patch_state_donut",
        "name":       "Current Patch State",
        "display":    "pie",
        "row": 12, "col": 0, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "pie.dimension":       "Current Patch State",
            "pie.metric":          "Patches",
            # 0 = show every slice; default 2.5 buckets small ones into "Other"
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
            "pie.colors":          PATCH_STATE_COLORS,
        },
        # Click a status slice → open Detail filtered to that status.
        "click_behavior": {
            "target": DASH_DETAIL,
            "params": {"p_status": "Current Patch State"},
        },
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT status AS "Current Patch State", COUNT(*) AS "Patches"
FROM current_state
GROUP BY status
ORDER BY "Patches" DESC
""",
    },
    {
        "key":        "compliance_worst",
        "name":       "Clients with Lowest Patch Compliance",
        "display":    "row",
        "row": 12, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["organization"],
            "graph.metrics":    ["Patch Compliance"],
        },
        # Click an org bar → open Org Overview filtered to that org.
        "click_behavior": {
            "target": DASH_ORG,
            "params": {"p_org": "organization"},
        },
        # Compliance = (device, patch) pairs with a successful install
        # divided by the universe of (device, patch) pairs we know
        # about. INSTALLED rows live in fact_type='install_outcome'; the
        # old query filtered to fact_type='patch_state' and so could
        # never count any installs — every org showed 0 %.
        "query": """
WITH all_patches AS (
    SELECT DISTINCT device_id, patch_uid
    FROM ninja_patches.patch_facts
),
installed_patches AS (
    SELECT DISTINCT device_id, patch_uid
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome' AND status = 'INSTALLED'
)
SELECT
    o.name AS organization,
    ROUND(
      COUNT(*) FILTER (WHERE ip.device_id IS NOT NULL) * 100.0
      / NULLIF(COUNT(*), 0),
      1
    ) AS "Patch Compliance",
    COUNT(*) AS "Total Patches"
FROM all_patches ap
LEFT JOIN installed_patches ip USING (device_id, patch_uid)
JOIN ninja_core.v_active_devices d ON d.id = ap.device_id
JOIN ninja_core.organizations o   ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
GROUP BY o.name
HAVING COUNT(*) >= 50
ORDER BY "Patch Compliance" ASC
LIMIT 15
""",
    },
    {
        "key":        "compliance_all",
        "name":       "Client Patch Compliance",
        "display":    "table",
        "row": 20, "col": 0, "size_x": 24, "size_y": 10,
        "column_click_behaviors": {
            "organization": {
                "target": DASH_ORG,
                "params": {"p_org": "organization"},
            },
        },
        # Same compliance bug as compliance_worst: pulling from
        # patch_state only never captures INSTALLED rows. Fixed by
        # using the install_outcome side for both the "Installed" count
        # and the numerator of "Patch Compliance".
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
),
latest_install_outcome AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
),
all_patches AS (
    SELECT DISTINCT device_id, patch_uid
    FROM ninja_patches.patch_facts
),
installed_patches AS (
    SELECT DISTINCT device_id, patch_uid
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome' AND status = 'INSTALLED'
)
SELECT
    o.name AS organization,
    ROUND(
      COUNT(*) FILTER (WHERE ip.device_id IS NOT NULL) * 100.0
      / NULLIF(COUNT(*), 0),
      1
    ) AS "Patch Compliance",
    COUNT(*) FILTER (WHERE ip.device_id IS NOT NULL)                         AS "Installed",
    COUNT(*) FILTER (WHERE cs.status = 'APPROVED')                           AS "Approved Patches",
    COUNT(*) FILTER (WHERE cs.status = 'MANUAL')                             AS "Manual Approval Patches",
    COUNT(*) FILTER (WHERE cs.status = 'DELAYED')                            AS "Delayed Install Patches",
    COUNT(*) FILTER (WHERE lio.status = 'FAILED')                            AS "Failed Patches",
    COUNT(*) FILTER (WHERE cs.status = 'REJECTED')                           AS "Rejected",
    COUNT(*)                                                                 AS "Total Patches",
    COUNT(DISTINCT ap.device_id)                                             AS "Devices"
FROM all_patches ap
LEFT JOIN current_state cs
  ON cs.device_id = ap.device_id AND cs.patch_uid = ap.patch_uid
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = ap.device_id AND lio.patch_uid = ap.patch_uid
LEFT JOIN installed_patches ip
  ON ip.device_id = ap.device_id AND ip.patch_uid = ap.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = ap.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
GROUP BY o.name
HAVING COUNT(*) >= 10
ORDER BY "Patch Compliance" ASC, "Total Patches" DESC
""",
    },
    {
        "key":        "needs_reboot",
        "name":       "Devices Needing Reboot",
        "display":    "table",
        "row": 30, "col": 0, "size_x": 24, "size_y": 8,
        # Stable lowercase aliases on every column. Inert self-link
        # placeholders on last_contact / reported_at were removed —
        # they were the v0.7.4 "suppress drill popup" experiment but
        # were misaligning click_behaviors to the wrong columns. The
        # drill popup on info columns is the lesser evil.
        "column_click_behaviors": {
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "organization": {"target": DASH_ORG,       "params": {"p_org":    "organization"}},
            "device_type":  {"target": DASH_DETAIL,    "params": {"p_class":  "device_type"}},
        },
        "query": f"""
SELECT
    d.system_name AS device,
    o.name AS organization,
    {DEVICE_TYPE_D} AS device_type,
    d.last_contact AS last_contact,
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
        "row": 38, "col": 0, "size_x": 24, "size_y": 8,
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
        # Purely diagnostic table — no meaningful drill destination.
        # Self-link with empty preset suppresses Metabase's default
        # "filter by this value" prompt on every cell.
        "column_click_behaviors": {
            "domain":      {"target": "self", "preset": {}},
            "status":      {"target": "self", "preset": {}},
            "started_at":  {"target": "self", "preset": {}},
            "duration_ms": {"target": "self", "preset": {}},
            "inserted":    {"target": "self", "preset": {}},
            "upserted":    {"target": "self", "preset": {}},
            "error":       {"target": "self", "preset": {}},
        },
    },
]

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
    current_dash_id: int | None = None,
) -> dict | None:
    """Three shapes, in priority order:

    A. preset (for scalar/number cards or inert table cells): URL
       navigation. target="self" resolves to the current dashboard,
       empty preset {} produces a no-op self-link that visually
       suppresses Metabase's default drill menu on that cell.
           spec = {"target": <dash name>|"self", "preset": {<slug>: <value>}}
       → linkTemplate = /dashboard/<id>[?slug=val&...]

    B. params with target="self": crossfilter the current dashboard.
           spec = {"target": "self", "params": {<param_id>: <col>}}

    C. params with target=<dash name>: cross-dashboard link with
       parameterMapping reading from the row's columns.
    """
    target = spec.get("target")
    preset = spec.get("preset")

    if preset is not None:
        if target == "self":
            if current_dash_id is None:
                log.warning("click_behavior target='self' but current_dash_id unknown")
                return None
            target_id = current_dash_id
        else:
            target_id = dash_id_by_name.get(target)
            if target_id is None:
                log.warning("Click behavior: unknown target dashboard %r", target)
                return None
        path = f"/dashboard/{target_id}"
        if preset:
            qs = "&".join(f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in preset.items())
            path = f"{path}?{qs}"
        return {
            "type":         "link",
            "linkType":     "url",
            "linkTemplate": path,
        }

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
        current_dash_id = dash_id_by_name.get(dash_spec["name"])
        for card_spec in dash_spec["cards"]:
            extra: dict[str, Any] = {}

            if "click_behavior" in card_spec:
                cb = _build_click_behavior_json(
                    card_spec["click_behavior"], dash_id_by_name, current_dash_id,
                )
                if cb:
                    extra["click_behavior"] = cb

            if "column_click_behaviors" in card_spec:
                column_settings: dict[str, dict] = {}
                for col, ccb in card_spec["column_click_behaviors"].items():
                    cb = _build_click_behavior_json(ccb, dash_id_by_name, current_dash_id)
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
PARAM_OUTCOME = "p_install_outcome"
PARAM_DEVICE      = "p_device"
PARAM_DEVICE_DAYS = "p_device_days"

# Static dropdown options for known small enums. Dynamic ones (orgs, OS
# names) are populated from the DB in build_detail_parameters().
_STATUS_OPTIONS = [
    "INSTALLED", "FAILED", "APPROVED", "PENDING", "REJECTED", "DELAYED", "MANUAL",
]
_NODE_CLASS_OPTIONS = ["Windows Workstation", "Windows Server"]
_SEVERITY_OPTIONS = ["CRITICAL", "IMPORTANT", "OPTIONAL", "MODERATE", "LOW", "NONE"]
_OUTCOME_OPTIONS = ["FAILED", "INSTALLED"]
_OS_FAMILY_OPTIONS = ["Windows 11", "Windows 10", "Windows Server", "Other Windows", "Unknown"]


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


def build_detail_parameters(
    org_names: list[str], os_families: list[str], device_names: list[str],
) -> list[dict]:
    """Construct the dashboard's parameter widgets.

    Organization and Device are populated from live data. Device Type
    defaults to Windows Workstation so the MSP workflow "patch
    workstations across all clients first" is the default view.
    """
    return [
        _param_dropdown(PARAM_ORG,    "Organization", "org",        org_names),
        _param_dropdown(PARAM_DEVICE, "Device",       "device",     device_names),
        _param_dropdown(PARAM_STATUS, "Current Patch State", "status",  _STATUS_OPTIONS),
        _param_dropdown(PARAM_CLASS,  "Device Type",  "node_class", _NODE_CLASS_OPTIONS,
                        default="Windows Workstation"),
        _param_dropdown(PARAM_SEV,    "Severity",     "severity",   _SEVERITY_OPTIONS),
        _param_dropdown(PARAM_OUTCOME, "Install Results", "install_outcome",
                        _OUTCOME_OPTIONS),
        _param_dropdown(PARAM_OS,     "Operating System Family", "os", os_families),
        _param_text(    PARAM_KB,     "KB Number",    "kb"),
        _param_number(  PARAM_DAYS,   "Timeline window (days)", "days", 90),
    ]


# Each filtered card declares the same template tags + maps the dashboard
# parameters onto them.
_FILTER_TAGS = {
    "org":        {"id": "tt_org",        "name": "org",        "display-name": "Organization", "type": "text"},
    "status":     {"id": "tt_status",     "name": "status",     "display-name": "Current Patch State", "type": "text"},
    "node_class": {"id": "tt_node_class", "name": "node_class", "display-name": "Device Type",  "type": "text"},
    "severity":   {"id": "tt_severity",   "name": "severity",   "display-name": "Severity",     "type": "text"},
    "install_outcome": {
        "id": "tt_install_outcome", "name": "install_outcome",
        "display-name": "Install Results", "type": "text",
    },
    "os":         {"id": "tt_os",         "name": "os",         "display-name": "Operating System Family", "type": "text"},
    "kb":         {"id": "tt_kb",         "name": "kb",         "display-name": "KB Number",    "type": "text"},
    "device":     {"id": "tt_device",     "name": "device",     "display-name": "Device",       "type": "text"},
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
    PARAM_OUTCOME: ["variable", ["template-tag", "install_outcome"]],
    PARAM_OS:     ["variable", ["template-tag", "os"]],
    PARAM_KB:     ["variable", ["template-tag", "kb"]],
    PARAM_DEVICE: ["variable", ["template-tag", "device"]],
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
    WHERE pf.fact_type = 'patch_state'
    ORDER BY pf.device_id, pf.patch_uid, pf.last_observed_at DESC, pf.id DESC
),
latest_install_outcome AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status, severity,
        name AS patch_name, kb_number, installed_at, ninja_observed_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
)
"""
_FILTER_PREDICATES = f"""
  [[AND o.name = {{{{org}}}}]]
  [[AND cs.status = {{{{status}}}}]]
  [[AND {DEVICE_TYPE_D} = {{{{node_class}}}}]]
  [[AND cs.severity = {{{{severity}}}}]]
  [[AND lio.status = {{{{install_outcome}}}}]]
  [[AND {OS_FAMILY_D} = {{{{os}}}}]]
  [[AND cs.kb_number = {{{{kb}}}}]]
  [[AND d.system_name = {{{{device}}}}]]
"""

DETAIL_CARDS = [
    {
        "key":            "detail_status_donut",
        "name":           "Current Patch State",
        "display":        "pie",
        "row": 0, "col": 0, "size_x": 8, "size_y": 6,
        "viz_settings":   {
            "pie.dimension":       "Current Patch State",
            "pie.metric":          "Patches",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": "self", "params": {"p_status": "Current Patch State"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT cs.status AS "Current Patch State", COUNT(*) AS "Patches"
FROM current_state cs
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY cs.status
ORDER BY "Patches" DESC
""",
    },
    {
        "key":            "detail_severity_bar",
        "name":           "Severity Breakdown",
        "display":        "bar",
        "row": 0, "col": 8, "size_x": 8, "size_y": 6,
        "viz_settings":   {"graph.dimensions": ["Severity"], "graph.metrics": ["Patches"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": "self", "params": {"p_severity": "Severity"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT COALESCE(NULLIF(cs.severity, ''), 'NONE') AS "Severity", COUNT(*) AS "Patches"
FROM current_state cs
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY 1
ORDER BY "Patches" DESC
""",
    },
    {
        "key":            "detail_top_devices",
        "name":           "Devices by Patch Count",
        "display":        "row",
        "row": 0, "col": 16, "size_x": 8, "size_y": 6,
        "viz_settings":   {"graph.dimensions": ["Device"], "graph.metrics": ["Patches"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": DASH_DRILLDOWN, "params": {"p_device": "Device"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    d.system_name AS "Device",
    COUNT(*) AS "Patches"
FROM current_state cs
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY d.system_name
ORDER BY "Patches" DESC
LIMIT 15
""",
    },
    {
        "key":            "detail_top_kbs",
        "name":           "KBs by Patch Count",
        "display":        "row",
        "row": 6, "col": 0, "size_x": 12, "size_y": 8,
        "viz_settings":   {"graph.dimensions": ["KB Number"], "graph.metrics": ["Patches"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "click_behavior": {"target": "self", "params": {"p_kb": "KB Number"}},
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    COALESCE(NULLIF(cs.kb_number, ''), '(none)') AS "KB Number",
    COUNT(*) AS "Patches"
FROM current_state cs
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY 1
ORDER BY "Patches" DESC
LIMIT 20
""",
    },
    {
        "key":            "detail_installs_timeline",
        "name":           "Install Results Over Time",
        "display":        "line",
        "row": 6, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings":   {"graph.dimensions": ["Day"], "graph.metrics": ["Install Results"]},
        "template_tags":  {**_FILTER_TAGS, **_DAYS_TAG},
        "param_mappings": _TIMELINE_PARAM_MAPPINGS,
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    DATE_TRUNC('day', lio.installed_at)::date AS "Day",
    COUNT(*) AS "Install Results"
FROM current_state cs
JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE lio.installed_at IS NOT NULL
  AND lio.installed_at > NOW() - (INTERVAL '1 day' * {{{{days}}}})
  AND d.approval_status = 'APPROVED'
  [[AND o.name = {{{{org}}}}]]
  [[AND cs.status = {{{{status}}}}]]
  [[AND lio.status = {{{{install_outcome}}}}]]
  [[AND {DEVICE_TYPE_D} = {{{{node_class}}}}]]
  [[AND cs.severity = {{{{severity}}}}]]
  [[AND {OS_FAMILY_D} = {{{{os}}}}]]
  [[AND cs.kb_number = {{{{kb}}}}]]
  [[AND d.system_name = {{{{device}}}}]]
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":            "detail_all_devices",
        "name":           "All Devices by Patch Count",
        "display":        "table",
        "row": 14, "col": 0, "size_x": 12, "size_y": 10,
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "organization": {"target": "self",         "params": {"p_org": "organization"}},
            "device_type":  {"target": "self",         "params": {"p_class": "device_type"}},
        },
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    d.system_name        AS device,
    o.name               AS organization,
    {DEVICE_TYPE_D} AS device_type,
    COUNT(*)             AS "Patches"
FROM current_state cs
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY d.system_name, o.name, device_type
ORDER BY "Patches" DESC
""",
    },
    {
        "key":            "detail_all_kbs",
        "name":           "All KBs by Count",
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
    cs.patch_name AS "Patch",
    cs.severity AS "Severity",
    COUNT(DISTINCT cs.device_id) AS "Devices",
    COUNT(*)                     AS "Patches"
FROM current_state cs
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
GROUP BY 1, cs.patch_name, cs.severity
ORDER BY "Patches" DESC
""",
    },
    {
        "key":            "detail_table",
        "name":           "Patch Detail Table",
        "display":        "table",
        "row": 24, "col": 0, "size_x": 24, "size_y": 14,
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "device":              {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "organization":        {"target": "self",         "params": {"p_org":      "organization"}},
            "device_type":         {"target": "self",         "params": {"p_class":    "device_type"}},
            "current_patch_state": {"target": "self",         "params": {"p_status":   "current_patch_state"}},
            "install_results":     {"target": "self",         "params": {"p_install_outcome": "install_results"}},
            "severity":            {"target": "self",         "params": {"p_severity": "severity"}},
            "kb_number":           {"target": "self",         "params": {"p_kb":       "kb_number"}},
        },
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    o.name           AS organization,
    d.system_name    AS device,
    {DEVICE_TYPE_D} AS device_type,
    cs.kb_number AS kb_number,
    cs.patch_name AS "Patch",
    cs.status AS current_patch_state,
    lio.status AS install_results,
    cs.severity AS severity,
    lio.installed_at AS "Last Install Attempt",
    CASE WHEN lio.installed_at IS NULL THEN NULL
         ELSE ROUND(EXTRACT(EPOCH FROM (NOW() - lio.installed_at)) / 86400)
    END AS "Days Since Attempt",
    cs.last_observed_at AS "Last Seen"
FROM current_state cs
LEFT JOIN latest_install_outcome lio
  ON lio.device_id = cs.device_id AND lio.patch_uid = cs.patch_uid
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
ORDER BY cs.last_observed_at DESC, lio.installed_at DESC NULLS LAST
LIMIT 1000
""",
    },
]


# ── Device Drilldown dashboard ──────────────────────────────────────
#
# Per-device deep dive. Filter is an exact device name selected from
# the active Windows fleet.

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

_DEVICE_FILTER = "[[AND d.system_name = {{device}}]]"


def build_device_parameters(device_names: list[str]) -> list[dict]:
    """Device selector + timeline window."""
    return [
        _param_dropdown(PARAM_DEVICE,      "Device", "device", device_names),
        _param_number(  PARAM_DEVICE_DAYS, "Timeline window (days)", "device_days", 180),
    ]


DEVICE_CARDS = [
    {
        "key":            "device_info",
        "name":           "Device Summary",
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
    d.id                   AS "Device ID",
    d.system_name          AS "Device",
    d.display_name         AS "Display Name",
    o.name                 AS "Organization",
    {DEVICE_TYPE_D}        AS "Device Type",
    d.os_name              AS "Operating System",
    d.os_release_id        AS "OS Release",
    d.serial_number        AS "Serial Number",
    d.manufacturer         AS "Manufacturer",
    d.model                AS "Model",
    ls.last_contact        AS "Last Contact",
    ls.last_boot           AS "Last Boot",
    ls.needs_reboot        AS "Needs Reboot",
    ls.maintenance_status  AS "Maintenance Status"
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
        "name":           "Current Patch State",
        "display":        "pie",
        "row": 6, "col": 0, "size_x": 8, "size_y": 8,
        "viz_settings":   {
            "pie.dimension":       "Current Patch State",
            "pie.metric":          "Patches",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  DEVICE_TAGS,
        "param_mappings": DEVICE_PARAM_MAPPINGS,
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT cs.status AS "Current Patch State", COUNT(*) AS "Patches"
FROM current_state cs
JOIN ninja_core.devices d ON d.id = cs.device_id
WHERE d.approval_status = 'APPROVED'
{_DEVICE_FILTER}
GROUP BY cs.status
ORDER BY "Patches" DESC
""",
    },
    {
        "key":            "device_install_timeline",
        "name":           "Install Results Over Time",
        "display":        "line",
        "row": 6, "col": 8, "size_x": 16, "size_y": 8,
        "viz_settings":   {"graph.dimensions": ["Day"], "graph.metrics": ["Install Results"]},
        "template_tags":  DEVICE_TIMELINE_TAGS,
        "param_mappings": DEVICE_TIMELINE_PARAM_MAPPINGS,
        "query": f"""
SELECT
    DATE_TRUNC('day', pf.installed_at)::date AS "Day",
    COUNT(*) AS "Install Results"
FROM ninja_patches.patch_facts pf
JOIN ninja_core.devices d ON d.id = pf.device_id
WHERE pf.installed_at IS NOT NULL
  AND pf.fact_type = 'install_outcome'
  AND pf.installed_at > NOW() - (INTERVAL '1 day' * {{{{days}}}})
  AND d.approval_status = 'APPROVED'
{_DEVICE_FILTER}
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":            "device_activities",
        "name":           "Recent Patch & Reboot Activity",
        "display":        "table",
        "row": 14, "col": 0, "size_x": 24, "size_y": 10,
        "template_tags":  DEVICE_TAGS,
        "param_mappings": DEVICE_PARAM_MAPPINGS,
        # Defense-in-depth: even if the ingest TYPES_INCLUDE has
        # broader codes set, the dashboard card only shows patch-
        # lifecycle and reboot events. Operator can edit
        # _DRILLDOWN_ACTIVITY_CODES to tweak the allowlist.
        # PATCH_MANAGEMENT_MESSAGE is intentionally excluded — it's
        # the noisy generic info code.
        "query": f"""
SELECT
    a.activity_time        AS "Activity Time",
    a.activity_type        AS "Event Code",
    a.subject              AS "Event",
    a.message              AS "Message",
    a.source_name          AS "Category",
    a.id                   AS "Activity ID"
FROM ninja_activities.activities a
JOIN ninja_core.devices d ON d.id = a.device_id
WHERE a.activity_type IN ({_DRILLDOWN_ACTIVITY_CODES_SQL})
{_DEVICE_FILTER}
ORDER BY a.activity_time DESC
LIMIT 200
""",
    },
    # Split the old "Patch History" table into two — the two
    # fact_type values are conceptually different and should not share
    # a row. patch_state shows where pending patches sit right now;
    # install_outcome shows what's been tried and the result.
    {
        "key":            "device_patch_state_history",
        "name":           "Patch State History",
        "display":        "table",
        "row": 24, "col": 0, "size_x": 24, "size_y": 12,
        "template_tags":  DEVICE_TAGS,
        "param_mappings": DEVICE_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "kb_number": {"target": DASH_DETAIL, "params": {"p_kb": "kb_number"}},
        },
        "query": f"""
SELECT
    d.system_name        AS "Device",
    pf.kb_number         AS kb_number,
    pf.name              AS "Patch",
    pf.status            AS "Patch State",
    pf.severity          AS "Severity",
    pf.first_observed_at AS "First Seen in This State",
    pf.last_observed_at  AS "Last Seen in This State"
FROM ninja_patches.patch_facts pf
JOIN ninja_core.devices d ON d.id = pf.device_id
WHERE pf.fact_type = 'patch_state'
  AND d.approval_status = 'APPROVED'
{_DEVICE_FILTER}
ORDER BY
    d.system_name,
    pf.last_observed_at DESC,
    pf.patch_uid
LIMIT 5000
""",
    },
    {
        "key":            "device_install_history",
        "name":           "Install History",
        "display":        "table",
        "row": 36, "col": 0, "size_x": 24, "size_y": 12,
        "template_tags":  DEVICE_TAGS,
        "param_mappings": DEVICE_PARAM_MAPPINGS,
        "column_click_behaviors": {
            "kb_number": {"target": DASH_DETAIL, "params": {"p_kb": "kb_number"}},
        },
        "query": f"""
SELECT
    d.system_name   AS "Device",
    pf.kb_number    AS kb_number,
    pf.name         AS "Patch",
    pf.status       AS "Install Outcome",
    pf.severity     AS "Severity",
    pf.installed_at AS "Install Attempt Time",
    pf.last_observed_at AS "Last Seen"
FROM ninja_patches.patch_facts pf
JOIN ninja_core.devices d ON d.id = pf.device_id
WHERE pf.fact_type = 'install_outcome'
  AND d.approval_status = 'APPROVED'
{_DEVICE_FILTER}
ORDER BY
    d.system_name,
    pf.installed_at DESC NULLS LAST,
    pf.last_observed_at DESC
LIMIT 5000
""",
    },
]


# ── Patching Status dashboard ───────────────────────────────────────
#
# Ninja's API doesn't return a "patch management enabled" flag on
# devices, so we infer status from install-outcome activity:
#   - active_patching  : MAX(installed_at) within the threshold
#   - stale_patch_data : install outcome exists but is older than threshold
#   - no_patch_data    : no install outcome with installed_at at all
# This catches devices the patch agent isn't reaching, regardless of
# whether the cause is config, agent failure, or decommissioning.

PARAM_PCOV_ORG    = "p_pcov_org"
PARAM_PCOV_CLASS  = "p_pcov_class"
PARAM_PCOV_OS     = "p_pcov_os"
PARAM_PCOV_STATUS = "p_pcov_status"
PARAM_PCOV_DAYS   = "p_pcov_days"

_PCOV_STATUS_OPTIONS = ["Patching Devices", "Stalled Devices", "Never-Patched Devices"]


def _param_number(pid: str, name: str, slug: str, default: int) -> dict:
    """Numeric dashboard parameter with a default value."""
    return {
        "id":      pid,
        "name":    name,
        "slug":    slug,
        "type":    "number/=",
        "default": default,
    }


def build_pcov_parameters(org_names: list[str], os_families: list[str]) -> list[dict]:
    return [
        _param_dropdown(PARAM_PCOV_ORG,    "Organization",  "pcov_org",        org_names),
        _param_dropdown(PARAM_PCOV_CLASS,  "Device Type",   "pcov_node_class", _NODE_CLASS_OPTIONS,
                        default="Windows Workstation"),
        _param_dropdown(PARAM_PCOV_OS,     "Operating System Family", "pcov_os", os_families),
        _param_dropdown(PARAM_PCOV_STATUS, "Patching Status", "pcov_status",    _PCOV_STATUS_OPTIONS),
        _param_number(  PARAM_PCOV_DAYS,   "Stale threshold (days)", "pcov_days", DEFAULT_STALE_PATCH_DAYS),
    ]


_PCOV_TAGS = {
    "pcov_org":         {"id": "tt_pcov_org",    "name": "pcov_org",        "display-name": "Organization", "type": "text"},
    "pcov_node_class":  {"id": "tt_pcov_class",  "name": "pcov_node_class", "display-name": "Device Type",  "type": "text"},
    "pcov_os":          {"id": "tt_pcov_os",     "name": "pcov_os",         "display-name": "Operating System Family", "type": "text"},
    "pcov_status":      {"id": "tt_pcov_status", "name": "pcov_status",     "display-name": "Patching Status", "type": "text"},
    "pcov_days":        {
        "id": "tt_pcov_days", "name": "pcov_days",
        "display-name": "Stale threshold (days)",
        "type": "number", "default": "35", "required": True,
    },
}

_PCOV_PARAM_MAPPINGS = {
    PARAM_PCOV_ORG:    ["variable", ["template-tag", "pcov_org"]],
    PARAM_PCOV_CLASS:  ["variable", ["template-tag", "pcov_node_class"]],
    PARAM_PCOV_OS:     ["variable", ["template-tag", "pcov_os"]],
    PARAM_PCOV_STATUS: ["variable", ["template-tag", "pcov_status"]],
    PARAM_PCOV_DAYS:   ["variable", ["template-tag", "pcov_days"]],
}

# Reused: classify every active device by its latest Ninja patch signal.
# Threshold is configurable via the dashboard's "Stale threshold (days)"
# parameter; template tag default keeps queries valid even before the
# operator sets a value.
_PCOV_CTE = """
WITH device_patch_signal AS (
    SELECT device_id, MAX(installed_at) AS last_seen_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
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
      AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
)
"""

_PCOV_FILTERS = f"""
  [[AND o.name = {{{{pcov_org}}}}]]
  [[AND {DEVICE_TYPE_C} = {{{{pcov_node_class}}}}]]
  [[AND {OS_FAMILY_C} = {{{{pcov_os}}}}]]
  [[AND {PATCH_ACTIVITY_LABEL_C} = {{{{pcov_status}}}}]]
"""

PCOV_CARDS = [
    # Active Devices first (leftmost) for consistency with every other
    # dashboard's row 0; the three patching-status breakdown scalars
    # follow.
    {
        "key":     "pcov_total",
        "name":    "Active Devices",
        "display": "scalar",
        "row": 0, "col": 0, "size_x": 6, "size_y": 4,
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
        "key":     "pcov_active",
        "name":    "Patching Devices",
        "display": "scalar",
        "row": 0, "col": 6, "size_x": 6, "size_y": 4,
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "click_behavior": {
            "target": DASH_PCOV,
            "preset": {"pcov_status": "Patching Devices"},
        },
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
        "name":    "Stalled Devices",
        "display": "scalar",
        "row": 0, "col": 12, "size_x": 6, "size_y": 4,
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "click_behavior": {
            "target": DASH_PCOV,
            "preset": {"pcov_status": "Stalled Devices"},
        },
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
        "name":    "Never-Patched Devices",
        "display": "scalar",
        "row": 0, "col": 18, "size_x": 6, "size_y": 4,
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "click_behavior": {
            "target": DASH_PCOV,
            "preset": {"pcov_status": "Never-Patched Devices"},
        },
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
        "key":     "pcov_status_pie",
        "name":    "Patching Status",
        "display": "pie",
        "row": 4, "col": 0, "size_x": 8, "size_y": 8,
        "click_behavior": {"target": "self", "params": {"p_pcov_status": "Patching Status"}},
        "viz_settings": {
            "pie.dimension":       "Patching Status",
            "pie.metric":          "devices",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
            "pie.colors":          PATCH_ACTIVITY_COLORS,
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT {PATCH_ACTIVITY_LABEL_C} AS "Patching Status", COUNT(*) AS devices
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY 1
ORDER BY devices DESC
""",
    },
    {
        "key":     "pcov_class_pie",
        "name":    "Patching Status by Device Type",
        "display": "pie",
        "row": 4, "col": 8, "size_x": 8, "size_y": 8,
        "click_behavior": {"target": "self", "params": {"p_pcov_class": "Device Type"}},
        "viz_settings": {
            "pie.dimension":       "Device Type",
            "pie.metric":          "devices",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT {DEVICE_TYPE_C} AS "Device Type", COUNT(*) AS devices
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY 1
ORDER BY devices DESC
""",
    },
    {
        "key":     "pcov_os_stacked",
        "name":    "Patching Status by Operating System",
        "display": "bar",
        "row": 4, "col": 16, "size_x": 8, "size_y": 8,
        "click_behavior": {"target": "self", "params": {"p_pcov_os": "Operating System Family"}},
        "viz_settings": {
            "graph.dimensions":      ["Operating System Family"],
            "graph.metrics":         [
                "Patching Devices",
                "Stalled Devices",
                "Never-Patched Devices",
            ],
            "stackable.stack_type":  "stacked",
            "graph.show_values":     False,
            "series_settings": {
                "Patching Devices":      {"color": PATCH_ACTIVITY_COLORS["Patching Devices"]},
                "Stalled Devices":       {"color": PATCH_ACTIVITY_COLORS["Stalled Devices"]},
                "Never-Patched Devices": {"color": PATCH_ACTIVITY_COLORS["Never-Patched Devices"]},
            },
        },
        "template_tags":  _PCOV_TAGS,
        "param_mappings": _PCOV_PARAM_MAPPINGS,
        "query": f"""
{_PCOV_CTE}
SELECT
    {OS_FAMILY_C} AS "Operating System Family",
    COUNT(*) FILTER (WHERE c.patch_status = 'active_patching')  AS "Patching Devices",
    COUNT(*) FILTER (WHERE c.patch_status = 'stale_patch_data') AS "Stalled Devices",
    COUNT(*) FILTER (WHERE c.patch_status = 'no_patch_data')    AS "Never-Patched Devices"
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY 1
ORDER BY COUNT(*) DESC
LIMIT 20
""",
    },
    {
        "key":     "pcov_by_org",
        "name":    "Patching Status by Organization",
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
    COUNT(*) FILTER (WHERE c.patch_status = 'active_patching')  AS "Patching Devices",
    COUNT(*) FILTER (WHERE c.patch_status = 'stale_patch_data') AS "Stalled Devices",
    COUNT(*) FILTER (WHERE c.patch_status = 'no_patch_data')    AS "Never-Patched Devices",
    COUNT(*)                                                    AS "Total Devices",
    ROUND(
        COUNT(*) FILTER (WHERE c.patch_status = 'active_patching') * 100.0
        / NULLIF(COUNT(*), 0), 1
    ) AS "Patching %"
FROM classified c
JOIN ninja_core.organizations o ON o.id = c.organization_id
WHERE 1=1
{_PCOV_FILTERS}
GROUP BY o.name
ORDER BY "Patching %" ASC, "Total Devices" DESC
""",
    },
    {
        "key":     "pcov_all_devices",
        "name":    "All Devices by Patching Status",
        "display": "table",
        "row": 20, "col": 0, "size_x": 24, "size_y": 14,
        "column_click_behaviors": {
            "device":                  {"target": DASH_DRILLDOWN, "params": {"p_device":      "device"}},
            "organization":            {"target": "self",         "params": {"p_pcov_org":    "organization"}},
            "device_type":             {"target": "self",         "params": {"p_pcov_class":  "device_type"}},
            "operating_system_family": {"target": "self",         "params": {"p_pcov_os":     "operating_system_family"}},
            "patching_status":         {"target": "self",         "params": {"p_pcov_status": "patching_status"}},
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
    c.device_id AS "Device ID",
    c.system_name AS device,
    o.name AS organization,
    {DEVICE_TYPE_C} AS device_type,
    {OS_FAMILY_C} AS operating_system_family,
    {PATCH_ACTIVITY_LABEL_C} AS patching_status,
    c.last_seen_at AS "Last Install Attempt",
    lc.last_contact AS "Last Contact",
    CASE WHEN c.last_seen_at IS NULL THEN NULL
         ELSE EXTRACT(DAY FROM (NOW() - c.last_seen_at))::int
    END AS "Days Since Attempt",
    CASE WHEN lc.last_contact IS NULL THEN NULL
         ELSE EXTRACT(DAY FROM (NOW() - lc.last_contact))::int
    END AS "Days Since Contact"
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


# ── Org Overview dashboard ──────────────────────────────────────────

_ORG_TAGS = {
    "org":         {"id": "tt_org_overview_org",         "name": "org",         "display-name": "Organization", "type": "text"},
    "device_type": {"id": "tt_org_overview_device_type", "name": "device_type", "display-name": "Device Type",  "type": "text"},
    "os_family":   {"id": "tt_org_overview_os_family",   "name": "os_family",   "display-name": "OS Family",    "type": "text"},
    "severity":    {"id": "tt_org_overview_severity",    "name": "severity",    "display-name": "Severity",     "type": "text"},
}

# Param mapping for cards that only have the patch dimensions (no
# severity — device-count cards skip severity entirely).
_ORG_PARAM_MAPPINGS = {
    PARAM_ORG:   ["variable", ["template-tag", "org"]],
    PARAM_CLASS: ["variable", ["template-tag", "device_type"]],
    PARAM_OS:    ["variable", ["template-tag", "os_family"]],
}

# Param mapping for patch-context cards that also honor severity.
_ORG_PARAM_MAPPINGS_FULL = {
    **_ORG_PARAM_MAPPINGS,
    PARAM_SEV:   ["variable", ["template-tag", "severity"]],
}

# SQL predicate fragments for Org Overview filters. Each ends with a
# trailing newline so cards can append them directly after their own
# WHERE/AND lines. Device-only cards use the DEVICE variant; patch-
# context cards use PATCH_CS (cs.severity alias) or PATCH_LIR
# (lir.severity alias).
_ORG_FILTER_ORG         = "  [[AND o.name = {{org}}]]\n"
_ORG_FILTER_DEVICE_TYPE = f"  [[AND {DEVICE_TYPE_D} = {{{{device_type}}}}]]\n"
_ORG_FILTER_OS_FAMILY   = f"  [[AND {OS_FAMILY_D} = {{{{os_family}}}}]]\n"
_ORG_FILTER_SEV_CS      = "  [[AND cs.severity = {{severity}}]]\n"
_ORG_FILTER_SEV_LIR     = "  [[AND lir.severity = {{severity}}]]\n"

# Device-count cards (no severity context).
_ORG_FILTERS_DEVICE = (
    _ORG_FILTER_ORG + _ORG_FILTER_DEVICE_TYPE + _ORG_FILTER_OS_FAMILY
)
# Patch cards using `cs.severity` (current_state alias).
_ORG_FILTERS_PATCH_CS = _ORG_FILTERS_DEVICE + _ORG_FILTER_SEV_CS
# Patch cards using `lir.severity` (latest_install_result alias).
_ORG_FILTERS_PATCH_LIR = _ORG_FILTERS_DEVICE + _ORG_FILTER_SEV_LIR
# Cross-org-only filters (for the per-device-type / per-OS-family
# charts where the X dimension is itself the filter we'd otherwise
# constrain). Patch-context with severity but skipping one of the
# device dimensions.
_ORG_FILTERS_PATCH_CS_NO_CLASS = (
    _ORG_FILTER_ORG + _ORG_FILTER_OS_FAMILY + _ORG_FILTER_SEV_CS
)
_ORG_FILTERS_PATCH_CS_NO_OS = (
    _ORG_FILTER_ORG + _ORG_FILTER_DEVICE_TYPE + _ORG_FILTER_SEV_CS
)


def build_org_parameters(org_names: list[str]) -> list[dict]:
    return [
        _param_dropdown(PARAM_ORG,   "Organization", "org",         org_names),
        _param_dropdown(PARAM_CLASS, "Device Type",  "device_type", _NODE_CLASS_OPTIONS),
        _param_dropdown(PARAM_OS,    "OS Family",    "os_family",   _OS_FAMILY_OPTIONS),
        _param_dropdown(PARAM_SEV,   "Severity",     "severity",    _SEVERITY_OPTIONS),
    ]


ORG_OVERVIEW_CARDS = [
    {
        "key":     "org_active_devices",
        "name":    "Active Devices",
        "display": "scalar",
        "row": 4, "col": 0, "size_x": 5, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        "query": f"""
SELECT COUNT(*) AS devices
FROM ninja_core.v_active_devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE 1=1
{_ORG_FILTERS_DEVICE}
""",
    },
    {
        "key":     "org_compliance",
        "name":    "Patch Compliance",
        "display": "scalar",
        "row": 0, "col": 0, "size_x": 24, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        # Same compliance bug as Fleet Overview's compliance cards:
        # INSTALLED lives in fact_type='install_outcome', not
        # 'patch_state'. Compute installed from install_outcome over
        # the universe of all (device, patch) we know about. The
        # all_patches CTE also pulls node_class + os_name so the
        # dashboard's device_type / os_family filters can scope.
        "query": f"""
WITH all_patches AS (
    SELECT DISTINCT pf.device_id, pf.patch_uid, d.organization_id,
                    d.node_class, d.os_name
    FROM ninja_patches.patch_facts pf
    JOIN ninja_core.v_active_devices d ON d.id = pf.device_id
    WHERE d.approval_status = 'APPROVED'
),
installed_patches AS (
    SELECT DISTINCT device_id, patch_uid
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome' AND status = 'INSTALLED'
)
SELECT ROUND(
    COUNT(*) FILTER (WHERE ip.device_id IS NOT NULL) * 100.0
    / NULLIF(COUNT(*), 0),
    1
) AS percent_installed
FROM all_patches d
LEFT JOIN installed_patches ip USING (device_id, patch_uid)
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE 1=1
{_ORG_FILTERS_DEVICE}
""",
    },
    {
        "key":     "org_failed",
        "name":    "Failed Patches",
        "display": "scalar",
        "row": 8, "col": 18, "size_x": 6, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS_FULL,
        "query": f"""
WITH latest_install_result AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status, severity
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
)
SELECT COUNT(*) AS patches
FROM latest_install_result lir
JOIN ninja_core.v_active_devices d ON d.id = lir.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE lir.status = 'FAILED'
{_ORG_FILTERS_PATCH_LIR}
""",
    },
    {
        "key":     "org_approved",
        "name":    "Approved Patches",
        "display": "scalar",
        "row": 8, "col": 0, "size_x": 6, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS_FULL,
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status, severity
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE cs.status = 'APPROVED'
{_ORG_FILTERS_PATCH_CS}
""",
    },
    {
        "key":     "org_manual",
        "name":    "Manual Approval",
        "display": "scalar",
        "row": 8, "col": 6, "size_x": 6, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS_FULL,
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status, severity
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE cs.status = 'MANUAL'
{_ORG_FILTERS_PATCH_CS}
""",
    },
    {
        "key":     "org_delayed",
        "name":    "Delayed Patches",
        "display": "scalar",
        "row": 8, "col": 12, "size_x": 6, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS_FULL,
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status, severity
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT COUNT(*) AS patches
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE cs.status = 'DELAYED'
{_ORG_FILTERS_PATCH_CS}
""",
    },
    {
        "key":     "org_stale",
        "name":    "Stalled Devices",
        "display": "scalar",
        "row": 4, "col": 10, "size_x": 5, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        "query": f"""
WITH last_install AS (
    SELECT device_id, MAX(installed_at) AS last_install_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
)
SELECT COUNT(*) AS devices
FROM ninja_core.devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
JOIN last_install li ON li.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
  AND li.last_install_at < NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS})
{_ORG_FILTERS_DEVICE}
""",
    },
    {
        "key":     "org_never",
        "name":    "Never-Patched Devices",
        "display": "scalar",
        "row": 4, "col": 15, "size_x": 5, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        "query": f"""
SELECT COUNT(*) AS devices
FROM ninja_core.devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
LEFT JOIN ninja_patches.patch_facts pf
  ON pf.device_id = d.id
 AND pf.fact_type = 'install_outcome'
 AND pf.installed_at IS NOT NULL
WHERE d.approval_status = 'APPROVED'
  AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
  AND pf.device_id IS NULL
{_ORG_FILTERS_DEVICE}
""",
    },
    {
        "key":     "org_patching",
        "name":    "Patching Devices",
        "display": "scalar",
        "row": 4, "col": 5, "size_x": 5, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        "query": f"""
WITH last_install AS (
    SELECT device_id, MAX(installed_at) AS last_install_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
)
SELECT COUNT(*) AS devices
FROM ninja_core.devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
JOIN last_install li ON li.device_id = d.id
WHERE d.approval_status = 'APPROVED'
  AND d.node_class IN ('WINDOWS_WORKSTATION', 'WINDOWS_SERVER')
  AND li.last_install_at >= NOW() - (INTERVAL '1 day' * {DEFAULT_STALE_PATCH_DAYS})
{_ORG_FILTERS_DEVICE}
""",
    },
    {
        "key":     "org_reboot",
        "name":    "Needs Reboot",
        "display": "scalar",
        "row": 4, "col": 20, "size_x": 4, "size_y": 4,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        "query": f"""
SELECT COUNT(*) AS devices
FROM ninja_core.v_active_devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE d.needs_reboot = TRUE
{_ORG_FILTERS_DEVICE}
""",
    },
    {
        "key":     "org_status",
        "name":    "Current Patch State",
        "display": "pie",
        "row": 12, "col": 0, "size_x": 8, "size_y": 8,
        "viz_settings": {
            "pie.dimension": "Current Patch State",
            "pie.metric": "Patches",
            "pie.slice_threshold": 0,
            "pie.show_legend": True,
            "pie.show_total": True,
            "pie.colors": PATCH_STATE_COLORS,
        },
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS_FULL,
        "click_behavior": {"target": DASH_DETAIL, "params": {"p_org": "Organization", "p_status": "Current Patch State"}},
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status, severity
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT
    o.name AS "Organization",
    cs.status AS "Current Patch State",
    COUNT(*) AS "Patches"
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE 1=1
{_ORG_FILTERS_PATCH_CS}
GROUP BY o.name, cs.status
ORDER BY "Patches" DESC
""",
    },
    {
        "key":     "org_device_type",
        "name":    "Patch Compliance by Device Type",
        "display": "bar",
        "row": 12, "col": 8, "size_x": 8, "size_y": 8,
        "viz_settings": {"graph.dimensions": ["Device Type"], "graph.metrics": ["Patch Compliance"]},
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        "click_behavior": {"target": DASH_DETAIL, "params": {"p_org": "Organization", "p_class": "Device Type"}},
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT
    o.name AS "Organization",
    {DEVICE_TYPE_D} AS "Device Type",
    ROUND(COUNT(*) FILTER (WHERE cs.status = 'INSTALLED') * 100.0 / NULLIF(COUNT(*), 0), 1) AS "Patch Compliance"
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE 1=1
{_ORG_FILTERS_DEVICE}
GROUP BY o.name, "Device Type"
ORDER BY "Patch Compliance" ASC
""",
    },
    {
        "key":     "org_os_family",
        "name":    "Patch Compliance by Operating System",
        "display": "bar",
        "row": 12, "col": 16, "size_x": 8, "size_y": 8,
        "viz_settings": {"graph.dimensions": ["Operating System Family"], "graph.metrics": ["Patch Compliance"]},
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        "click_behavior": {"target": DASH_DETAIL, "params": {"p_org": "Organization", "p_os": "Operating System Family"}},
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) device_id, patch_uid, status
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT
    o.name AS "Organization",
    {OS_FAMILY_D} AS "Operating System Family",
    ROUND(COUNT(*) FILTER (WHERE cs.status = 'INSTALLED') * 100.0 / NULLIF(COUNT(*), 0), 1) AS "Patch Compliance"
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE 1=1
{_ORG_FILTERS_DEVICE}
GROUP BY o.name, "Operating System Family"
ORDER BY "Patch Compliance" ASC
""",
    },
    {
        "key":     "org_failed_queue",
        "name":    "Failed Patch Queue",
        "display": "table",
        "row": 20, "col": 0, "size_x": 24, "size_y": 10,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS_FULL,
        "column_click_behaviors": {
            "organization": {"target": "self",         "params": {"p_org": "organization"}},
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "kb_number":    {"target": DASH_DETAIL,    "params": {"p_org": "organization", "p_kb": "kb_number"}},
        },
        "query": f"""
WITH latest_install_result AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status, severity, kb_number, name AS patch_name,
        installed_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
    ORDER BY
        device_id,
        patch_uid,
        installed_at DESC NULLS LAST,
        ninja_observed_at DESC NULLS LAST,
        last_observed_at DESC,
        id DESC
)
SELECT
    o.name AS organization,
    d.system_name AS device,
    COALESCE(NULLIF(lir.kb_number, ''), '(none)') AS kb_number,
    lir.patch_name AS "Patch",
    lir.severity AS "Severity",
    lir.status AS "Install Results",
    lir.installed_at AS "Last Install Attempt",
    CASE WHEN lir.installed_at IS NULL THEN NULL
         ELSE ROUND(EXTRACT(EPOCH FROM (NOW() - lir.installed_at)) / 86400)
    END AS "Days Since Attempt"
FROM latest_install_result lir
JOIN ninja_core.v_active_devices d ON d.id = lir.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE lir.status = 'FAILED'
{_ORG_FILTERS_PATCH_LIR}
ORDER BY lir.installed_at DESC NULLS LAST, d.system_name
LIMIT 100
""",
    },
    {
        "key":     "org_action_queue",
        "name":    "Manual and Delayed Patches",
        "display": "table",
        "row": 30, "col": 0, "size_x": 24, "size_y": 10,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS_FULL,
        "column_click_behaviors": {
            "organization":        {"target": "self",      "params": {"p_org": "organization"}},
            "device":              {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "current_patch_state": {"target": DASH_DETAIL, "params": {"p_org": "organization", "p_status": "current_patch_state"}},
            "kb_number":           {"target": DASH_DETAIL, "params": {"p_org": "organization", "p_kb": "kb_number"}},
        },
        "query": f"""
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status, severity, kb_number, name AS patch_name,
        last_observed_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT
    o.name AS organization,
    d.system_name AS device,
    cs.status AS current_patch_state,
    COALESCE(NULLIF(cs.kb_number, ''), '(none)') AS kb_number,
    cs.patch_name AS "Patch",
    cs.severity AS "Severity",
    cs.last_observed_at AS "Last Seen"
FROM current_state cs
JOIN ninja_core.v_active_devices d ON d.id = cs.device_id
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE cs.status IN ('MANUAL', 'DELAYED')
{_ORG_FILTERS_PATCH_CS}
ORDER BY
    CASE cs.status WHEN 'MANUAL' THEN 0 ELSE 1 END,
    cs.last_observed_at DESC,
    d.system_name
LIMIT 100
""",
    },
    {
        "key":     "org_reboot_devices",
        "name":    "Devices Needing Reboot",
        "display": "table",
        "row": 40, "col": 0, "size_x": 24, "size_y": 8,
        "template_tags":  _ORG_TAGS,
        "param_mappings": _ORG_PARAM_MAPPINGS,
        # Lowercase snake_case aliases on every clickable column.
        # Inert "Last Contact" placeholder removed — same v0.11.3
        # lesson as Fleet Overview's needs_reboot (inerts misaligned
        # click_behaviors to the wrong columns).
        "column_click_behaviors": {
            "organization": {"target": "self",         "params": {"p_org": "organization"}},
            "device":       {"target": DASH_DRILLDOWN, "params": {"p_device": "device"}},
            "device_type":  {"target": DASH_DETAIL,    "params": {"p_org": "organization", "p_class": "device_type"}},
        },
        "query": f"""
SELECT
    o.name AS organization,
    d.system_name AS device,
    {DEVICE_TYPE_D} AS device_type,
    {OS_FAMILY_D} AS operating_system_family,
    d.last_contact AS last_contact
FROM ninja_core.v_active_devices d
JOIN ninja_core.organizations o ON o.id = d.organization_id
WHERE d.needs_reboot = TRUE
{_ORG_FILTERS_DEVICE}
ORDER BY d.last_contact DESC
""",
    },
]


# ── Trends dashboard ────────────────────────────────────────────────
# Time-series rollups derived from the historical timestamps we
# already capture: install_outcome.installed_at (per install attempt),
# activities.activity_time (per event), device_snapshots.snapshot_at
# (hourly device check-in record). No new schema needed.

PARAM_TRENDS_DAYS = "p_trends_days"

_TRENDS_TAGS = {
    "days": {
        "id": "tt_trends_days", "name": "days",
        "display-name": "Timeline window (days)",
        "type": "number", "default": "90", "required": True,
    },
}

_TRENDS_PARAM_MAPPINGS = {
    PARAM_TRENDS_DAYS: ["variable", ["template-tag", "days"]],
}


def build_trends_parameters() -> list[dict]:
    return [
        _param_number(PARAM_TRENDS_DAYS, "Timeline window (days)", "days", 90),
    ]


TRENDS_CARDS = [
    {
        "key":     "trends_installs_daily",
        "name":    "Patch Installs per Day",
        "display": "bar",
        "row": 0, "col": 0, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["Day"],
            "graph.metrics":    ["Installs"],
            "graph.show_values": False,
        },
        "template_tags":  _TRENDS_TAGS,
        "param_mappings": _TRENDS_PARAM_MAPPINGS,
        "query": """
SELECT
    DATE_TRUNC('day', installed_at)::date AS "Day",
    COUNT(*)                              AS "Installs"
FROM ninja_patches.patch_facts
WHERE fact_type = 'install_outcome'
  AND status    = 'INSTALLED'
  AND installed_at IS NOT NULL
  AND installed_at > NOW() - (INTERVAL '1 day' * {{days}})
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":     "trends_failures_daily",
        "name":    "Failed Install Attempts per Day",
        "display": "bar",
        "row": 0, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["Day"],
            "graph.metrics":    ["Failures"],
            "graph.show_values": False,
            "series_settings": {
                "Failures": {"color": "#c62828"},
            },
        },
        "template_tags":  _TRENDS_TAGS,
        "param_mappings": _TRENDS_PARAM_MAPPINGS,
        "query": """
SELECT
    DATE_TRUNC('day', installed_at)::date AS "Day",
    COUNT(*)                              AS "Failures"
FROM ninja_patches.patch_facts
WHERE fact_type = 'install_outcome'
  AND status    = 'FAILED'
  AND installed_at IS NOT NULL
  AND installed_at > NOW() - (INTERVAL '1 day' * {{days}})
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":     "trends_reboots_daily",
        "name":    "System Reboots per Day",
        "display": "bar",
        "row": 8, "col": 0, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["Day"],
            "graph.metrics":    ["Reboots"],
            "graph.show_values": False,
        },
        "template_tags":  _TRENDS_TAGS,
        "param_mappings": _TRENDS_PARAM_MAPPINGS,
        "query": """
SELECT
    DATE_TRUNC('day', activity_time)::date AS "Day",
    COUNT(*)                               AS "Reboots"
FROM ninja_activities.activities
WHERE activity_type = 'SYSTEM_REBOOTED'
  AND activity_time > NOW() - (INTERVAL '1 day' * {{days}})
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":     "trends_active_devices",
        "name":    "Active Devices Seen per Day",
        "display": "line",
        "row": 8, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["Day"],
            "graph.metrics":    ["Active Devices"],
            "graph.show_values": False,
        },
        "template_tags":  _TRENDS_TAGS,
        "param_mappings": _TRENDS_PARAM_MAPPINGS,
        # Daily distinct device count from device_snapshots — answers
        # "how many devices were checking in on day D?". Useful for
        # spotting fleet drops (e.g. agent rollout regression).
        "query": """
SELECT
    DATE_TRUNC('day', snapshot_at)::date AS "Day",
    COUNT(DISTINCT device_id)            AS "Active Devices"
FROM ninja_core.device_snapshots
WHERE snapshot_at > NOW() - (INTERVAL '1 day' * {{days}})
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "key":     "trends_manual_age",
        "name":    "Currently-MANUAL Patches by Age",
        "display": "bar",
        "row": 16, "col": 0, "size_x": 24, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["Week First Seen"],
            "graph.metrics":    ["MANUAL Patches"],
            "graph.show_values": False,
            "series_settings": {
                "MANUAL Patches": {"color": "#f9a825"},
            },
        },
        # No filter on the days param — this is a snapshot of the
        # current MANUAL backlog grouped by when each patch first
        # showed up in MANUAL state. Shows how stale the admin queue
        # is. Older bars = patches admins have been ignoring longer.
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid)
        device_id, patch_uid, status, first_observed_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'patch_state'
    ORDER BY device_id, patch_uid, last_observed_at DESC, id DESC
)
SELECT
    DATE_TRUNC('week', first_observed_at)::date AS "Week First Seen",
    COUNT(*)                                    AS "MANUAL Patches"
FROM current_state
WHERE status = 'MANUAL'
GROUP BY 1
ORDER BY 1
""",
    },
]


def build_dashboards(
    org_names: list[str], os_families: list[str], device_names: list[str],
) -> list[dict]:
    """All dashboards this script provisions. Detail / Patching Status
    dropdowns are populated from the live data passed in.

    `section_headers` (optional per dashboard): list of
    `{"row": <orig_row>, "text": <markdown>}` entries. Inserted as
    virtual text dashcards in pass 1b; every card at row >= the
    header's row is shifted down by SECTION_HEADER_HEIGHT."""
    return [
        {
            "name":       DASH_COMMAND,
            "parameters": [],
            "cards":      COMMAND_CARDS,
            "section_headers": [
                {"row": 0, "text": "### Devices"},
                {"row": 4, "text": "### Patches"},
            ],
        },
        {
            "name":       DASH_OVERVIEW,
            "parameters": [],
            "cards":      OVERVIEW_CARDS,
            "section_headers": [
                {"row": 0, "text": "### Compliance"},
                {"row": 4, "text": "### Devices"},
                {"row": 8, "text": "### Patches"},
            ],
        },
        {
            "name":       DASH_ORG,
            "parameters": build_org_parameters(org_names),
            "cards":      ORG_OVERVIEW_CARDS,
            "section_headers": [
                {"row": 0, "text": "### Compliance"},
                {"row": 4, "text": "### Devices"},
                {"row": 8, "text": "### Patches"},
            ],
        },
        {
            "name":       "Ninja — Patch Detail (Filterable)",
            "parameters": build_detail_parameters(org_names, os_families, device_names),
            "cards":      DETAIL_CARDS,
        },
        {
            "name":       "Ninja — Device Drilldown",
            "parameters": build_device_parameters(device_names),
            "cards":      DEVICE_CARDS,
        },
        {
            "name":       DASH_PCOV,
            "parameters": build_pcov_parameters(org_names, os_families),
            "cards":      PCOV_CARDS,
        },
        {
            "name":       DASH_TRENDS,
            "parameters": build_trends_parameters(),
            "cards":      TRENDS_CARDS,
        },
    ]


def _fetch_dropdown_sources() -> tuple[list[str], list[str], list[str]]:
    """Query Postgres for current orgs, OS families, and active devices."""
    db.init(settings.postgres_dsn)
    with db.transaction() as cur:
        cur.execute("SELECT name FROM ninja_core.organizations ORDER BY name")
        org_names = [r[0] for r in cur.fetchall() if r[0]]
        os_families = list(_OS_FAMILY_OPTIONS)
        cur.execute(
            "SELECT system_name FROM ninja_core.v_active_devices "
            "WHERE system_name IS NOT NULL AND system_name <> '' "
            "ORDER BY system_name"
        )
        device_names = [r[0] for r in cur.fetchall() if r[0]]
    log.info(
        "Dropdown sources: %d orgs, %d OS families, %d devices",
        len(org_names), len(os_families), len(device_names),
    )
    return org_names, os_families, device_names


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
    legacy_names = {
        # Order matters: most-recent legacy name first so it's matched
        # ahead of older names. The bootstrap renames in place if a
        # legacy name is found.
        DASH_PCOV:     ["Ninja — Patching Status", "Ninja — Patch Coverage"],
        DASH_OVERVIEW: ["Ninja — Overview"],
    }
    for d in r.json():
        names = [name, *legacy_names.get(name, [])]
        if d.get("name") in names and d.get("collection_id") == collection_id:
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

        if dash.get("name") != name:
            r = client.put(f"/api/dashboard/{dash['id']}", json={"name": name})
            r.raise_for_status()
            dash = r.json()
            log.info("Renamed dashboard to: %s (id=%s)", name, dash["id"])

    if parameters is not None:
        # Update parameters (dashboard-level filter widgets).
        r = client.put(
            f"/api/dashboard/{dash['id']}",
            json={"parameters": parameters},
        )
        r.raise_for_status()
        dash = r.json()
    return dash


NAV_HEIGHT = 2  # rows reserved at top of every dashboard for the nav bar
SECTION_HEADER_HEIGHT = 1  # rows each section header markdown card occupies
NAV_ORDER = [
    DASH_COMMAND, DASH_OVERVIEW, DASH_ORG, DASH_PCOV,
    DASH_TRENDS, DASH_DETAIL, DASH_DRILLDOWN,
]
NAV_DISPLAY_NAMES = {
    DASH_COMMAND:   "Command Center",
    DASH_OVERVIEW:  "Overall Status",
    DASH_ORG:       "Org Overview",
    DASH_PCOV:      "Device Status",
    DASH_TRENDS:    "Trends",
    DASH_DETAIL:    "Patch Detail",
    DASH_DRILLDOWN: "Device Drilldown",
}


def _build_nav_markdown(
    current_dash_name: str, dash_id_by_name: dict[str, int],
) -> str:
    """Build the markdown for the nav bar on `current_dash_name`. The
    current dashboard is shown in bold without a link; siblings link
    out. Dashboards we couldn't resolve to an id are silently skipped
    (first-run race avoided)."""
    parts: list[str] = []
    for name in NAV_ORDER:
        label = NAV_DISPLAY_NAMES.get(name, name)
        if name == current_dash_name:
            parts.append(f"**{label}**")
            continue
        did = dash_id_by_name.get(name)
        if did is None:
            continue
        parts.append(f"[{label}](/dashboard/{did})")
    return "**Navigate:** " + " · ".join(parts)


def _section_header_dashcard(text: str, row: int, idx: int) -> dict:
    """Build a virtual text dashcard that acts as a section divider
    between scalar groups. Uses Metabase's `display: "text"` virtual
    card with markdown content so a single bold/heading line styles
    the divider."""
    return {
        "id":                     -(idx + 100),
        "card_id":                None,
        "row":                    row,
        "col":                    0,
        "size_x":                 24,
        "size_y":                 SECTION_HEADER_HEIGHT,
        "parameter_mappings":     [],
        "visualization_settings": {
            "virtual_card": {
                "display":       "text",
                "name":          None,
                "archived":      False,
                "dataset_query": {},
            },
            "text": text,
        },
    }


def _nav_dashcard(text: str) -> dict:
    """Build the virtual (card_id=null) text dashcard for the nav bar.
    Metabase treats dashcards with card_id=null as text/heading panels
    when visualization_settings.virtual_card.display is set."""
    return {
        "id":                     -1,
        "card_id":                None,
        "row":                    0,
        "col":                    0,
        "size_x":                 24,
        "size_y":                 NAV_HEIGHT,
        "parameter_mappings":     [],
        "visualization_settings": {
            "virtual_card": {
                "display":       "text",
                "name":          None,
                "archived":      False,
                "dataset_query": {},
            },
            "text": text,
        },
    }


def _build_column_settings_for_dashcard(
    spec: dict, dash_id_by_name: dict[str, int], current_dash_id: int | None,
) -> dict[str, dict]:
    """Build the column_settings dict (click_behavior per column) for a
    table card. Per Metabase behavior we observed, per-column click
    behaviors must live on the *dashcard*'s visualization_settings,
    not the card's — card-level column_settings.click_behavior is
    silently ignored (the operator sees the default 'filter by this
    value' drill prompt). Whole-card click_behavior still works at
    the card level (and stays there)."""
    column_settings: dict[str, dict] = {}
    for col, ccb in spec.get("column_click_behaviors", {}).items():
        cb = _build_click_behavior_json(ccb, dash_id_by_name, current_dash_id)
        if cb:
            # Metabase keys column_settings by JSON-encoded
            # ["name", "<col>"] arrays.
            key = f'["name","{col}"]'
            column_settings[key] = {"click_behavior": cb}
    return column_settings


def _set_dashboard_layout(
    client: httpx.Client, dashboard: dict, specs: list[dict],
    card_ids: dict[str, int],
    dash_id_by_name: dict[str, int] | None = None,
    nav_markdown: str | None = None,
    section_headers: list[dict] | None = None,
) -> None:
    """Replace the dashboard's dashcards with our layout. Uses PUT
    /api/dashboard/:id with a full `dashcards` array — modern
    Metabase replaces dashcards atomically. Each dashcard's
    parameter_mappings wire dashboard filters into the card's
    template tags.

    When `nav_markdown` is provided, a virtual text dashcard is
    prepended at row 0 and every other dashcard is shifted down by
    NAV_HEIGHT — so card specs can keep their natural row numbers
    (0, 4, 8...) without baking in nav-bar offsets.

    When `dash_id_by_name` is provided, per-column click_behaviors
    from card specs are resolved and written into each dashcard's
    visualization_settings.column_settings (where Metabase actually
    honors them).

    When `section_headers` is provided (a list of
    `{"row": <orig_row>, "text": <markdown>}`), virtual text
    dashcards are inserted at those original row positions and every
    card at or below each header's row is shifted down by
    SECTION_HEADER_HEIGHT. Headers are sorted by row before
    applying."""
    dashcards = []
    row_offset = 0
    current_dash_id = int(dashboard["id"])
    if nav_markdown is not None:
        dashcards.append(_nav_dashcard(nav_markdown))
        row_offset = NAV_HEIGHT

    headers = sorted(section_headers or [], key=lambda h: h["row"])

    def shift(orig_row: int) -> int:
        """Add SECTION_HEADER_HEIGHT for every header whose original
        row is <= orig_row (the header pushes everything at or below
        it down)."""
        return orig_row + sum(
            SECTION_HEADER_HEIGHT for h in headers if h["row"] <= orig_row
        )

    # Insert each section header at its position (orig_row + the count
    # of prior headers, since each earlier header pushes this one down).
    for i, h in enumerate(headers):
        prior = sum(1 for hh in headers if hh["row"] < h["row"])
        header_row = h["row"] + prior * SECTION_HEADER_HEIGHT
        dashcards.append(
            _section_header_dashcard(h["text"], header_row + row_offset, i)
        )

    for i, spec in enumerate(specs):
        card_id = card_ids[spec["key"]]
        param_mappings = [
            {"parameter_id": pid, "card_id": card_id, "target": target}
            for pid, target in spec.get("param_mappings", {}).items()
        ]
        dashcard_viz: dict[str, Any] = {}
        if dash_id_by_name is not None:
            col_settings = _build_column_settings_for_dashcard(
                spec, dash_id_by_name, current_dash_id,
            )
            if col_settings:
                dashcard_viz["column_settings"] = col_settings
        dashcards.append({
            "id":                     -(i + 2),  # -1 reserved for nav
            "card_id":                card_id,
            "row":                    shift(spec["row"]) + row_offset,
            "col":                    spec["col"],
            "size_x":                 spec["size_x"],
            "size_y":                 spec["size_y"],
            "parameter_mappings":     param_mappings,
            "visualization_settings": dashcard_viz,
        })
    r = client.put(
        f"/api/dashboard/{dashboard['id']}",
        json={"dashcards": dashcards},
    )
    r.raise_for_status()
    log.info(
        "Set dashboard layout: %d dashcards (%d cards + %d headers)%s",
        len(dashcards), len(specs), len(headers),
        " + nav" if nav_markdown else "",
    )


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
    """Provision all dashboards in Metabase. Three passes:
      1a. Upsert cards and dashboards; collect IDs.
      1b. Set dashboard layouts with nav bar (needs all dashboard IDs
          so cross-links resolve).
      2.  Apply click_behavior (cross-dashboard drill-through and
          crossfilter — also needs IDs).
    Raises on auth / API errors."""
    org_names, os_families, device_names = _fetch_dropdown_sources()
    dashboards = build_dashboards(org_names, os_families, device_names)

    urls: list[str] = []
    dash_id_by_name: dict[str, int] = {}
    dash_obj_by_name: dict[str, dict] = {}
    card_ids_by_dash: dict[str, dict[str, int]] = {}

    with httpx.Client(base_url=url, timeout=60) as client:
        _authenticate(client, user, password)
        db_id = _find_database(client, db_name)
        log.info("Using database: %s (id=%d)", db_name, db_id)

        col_id = _upsert_collection(client, COLLECTION_NAME)
        existing_cards = _list_cards_in_collection(client, col_id)

        # Pass 1a — cards + dashboards (no layout yet).
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
            dash_id_by_name[dash_spec["name"]] = int(dashboard["id"])
            dash_obj_by_name[dash_spec["name"]] = dashboard
            card_ids_by_dash[dash_spec["name"]] = card_ids
            urls.append(f"{url}/dashboard/{dashboard['id']}  ({dash_spec['name']})")

        # Pass 1b — set layouts (with nav bar, per-column click
        # behaviors at the dashcard level, AND section headers if
        # the dashboard spec declares them) now that IDs are known.
        log.info("── Setting dashboard layouts with nav bar ──")
        for dash_spec in dashboards:
            nav_md = _build_nav_markdown(dash_spec["name"], dash_id_by_name)
            _set_dashboard_layout(
                client,
                dash_obj_by_name[dash_spec["name"]],
                dash_spec["cards"],
                card_ids_by_dash[dash_spec["name"]],
                dash_id_by_name=dash_id_by_name,
                nav_markdown=nav_md,
                section_headers=dash_spec.get("section_headers"),
            )

        # Pass 2 — click behaviors.
        log.info("── Applying click behaviors ──")
        _apply_click_behaviors(client, dashboards, card_ids_by_dash, dash_id_by_name)

        # Pass 3 — make Patch Command Center the Metabase-wide custom
        # homepage so operators land there instead of the generic
        # Metabase home. Two settings work together:
        # `custom-homepage` enables the feature; `custom-homepage-
        # dashboard` points to the dashboard id. Best-effort: warn
        # and continue if the setting endpoint rejects (older Metabase
        # versions exposed these differently).
        _set_custom_homepage(client, dash_id_by_name.get(DASH_COMMAND))

    return urls


def _set_custom_homepage(client: httpx.Client, dashboard_id: int | None) -> None:
    """Configure Metabase's instance-wide custom homepage to point at
    `dashboard_id`. Best-effort — logs and continues on failure so a
    Metabase version mismatch doesn't fail the whole bootstrap."""
    if dashboard_id is None:
        log.warning("Custom homepage: dashboard id unknown, skipping")
        return
    try:
        r = client.put(
            "/api/setting/custom-homepage",
            json={"value": True},
        )
        r.raise_for_status()
        r = client.put(
            "/api/setting/custom-homepage-dashboard",
            json={"value": dashboard_id},
        )
        r.raise_for_status()
        log.info("Set custom homepage → dashboard id=%d", dashboard_id)
    except httpx.HTTPStatusError as e:
        log.warning(
            "Custom homepage PUT failed (%s) — operator can set manually "
            "via Admin → Settings → General → Custom Homepage",
            e.response.status_code,
        )


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
