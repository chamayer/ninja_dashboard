"""Provision the Agent Compliance Metabase collection and dashboard."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

COLLECTION_NAME = "Agent Compliance"
DASHBOARD_NAME = "Agent Compliance - Command Center"

CARDS = [
    {
        "key": "compliance_percent",
        "name": "Compliance %",
        "display": "scalar",
        "query": """
            SELECT ROUND(
                COUNT(*) FILTER (WHERE is_compliant) * 100.0 / NULLIF(COUNT(*), 0),
                1
            ) AS compliance_percent
            FROM ninja_agent_compliance.v_compliance_matrix_current
        """,
        "row": 0, "col": 0, "size_x": 6, "size_y": 4,
    },
    {
        "key": "noncompliant_devices",
        "name": "Noncompliant Devices",
        "display": "scalar",
        "query": """
            SELECT COUNT(*) AS devices
            FROM ninja_agent_compliance.v_compliance_matrix_current
            WHERE NOT is_compliant
        """,
        "row": 0, "col": 6, "size_x": 6, "size_y": 4,
    },
    {
        "key": "active_findings",
        "name": "Active Findings",
        "display": "scalar",
        "query": """
            SELECT COUNT(*) AS findings
            FROM ninja_agent_compliance.v_active_findings
        """,
        "row": 0, "col": 12, "size_x": 6, "size_y": 4,
    },
    {
        "key": "source_failures",
        "name": "Source Failures",
        "display": "scalar",
        "query": """
            SELECT COUNT(*) AS source_failures
            FROM ninja_agent_compliance.v_source_health_current
            WHERE enabled AND status = 'failed'
        """,
        "row": 0, "col": 18, "size_x": 6, "size_y": 4,
    },
    {
        "key": "missing_by_platform",
        "name": "Missing Required Platforms",
        "display": "bar",
        "query": """
            SELECT platform, COUNT(*) AS devices
            FROM ninja_agent_compliance.v_compliance_matrix_current m
            CROSS JOIN LATERAL unnest(m.missing_required_platforms) AS platform
            GROUP BY platform
            ORDER BY devices DESC
        """,
        "row": 4, "col": 0, "size_x": 12, "size_y": 8,
    },
    {
        "key": "source_health",
        "name": "Source Health",
        "display": "table",
        "query": """
            SELECT
                platform,
                source_name,
                COALESCE(client_name, 'shared') AS client,
                status,
                rows_observed,
                finished_at,
                error_text
            FROM ninja_agent_compliance.v_source_health_current
            ORDER BY platform, source_name
        """,
        "row": 4, "col": 12, "size_x": 12, "size_y": 8,
    },
    {
        "key": "alignment_mismatches",
        "name": "Org Alignment Mismatches",
        "display": "table",
        "query": """
            SELECT
                org_name,
                overall_status,
                ninja_status,
                s1_status,
                lmi_status,
                ninja_platform_name,
                s1_platform_name,
                lmi_platform_name,
                merged_from,
                suggested_config
            FROM ninja_agent_compliance.v_alignment_mismatches
            LIMIT 500
        """,
        "row": 12, "col": 0, "size_x": 24, "size_y": 8,
    },
    {
        "key": "remediation_candidates",
        "name": "Remediation Candidates",
        "display": "table",
        "query": """
            SELECT
                client_name,
                hostname,
                device_type,
                required_platforms,
                observed_platforms,
                missing_required_platforms,
                stale_required_platforms,
                is_stale,
                is_degraded,
                s1_exempt,
                org_align_status
            FROM ninja_agent_compliance.v_remediation_candidates
            ORDER BY client_name, hostname
            LIMIT 500
        """,
        "row": 20, "col": 0, "size_x": 24, "size_y": 10,
    },
    {
        "key": "degraded_devices",
        "name": "Degraded Devices",
        "display": "table",
        "query": """
            SELECT
                client_name,
                hostname,
                device_type,
                required_platforms,
                observed_platforms,
                stale_required_platforms,
                ninja_last_seen,
                sentinelone_last_seen,
                logmein_last_seen,
                screenconnect_last_seen
            FROM ninja_agent_compliance.v_compliance_matrix_current
            WHERE is_degraded
            ORDER BY client_name, hostname
            LIMIT 500
        """,
        "row": 30, "col": 0, "size_x": 24, "size_y": 8,
    },
    {
        "key": "active_findings_table",
        "name": "Active Findings",
        "display": "table",
        "query": """
            SELECT
                severity,
                finding_type,
                affected_platform,
                client_name,
                hostname,
                summary,
                last_seen_at
            FROM ninja_agent_compliance.v_active_findings
            LIMIT 500
        """,
        "row": 38, "col": 0, "size_x": 24, "size_y": 10,
    },
    {
        # Surfaces silent client-resolution misses. When a platform org
        # / site / group name has no matching client alias and no
        # alignment fuzzy-match, the observation lands in
        # platform_observations with resolved_client_id = NULL and gets
        # filtered out of the compliance matrix. Without this card the
        # only signal is missing counts on the per-client dashboard,
        # which is easy to overlook. Operator-actionable: add a manual
        # alias row, or rename in source.
        "key": "unresolved_observations",
        "name": "Unresolved Observations (no matching client)",
        "display": "table",
        "query": """
            SELECT
                source_name,
                platform,
                COALESCE(NULLIF(platform_group_name, ''), '(blank)') AS source_group,
                COALESCE(NULLIF(platform_group_id, ''), '(none)') AS source_group_id,
                COUNT(*) AS devices,
                MAX(observed_at) AS last_observed
            FROM ninja_agent_compliance.platform_observations
            WHERE resolved_client_id IS NULL
              AND observed_at > now() - INTERVAL '7 days'
            GROUP BY source_name, platform, source_group, source_group_id
            ORDER BY devices DESC, source_name
            LIMIT 200
        """,
        "row": 48, "col": 0, "size_x": 24, "size_y": 8,
    },
]


def run_bootstrap(url: str, user: str, password: str, db_name: str = "Ninja") -> list[str]:
    with httpx.Client(base_url=url, timeout=60) as client:
        _authenticate(client, user, password)
        db_id = _find_database(client, db_name)
        collection_id = _upsert_collection(client, COLLECTION_NAME)
        existing_cards = _list_cards(client, collection_id)
        card_ids = {
            card["key"]: _upsert_card(client, card, db_id, collection_id, existing_cards)
            for card in CARDS
        }
        dashboard = _upsert_dashboard(client, DASHBOARD_NAME, collection_id)
        _set_layout(client, dashboard, card_ids)
        return [f"{url}/dashboard/{dashboard['id']}  ({DASHBOARD_NAME})"]


def _authenticate(client: httpx.Client, user: str, password: str) -> None:
    resp = client.post("/api/session", json={"username": user, "password": password})
    resp.raise_for_status()
    client.headers["X-Metabase-Session"] = resp.json()["id"]


def _find_database(client: httpx.Client, name: str) -> int:
    resp = client.get("/api/database")
    resp.raise_for_status()
    for db in resp.json().get("data", []):
        if db.get("name") == name:
            return int(db["id"])
    raise RuntimeError(f"Metabase database not found: {name}")


def _upsert_collection(client: httpx.Client, name: str) -> int:
    resp = client.get("/api/collection")
    resp.raise_for_status()
    for collection in resp.json():
        if collection.get("name") == name and not collection.get("archived", False):
            return int(collection["id"])
    resp = client.post("/api/collection", json={"name": name, "color": "#546E7A"})
    resp.raise_for_status()
    return int(resp.json()["id"])


def _list_cards(client: httpx.Client, collection_id: int) -> list[dict[str, Any]]:
    resp = client.get(f"/api/collection/{collection_id}/items", params={"models": "card"})
    resp.raise_for_status()
    payload = resp.json()
    items = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    return [item for item in items if item.get("model") == "card"]


def _uid(key: str) -> str:
    return f"agent-compliance:{key}"


def _upsert_card(
    client: httpx.Client,
    spec: dict[str, Any],
    db_id: int,
    collection_id: int,
    existing_cards: list[dict[str, Any]],
) -> int:
    body = {
        "name": spec["name"],
        "description": _uid(spec["key"]),
        "display": spec["display"],
        "visualization_settings": {},
        "collection_id": collection_id,
        "dataset_query": {
            "type": "native",
            "database": db_id,
            "native": {"query": spec["query"].strip()},
        },
    }
    existing = next((card for card in existing_cards if card.get("description") == _uid(spec["key"])), None)
    if existing:
        card_id = int(existing["id"])
        resp = client.put(f"/api/card/{card_id}", json=body)
        resp.raise_for_status()
        return card_id
    resp = client.post("/api/card", json=body)
    resp.raise_for_status()
    return int(resp.json()["id"])


def _upsert_dashboard(client: httpx.Client, name: str, collection_id: int) -> dict[str, Any]:
    resp = client.get("/api/dashboard")
    resp.raise_for_status()
    for dashboard in resp.json():
        if dashboard.get("name") == name and dashboard.get("collection_id") == collection_id:
            detail = client.get(f"/api/dashboard/{dashboard['id']}")
            detail.raise_for_status()
            return detail.json()
    resp = client.post("/api/dashboard", json={"name": name, "collection_id": collection_id})
    resp.raise_for_status()
    return resp.json()


def _set_layout(client: httpx.Client, dashboard: dict[str, Any], card_ids: dict[str, int]) -> None:
    dashcards = []
    for i, spec in enumerate(CARDS):
        dashcards.append({
            "id": -(i + 1),
            "card_id": card_ids[spec["key"]],
            "row": spec["row"],
            "col": spec["col"],
            "size_x": spec["size_x"],
            "size_y": spec["size_y"],
            "parameter_mappings": [],
            "visualization_settings": {},
        })
    resp = client.put(f"/api/dashboard/{dashboard['id']}", json={"dashcards": dashcards})
    resp.raise_for_status()
