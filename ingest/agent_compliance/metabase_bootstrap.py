"""Provision the Agent Compliance Metabase collection and dashboards.

This module builds the dashboard surface from scratch around a simple
human workflow:

* Today: what needs attention right now.
* Devices: device-level fixes and ignore/restore.
* Health: source health plus new names that need a decision.
* Debug: raw leftovers and admin-level mapping cleanup.

No visible table field should contain a raw URL. Action cells are plain
labels, and the link target lives in the card visualization settings.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ingest.config import settings

log = logging.getLogger(__name__)

ACTION_BASE_URL = settings.AGENT_COMPLIANCE_ACTION_BASE_URL.rstrip("/")
COLLECTION_NAME = "Agent Compliance"

DASH_TODAY = "Agent Compliance - Today"
DASH_DEVICES = "Agent Compliance - Devices"
DASH_HEALTH = "Agent Compliance - Health"
DASH_DEBUG = "Agent Compliance - Debug"

NAV_ORDER = [DASH_TODAY, DASH_DEVICES, DASH_HEALTH, DASH_DEBUG]
NAV_LABELS = {
    DASH_TODAY: "Today",
    DASH_DEVICES: "Devices",
    DASH_HEALTH: "Health",
    DASH_DEBUG: "Debug",
}
NAV_HEIGHT = 2


def _card(
    key: str,
    name: str,
    display: str,
    query: str,
    row: int,
    col: int,
    size_x: int,
    size_y: int,
    click_behavior: dict[str, Any] | None = None,
    column_click_behaviors: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    card = {
        "key": key,
        "name": name,
        "display": display,
        "query": query,
        "row": row,
        "col": col,
        "size_x": size_x,
        "size_y": size_y,
    }
    if click_behavior is not None:
        card["click_behavior"] = click_behavior
    if column_click_behaviors is not None:
        card["column_click_behaviors"] = column_click_behaviors
    return card


def _dashboard_link(target: str) -> dict[str, Any]:
    return {"target": target}


def _url_template(path: str, params: list[tuple[str, str]]) -> str:
    query = "&".join(f"{key}={{{{{field}}}}}" for key, field in params)
    suffix = f"?{query}&confirm=1" if query else "?confirm=1"
    return f"{ACTION_BASE_URL}{path}{suffix}"


def _build_click_behavior_json(
    spec: dict[str, Any],
    dash_id_by_name: dict[str, int],
) -> dict[str, Any] | None:
    target = spec.get("target")
    if target:
        target_id = dash_id_by_name.get(target)
        if target_id is None:
            log.warning("Click behavior: unknown target dashboard %r", target)
            return None
        return {
            "type": "link",
            "linkType": "url",
            "linkTemplate": f"/dashboard/{target_id}",
        }

    url_template = spec.get("url_template")
    if url_template:
        return {
            "type": "link",
            "linkType": "url",
            "linkTemplate": url_template,
        }
    return None


DASHBOARDS = [
    {
        "name": DASH_TODAY,
        "cards": [
            _card(
                "compliant_percent",
                "Compliant %",
                "scalar",
                """
                    SELECT ROUND(
                        COUNT(*) FILTER (WHERE is_compliant) * 100.0 / NULLIF(COUNT(*), 0),
                        1
                    ) AS "Compliant %"
                    FROM ninja_agent_compliance.v_compliance_matrix_current
                """,
                0, 0, 5, 4,
                click_behavior=_dashboard_link(DASH_DEVICES),
            ),
            _card(
                "devices_to_fix",
                "Devices to fix",
                "scalar",
                """
                    SELECT COUNT(*) AS "Devices to fix"
                    FROM ninja_agent_compliance.v_remediation_candidates
                """,
                0, 5, 5, 4,
                click_behavior=_dashboard_link(DASH_DEVICES),
            ),
            _card(
                "sources_down",
                "Sources down",
                "scalar",
                """
                    SELECT COUNT(*) AS "Sources down"
                    FROM ninja_agent_compliance.v_source_health_current
                    WHERE enabled AND status = 'failed'
                """,
                0, 10, 5, 4,
                click_behavior=_dashboard_link(DASH_HEALTH),
            ),
            _card(
                "names_to_review",
                "Names to review",
                "scalar",
                """
                    SELECT COUNT(*) AS "Names to review"
                    FROM ninja_agent_compliance.v_org_candidates_current
                """,
                0, 15, 5, 4,
                click_behavior=_dashboard_link(DASH_HEALTH),
            ),
            _card(
                "ignored_devices",
                "Ignored devices",
                "scalar",
                """
                    SELECT COUNT(*) AS "Ignored devices"
                    FROM ninja_agent_compliance.v_device_ignores_current
                """,
                0, 20, 4, 4,
                click_behavior=_dashboard_link(DASH_DEVICES),
            ),
        ],
    },
    {
        "name": DASH_DEVICES,
        "cards": [
            _card(
                "device_queue",
                "Need action",
                "table",
                """
                    SELECT
                        client_name AS "Org",
                        hostname AS "Device",
                        device_type AS "Type",
                        COALESCE(array_to_string(missing_required_platforms, ', '), 'None') AS "Need",
                        CASE
                            WHEN is_degraded THEN 'Degraded'
                            WHEN is_stale THEN 'Stale'
                            ELSE 'Review'
                        END AS "State",
                        CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END AS "AV",
                        'Ignore' AS "Action"
                    FROM ninja_agent_compliance.v_remediation_candidates
                    ORDER BY client_name, hostname
                    LIMIT 500
                """,
                0, 0, 24, 10,
                column_click_behaviors={
                    "Action": {
                        "url_template": _url_template(
                            "/a/ig",
                            [("client", "Org"), ("host", "Device")],
                        ),
                    },
                },
            ),
            _card(
                "ignored_devices",
                "Ignored",
                "table",
                """
                    SELECT
                        client_name AS "Org",
                        COALESCE(NULLIF(display_name, ''), norm_name) AS "Device",
                        COALESCE(NULLIF(reason, ''), 'Ignored') AS "Reason",
                        COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                        'Restore' AS "Action"
                    FROM ninja_agent_compliance.v_device_ignores_current
                    ORDER BY updated_at DESC, client_name, display_name
                    LIMIT 200
                """,
                0, 10, 24, 6,
                column_click_behaviors={
                    "Action": {
                        "url_template": _url_template(
                            "/a/ui",
                            [("client", "Org"), ("host", "Device")],
                        ),
                    },
                },
            ),
        ],
    },
    {
        "name": DASH_HEALTH,
        "cards": [
            _card(
                "missing_by_platform",
                "Missing by platform",
                "bar",
                """
                    SELECT
                        platform AS "Platform",
                        COUNT(*) AS "Devices"
                    FROM ninja_agent_compliance.v_compliance_matrix_current m
                    CROSS JOIN LATERAL unnest(m.missing_required_platforms) AS platform
                    GROUP BY platform
                    ORDER BY "Devices" DESC
                """,
                0, 0, 12, 8,
            ),
            _card(
                "source_health",
                "Source health",
                "table",
                """
                    SELECT
                        source_name AS "Source",
                        platform AS "Platform",
                        COALESCE(NULLIF(client_name, ''), 'Shared') AS "Org",
                        status AS "Status",
                        rows_observed AS "Rows",
                        COALESCE(TO_CHAR(finished_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Finished",
                        COALESCE(NULLIF(error_text, ''), 'OK') AS "Issue"
                    FROM ninja_agent_compliance.v_source_health_current
                    ORDER BY platform, source_name
                """,
                0, 12, 12, 8,
            ),
            _card(
                "new_names",
                "New names",
                "table",
                """
                    SELECT
                        candidate_name AS "Name",
                        platform AS "Platform",
                        observed_count AS "Hits",
                        COALESCE(NULLIF(source_name, ''), 'Unknown') AS "Source",
                        COALESCE(NULLIF(suggested_target, ''), 'Review needed') AS "Target",
                        status AS "State",
                        'Skip' AS "Action"
                    FROM ninja_agent_compliance.v_org_candidates_current
                    ORDER BY last_seen_at DESC, candidate_name
                    LIMIT 200
                """,
                0, 20, 24, 8,
                column_click_behaviors={
                    "Action": {
                        "url_template": _url_template(
                            "/a/eo",
                            [("pattern", "Name")],
                        ),
                    },
                },
            ),
        ],
    },
    {
        "name": DASH_DEBUG,
        "cards": [
            _card(
                "raw_observations",
                "Raw observations",
                "table",
                """
                    SELECT
                        observed_at AS "Seen",
                        platform AS "Platform",
                        source_name AS "Source",
                        COALESCE(NULLIF(resolved_client_name, ''), 'Unresolved') AS "Org",
                        hostname AS "Device",
                        COALESCE(NULLIF(platform_group_name, ''), 'Unknown') AS "Group",
                        COALESCE(NULLIF(platform_group_id, ''), 'Unknown') AS "Group ID",
                        raw_data AS "Raw data"
                    FROM ninja_agent_compliance.platform_observations
                    ORDER BY observed_at DESC
                    LIMIT 200
                """,
                0, 0, 24, 10,
            ),
            _card(
                "alignment_leftovers",
                "Alignment leftovers",
                "table",
                """
                    SELECT
                        org_name AS "Name",
                        overall_status AS "State",
                        COALESCE(NULLIF(ninja_platform_name, ''), '') AS "N",
                        COALESCE(NULLIF(s1_platform_name, ''), '') AS "S1",
                        COALESCE(NULLIF(lmi_platform_name, ''), '') AS "LMI",
                        COALESCE(NULLIF(suggested_config, ''), 'No suggestion') AS "Target",
                        CASE WHEN ninja_status = 'MISSING' AND COALESCE(NULLIF(ninja_platform_name, ''), '') <> '' THEN 'Fix N' ELSE '' END AS "Fix N",
                        CASE WHEN s1_status = 'MISSING' AND COALESCE(NULLIF(s1_platform_name, ''), '') <> '' THEN 'Fix S1' ELSE '' END AS "Fix S1",
                        CASE WHEN lmi_status = 'MISSING' AND COALESCE(NULLIF(lmi_platform_name, ''), '') <> '' THEN 'Fix LMI' ELSE '' END AS "Fix LMI",
                        'Skip' AS "Skip"
                    FROM ninja_agent_compliance.v_alignment_mismatches
                    WHERE overall_status NOT LIKE 'OK%'
                    ORDER BY org_name
                    LIMIT 200
                """,
                0, 10, 24, 8,
                column_click_behaviors={
                    "Fix N": {
                        "url_template": _url_template(
                            "/a/aa",
                            [("client_name", "Name"), ("platform", "Ninja"), ("alias", "N")],
                        ),
                    },
                    "Fix S1": {
                        "url_template": _url_template(
                            "/a/aa",
                            [("client_name", "Name"), ("platform", "SentinelOne"), ("alias", "S1")],
                        ),
                    },
                    "Fix LMI": {
                        "url_template": _url_template(
                            "/a/aa",
                            [("client_name", "Name"), ("platform", "LogMeIn"), ("alias", "LMI")],
                        ),
                    },
                    "Skip": {
                        "url_template": _url_template(
                            "/a/eo",
                            [("pattern", "Name")],
                        ),
                    },
                },
            ),
            _card(
                "ignored_names",
                "Ignored names",
                "table",
                """
                    SELECT
                        pattern AS "Name",
                        source AS "Source",
                        COALESCE(NULLIF(notes, ''), 'No notes') AS "Notes",
                        COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                        CASE WHEN source = 'manual' THEN 'Restore' ELSE '' END AS "Action"
                    FROM ninja_agent_compliance.org_excludes
                    WHERE enabled
                    ORDER BY source, pattern
                    LIMIT 200
                """,
                0, 18, 24, 4,
                column_click_behaviors={
                    "Action": {
                        "url_template": _url_template(
                            "/a/ue",
                            [("pattern", "Name")],
                        ),
                    },
                },
            ),
        ],
    },
]


def run_bootstrap(url: str, user: str, password: str, db_name: str = "Ninja") -> list[str]:
    with httpx.Client(base_url=url, timeout=60) as client:
        _authenticate(client, user, password)
        db_id = _find_database(client, db_name)
        collection_id = _upsert_collection(client, COLLECTION_NAME)
        existing_cards = _list_cards(client, collection_id)

        all_cards = [card for dash in DASHBOARDS for card in dash["cards"]]
        card_ids = {
            card["key"]: _upsert_card(client, card, db_id, collection_id, existing_cards)
            for card in all_cards
        }

        dash_id_by_name: dict[str, int] = {}
        dash_obj_by_name: dict[str, dict[str, Any]] = {}
        urls: list[str] = []

        for dash_spec in DASHBOARDS:
            dashboard = _upsert_dashboard(client, dash_spec["name"], collection_id)
            dash_id_by_name[dash_spec["name"]] = int(dashboard["id"])
            dash_obj_by_name[dash_spec["name"]] = dashboard
            urls.append(f"dashboard/{dashboard['id']}  ({dash_spec['name']})")

        for dash_spec in DASHBOARDS:
            nav_md = _build_nav_markdown(dash_spec["name"], dash_id_by_name)
            _set_layout(
                client,
                dash_obj_by_name[dash_spec["name"]],
                dash_spec["cards"],
                card_ids,
                nav_markdown=nav_md,
            )

        card_ids_by_dash = {
            dash_spec["name"]: {card["key"]: card_ids[card["key"]] for card in dash_spec["cards"]}
            for dash_spec in DASHBOARDS
        }
        _apply_click_behaviors(client, DASHBOARDS, card_ids_by_dash, dash_id_by_name)

        _set_custom_homepage(client, dash_id_by_name.get(DASH_TODAY))
        return urls


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


def _build_nav_markdown(current_dash_name: str, dash_id_by_name: dict[str, int]) -> str:
    parts: list[str] = []
    for name in NAV_ORDER:
        label = NAV_LABELS.get(name, name)
        if name == current_dash_name:
            parts.append(f"**{label}**")
            continue
        dash_id = dash_id_by_name.get(name)
        if dash_id is None:
            continue
        parts.append(f"[{label}](/dashboard/{dash_id})")
    return " | ".join(parts)


def _nav_dashcard(text: str) -> dict[str, Any]:
    return {
        "id": -1,
        "card_id": None,
        "row": 0,
        "col": 0,
        "size_x": 24,
        "size_y": NAV_HEIGHT,
        "parameter_mappings": [],
        "visualization_settings": {
            "virtual_card": {
                "display": "text",
                "name": None,
                "archived": False,
                "dataset_query": {},
            },
            "text": text,
        },
    }


def _set_layout(
    client: httpx.Client,
    dashboard: dict[str, Any],
    specs: list[dict[str, Any]],
    card_ids: dict[str, int],
    nav_markdown: str | None = None,
) -> None:
    dashcards = []
    row_offset = NAV_HEIGHT if nav_markdown is not None else 0
    if nav_markdown is not None:
        dashcards.append(_nav_dashcard(nav_markdown))
    for i, spec in enumerate(specs):
        dashcards.append({
            "id": -(i + 2),
            "card_id": card_ids[spec["key"]],
            "row": spec["row"] + row_offset,
            "col": spec["col"],
            "size_x": spec["size_x"],
            "size_y": spec["size_y"],
            "parameter_mappings": [],
            "visualization_settings": {},
        })
    resp = client.put(f"/api/dashboard/{dashboard['id']}", json={"dashcards": dashcards})
    resp.raise_for_status()


def _apply_click_behaviors(
    client: httpx.Client,
    dashboards: list[dict[str, Any]],
    card_ids_by_dash: dict[str, dict[str, int]],
    dash_id_by_name: dict[str, int],
) -> None:
    for dash_spec in dashboards:
        current_dash_name = dash_spec["name"]
        for card_spec in dash_spec["cards"]:
            click_spec = card_spec.get("click_behavior")
            column_specs = card_spec.get("column_click_behaviors") or {}
            if not click_spec and not column_specs:
                continue
            card_id = card_ids_by_dash[current_dash_name][card_spec["key"]]
            r = client.get(f"/api/card/{card_id}")
            r.raise_for_status()
            current = r.json().get("visualization_settings") or {}
            if click_spec:
                cb = _build_click_behavior_json(click_spec, dash_id_by_name)
                if cb:
                    current["click_behavior"] = cb
            if column_specs:
                column_settings: dict[str, dict[str, Any]] = dict(current.get("column_settings") or {})
                for col, col_spec in column_specs.items():
                    cb = _build_click_behavior_json(col_spec, dash_id_by_name)
                    if cb:
                        column_settings[f'["name","{col}"]'] = {"click_behavior": cb}
                if column_settings:
                    current["column_settings"] = column_settings
            r = client.put(
                f"/api/card/{card_id}",
                json={"visualization_settings": current},
            )
            r.raise_for_status()


def _set_custom_homepage(client: httpx.Client, dashboard_id: int | None) -> None:
    if dashboard_id is None:
        log.warning("Custom homepage: dashboard id unknown, skipping")
        return
    for endpoint, payload in (
        ("/api/setting/custom-homepage", {"value": True}),
        ("/api/setting/custom-homepage-dashboard", {"value": dashboard_id}),
    ):
        try:
            resp = client.put(endpoint, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.warning("Custom homepage setting failed for %s: %s", endpoint, exc)
            return
    log.info("Set custom homepage to Agent Compliance today id=%d", dashboard_id)
