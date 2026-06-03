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
FROM ninja_core.devices
WHERE approval_status = 'APPROVED'
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
SELECT COUNT(*) AS needs_attention
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
        "key":        "patch_state_donut",
        "name":       "Patch State Breakdown",
        "display":    "pie",
        "row": 4, "col": 0, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "pie.dimension":       "status",
            "pie.metric":          "n",
            # 0 = show every slice; default 2.5 buckets small ones into "Other"
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "query": """
WITH current_state AS (
    SELECT DISTINCT ON (device_id, patch_uid) status
    FROM ninja_patches.patch_facts
    ORDER BY device_id, patch_uid, last_observed_at DESC
)
SELECT status, COUNT(*) AS n
FROM current_state
GROUP BY status
ORDER BY n DESC
""",
    },
    {
        "key":        "compliance_worst",
        "name":       "Worst-Compliant Orgs (bottom 15)",
        "display":    "row",
        "row": 4, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings": {
            "graph.dimensions": ["organization"],
            "graph.metrics":    ["pct_installed"],
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
JOIN ninja_core.devices d        ON d.id = cs.device_id
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
        "row": 12, "col": 0, "size_x": 24, "size_y": 10,
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
JOIN ninja_core.devices d        ON d.id = cs.device_id
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
        "row": 22, "col": 0, "size_x": 24, "size_y": 8,
        "query": """
WITH latest_snap AS (
    SELECT DISTINCT ON (device_id) *
    FROM ninja_core.device_snapshots
    ORDER BY device_id, snapshot_at DESC
)
SELECT
    d.system_name,
    o.name AS organization,
    d.node_class,
    ls.last_contact,
    ls.snapshot_at AS reported_at
FROM latest_snap ls
JOIN ninja_core.devices d        ON d.id = ls.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE ls.needs_reboot = TRUE
  AND d.approval_status = 'APPROVED'
ORDER BY ls.last_contact DESC
""",
    },
    {
        "key":        "ingest_health",
        "name":       "Ingest Health (last 24h)",
        "display":    "table",
        "row": 30, "col": 0, "size_x": 24, "size_y": 8,
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


def _param_dropdown(pid: str, name: str, slug: str, values: list[str]) -> dict:
    """Build a Metabase dashboard parameter with a static-list dropdown."""
    return {
        "id":                  pid,
        "name":                name,
        "slug":                slug,
        "type":                "category",
        "values_query_type":   "list",
        "values_source_type":  "static-list",
        "values_source_config": {"values": [[v] for v in values]},
    }


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
    use built-in enums; KB is a free-text search."""
    return [
        _param_dropdown(PARAM_ORG,    "Organization", "org",        org_names),
        _param_dropdown(PARAM_STATUS, "Status",       "status",     _STATUS_OPTIONS),
        _param_dropdown(PARAM_CLASS,  "Node Class",   "node_class", _NODE_CLASS_OPTIONS),
        _param_dropdown(PARAM_SEV,    "Severity",     "severity",   _SEVERITY_OPTIONS),
        _param_dropdown(PARAM_OS,     "OS Name",      "os",         os_names),
        _param_text(    PARAM_KB,     "KB Number",    "kb"),
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

_FILTER_PARAM_MAPPINGS = {
    PARAM_ORG:    ["variable", ["template-tag", "org"]],
    PARAM_STATUS: ["variable", ["template-tag", "status"]],
    PARAM_CLASS:  ["variable", ["template-tag", "node_class"]],
    PARAM_SEV:    ["variable", ["template-tag", "severity"]],
    PARAM_OS:     ["variable", ["template-tag", "os"]],
    PARAM_KB:     ["variable", ["template-tag", "kb"]],
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
            "pie.metric":          "n",
            "pie.slice_threshold": 0,
            "pie.show_legend":     True,
            "pie.show_total":      True,
        },
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT cs.status, COUNT(*) AS n
FROM current_state cs
JOIN ninja_core.devices d        ON d.id = cs.device_id
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
        "viz_settings":   {"graph.dimensions": ["severity"], "graph.metrics": ["n"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT COALESCE(NULLIF(cs.severity, ''), 'NONE') AS severity, COUNT(*) AS n
FROM current_state cs
JOIN ninja_core.devices d        ON d.id = cs.device_id
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
        "viz_settings":   {"graph.dimensions": ["device"], "graph.metrics": ["n"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    d.system_name AS device,
    COUNT(*) AS n
FROM current_state cs
JOIN ninja_core.devices d        ON d.id = cs.device_id
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
        "viz_settings":   {"graph.dimensions": ["kb_number"], "graph.metrics": ["n"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "query": f"""
{_CTE_CURRENT_STATE}
SELECT
    COALESCE(NULLIF(cs.kb_number, ''), '(none)') AS kb_number,
    COUNT(*) AS n
FROM current_state cs
JOIN ninja_core.devices d        ON d.id = cs.device_id
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
        "name":           "Installs over time (last 90 days, filtered)",
        "display":        "line",
        "row": 6, "col": 12, "size_x": 12, "size_y": 8,
        "viz_settings":   {"graph.dimensions": ["day"], "graph.metrics": ["installs"]},
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
        "query": f"""
SELECT
    DATE_TRUNC('day', pf.installed_at)::date AS day,
    COUNT(*) AS installs
FROM ninja_patches.patch_facts pf
JOIN ninja_core.devices d        ON d.id = pf.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE pf.installed_at IS NOT NULL
  AND pf.installed_at > NOW() - INTERVAL '90 days'
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
        "key":            "detail_table",
        "name":           "Patch Detail Table (filtered)",
        "display":        "table",
        "row": 14, "col": 0, "size_x": 24, "size_y": 14,
        "template_tags":  _FILTER_TAGS,
        "param_mappings": _FILTER_PARAM_MAPPINGS,
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
JOIN ninja_core.devices d        ON d.id = cs.device_id
JOIN ninja_core.organizations o  ON o.id = d.organization_id
WHERE d.approval_status = 'APPROVED'
{_FILTER_PREDICATES}
ORDER BY cs.last_observed_at DESC, cs.installed_at DESC NULLS LAST
LIMIT 1000
""",
    },
]


def build_dashboards(org_names: list[str], os_names: list[str]) -> list[dict]:
    """All dashboards this script provisions. Detail dropdowns are
    populated from the live data passed in."""
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

    org_names, os_names = _fetch_dropdown_sources()
    dashboards = build_dashboards(org_names, os_names)

    with httpx.Client(base_url=args.url, timeout=60) as client:
        _authenticate(client, args.user, password)
        db_id = _find_database(client, args.db_name)
        log.info("Using database: %s (id=%d)", args.db_name, db_id)

        col_id = _upsert_collection(client, COLLECTION_NAME)
        existing_cards = _list_cards_in_collection(client, col_id)

        urls: list[str] = []
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
            urls.append(f"{args.url}/dashboard/{dashboard['id']}  ({dash_spec['name']})")

        print()
        print("✓ Dashboards ready:")
        for url in urls:
            print(f"  - {url}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
