"""Provision the Agent Compliance Metabase collection and dashboards."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

import httpx

from ingest.config import settings

log = logging.getLogger(__name__)
ACTION_BASE_URL = settings.AGENT_COMPLIANCE_ACTION_BASE_URL.rstrip("/")

COLLECTION_NAME = "Agent Compliance"

DASH_COMMAND = "Agent Compliance - Today"
DASH_DEVICES = "Agent Compliance - Devices"
DASH_ORG = "Agent Compliance - Review"
DASH_SOURCE = "Agent Compliance - Health"
DASH_DEBUG = "Agent Compliance - Debug"

NAV_ORDER = [
    DASH_COMMAND,
    DASH_DEVICES,
    DASH_ORG,
    DASH_SOURCE,
    DASH_DEBUG,
]
NAV_DISPLAY_NAMES = {
    DASH_COMMAND: "Today",
    DASH_DEVICES: "Devices",
    DASH_ORG: "Review",
    DASH_SOURCE: "Health",
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
    return card


def _build_click_behavior_json(spec: dict[str, Any], dash_id_by_name: dict[str, int]) -> dict[str, Any] | None:
    target = spec.get("target")
    if not target:
        return None
    target_id = dash_id_by_name.get(target)
    if target_id is None:
        log.warning("Click behavior: unknown target dashboard %r", target)
        return None
    path = f"/dashboard/{target_id}"
    preset = spec.get("preset") or {}
    if preset:
        qs = "&".join(f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in preset.items())
        path = f"{path}?{qs}"
    return {
        "type": "link",
        "linkType": "url",
        "linkTemplate": path,
    }


def _action_url(path: str) -> str:
    return f"{ACTION_BASE_URL}{path}"


DASHBOARDS = [
    {
        "name": DASH_COMMAND,
        "cards": [
            _card(
                "compliance_percent",
                "Compliance %",
                "scalar",
                """
                    SELECT ROUND(
                        COUNT(*) FILTER (WHERE is_compliant) * 100.0 / NULLIF(COUNT(*), 0),
                        1
                    ) AS compliance_percent
                    FROM ninja_agent_compliance.v_compliance_matrix_current
                """,
                0, 0, 4, 4,
                click_behavior={"target": DASH_DEVICES},
            ),
            _card(
                "devices_needing_action",
                "Need Action",
                "scalar",
                """
                    SELECT COUNT(*) AS devices
                    FROM ninja_agent_compliance.v_compliance_matrix_current
                    WHERE NOT is_compliant
                """,
                0, 4, 4, 4,
                click_behavior={"target": DASH_DEVICES},
            ),
            _card(
                "active_findings",
                "Degraded",
                "scalar",
                """
                    SELECT COUNT(*) AS degraded_devices
                    FROM ninja_agent_compliance.v_compliance_matrix_current
                    WHERE is_degraded
                """,
                0, 8, 4, 4,
                click_behavior={"target": DASH_DEVICES},
            ),
            _card(
                "source_issues",
                "Source Down",
                "scalar",
                """
                    SELECT COUNT(*) AS source_issues
                    FROM ninja_agent_compliance.v_source_health_current
                    WHERE enabled AND status = 'failed'
                """,
                0, 12, 4, 4,
                click_behavior={"target": DASH_SOURCE},
            ),
            _card(
                "org_review_queue",
                "Needs Review",
                "scalar",
                """
                    SELECT COUNT(*) AS orgs
                    FROM ninja_agent_compliance.v_alignment_mismatches
                    WHERE overall_status = 'MISMATCH'
                """,
                0, 16, 4, 4,
                click_behavior={"target": DASH_ORG},
            ),
            _card(
                "unresolved_names",
                "New Names",
                "scalar",
                """
                    SELECT COUNT(*) AS unresolved_groups
                    FROM (
                        SELECT
                            source_name,
                            platform,
                            COALESCE(NULLIF(platform_group_name, ''), 'Unknown') AS source_group,
                            COALESCE(NULLIF(platform_group_id, ''), 'Unknown') AS source_group_id
                        FROM ninja_agent_compliance.platform_observations
                        WHERE resolved_client_id IS NULL
                          AND observed_at > now() - INTERVAL '7 days'
                          AND NOT EXISTS (
                                SELECT 1
                                FROM ninja_agent_compliance.org_excludes e
                                WHERE e.enabled
                                  AND lower(trim(COALESCE(platform_group_name, ''))) = e.pattern
                          )
                        GROUP BY source_name, platform, source_group, source_group_id
                    ) unresolved_groups
                """,
                0, 20, 4, 4,
                click_behavior={"target": DASH_ORG},
            ),
        ],
    },
    {
        "name": DASH_DEVICES,
        "cards": [
            _card(
                "remediation_candidates",
                "Need Action",
                "table",
                """
                    SELECT
                        client_name AS "Org",
                        hostname AS "Device",
                        device_type AS "Type",
                        COALESCE(array_to_string(missing_required_platforms, ', '), 'None') AS "Missing",
                        CASE
                            WHEN is_degraded THEN 'Degraded'
                            WHEN is_stale THEN 'Stale'
                            ELSE 'Needs review'
                        END AS "Status",
                        org_align_status AS "Alignment",
                        CASE WHEN s1_exempt THEN 'Yes' ELSE 'No' END AS "S1 exempt",
                        '{ACTION_BASE_URL}/agent-compliance/action/ignore-device?client_hex='
                            || encode(convert_to(client_name, 'UTF8'), 'hex')
                            || '&host_hex='
                            || encode(convert_to(hostname, 'UTF8'), 'hex')
                            || '&confirm=1' AS "Ignore device"
                    FROM ninja_agent_compliance.v_remediation_candidates
                    ORDER BY client_name, hostname
                    LIMIT 500
                """,
                0, 0, 24, 8,
            ),
            _card(
                "degraded_devices",
                "Degraded",
                "table",
                f"""
                    SELECT
                        client_name AS "Org",
                        hostname AS "Device",
                        device_type AS "Type",
                        COALESCE(array_to_string(required_platforms, ', '), 'None') AS "Required",
                        COALESCE(array_to_string(observed_platforms, ', '), 'None') AS "Observed",
                        COALESCE(array_to_string(stale_required_platforms, ', '), 'None') AS "Stale platforms",
                        COALESCE(TO_CHAR(ninja_last_seen, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Ninja last seen",
                        COALESCE(TO_CHAR(sentinelone_last_seen, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "SentinelOne last seen",
                        COALESCE(TO_CHAR(logmein_last_seen, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "LogMeIn last seen",
                        COALESCE(TO_CHAR(screenconnect_last_seen, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "ScreenConnect last seen"
                    FROM ninja_agent_compliance.v_compliance_matrix_current
                    WHERE is_degraded
                    ORDER BY client_name, hostname
                    LIMIT 500
                """,
                0, 8, 24, 8,
            ),
            _card(
                "active_findings_table",
                "Current Issues",
                "table",
                f"""
                    SELECT
                        severity AS "Severity",
                        finding_type AS "Finding",
                        affected_platform AS "Platform",
                        client_name AS "Org",
                        hostname AS "Device",
                        summary AS "Summary",
                        last_seen_at AS "Last seen",
                        '{ACTION_BASE_URL}/agent-compliance/action/ignore-device?client_hex='
                            || encode(convert_to(client_name, 'UTF8'), 'hex')
                            || '&host_hex='
                            || encode(convert_to(hostname, 'UTF8'), 'hex')
                            || '&confirm=1' AS "Ignore device"
                    FROM ninja_agent_compliance.v_active_findings
                    ORDER BY severity DESC, client_name, hostname
                    LIMIT 500
                """,
                0, 16, 24, 10,
            ),
            _card(
                "ignored_devices",
                "Ignored",
                "table",
                f"""
                    SELECT
                        client_name AS "Org",
                        COALESCE(NULLIF(display_name, ''), norm_name) AS "Device",
                        COALESCE(NULLIF(reason, ''), 'Ignored') AS "Reason",
                        COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                        '{ACTION_BASE_URL}/agent-compliance/action/unignore-device?client_hex='
                            || encode(convert_to(client_name, 'UTF8'), 'hex')
                            || '&host_hex='
                            || encode(convert_to(norm_name, 'UTF8'), 'hex')
                            || '&confirm=1' AS "Restore"
                    FROM ninja_agent_compliance.v_device_ignores_current
                    ORDER BY updated_at DESC, client_name, display_name
                    LIMIT 200
                """,
                0, 26, 24, 6,
            ),
        ],
    },
    {
        "name": DASH_ORG,
        "cards": [
            _card(
                "alignment_mismatches",
                "Org Alignment",
                "table",
                f"""
                    SELECT
                        org_name AS "Org",
                        overall_status AS "Status",
                        COALESCE(NULLIF(ninja_platform_name, ''), 'No name') AS "Ninja",
                        COALESCE(NULLIF(s1_platform_name, ''), 'No name') AS "SentinelOne",
                        COALESCE(NULLIF(lmi_platform_name, ''), 'No name') AS "LogMeIn",
                        merged_from AS "Merged from",
                        suggested_config AS "Suggested config",
                        CASE
                            WHEN ninja_status = 'MISSING'
                                 AND COALESCE(NULLIF(ninja_platform_name, ''), '') <> '' THEN
                                '{ACTION_BASE_URL}/agent-compliance/action/add-alias?client_id='
                                || client_id::text
                                || '&platform=Ninja&alias_hex='
                                || encode(convert_to(ninja_platform_name, 'UTF8'), 'hex')
                                || '&confirm=1'
                        END AS "Fix Ninja",
                        CASE
                            WHEN s1_status = 'MISSING'
                                 AND COALESCE(NULLIF(s1_platform_name, ''), '') <> '' THEN
                                '{ACTION_BASE_URL}/agent-compliance/action/add-alias?client_id='
                                || client_id::text
                                || '&platform=SentinelOne&alias_hex='
                                || encode(convert_to(s1_platform_name, 'UTF8'), 'hex')
                                || '&confirm=1'
                        END AS "Fix SentinelOne",
                        CASE
                            WHEN lmi_status = 'MISSING'
                                 AND COALESCE(NULLIF(lmi_platform_name, ''), '') <> '' THEN
                                '{ACTION_BASE_URL}/agent-compliance/action/add-alias?client_id='
                                || client_id::text
                                || '&platform=LogMeIn&alias_hex='
                                || encode(convert_to(lmi_platform_name, 'UTF8'), 'hex')
                                || '&confirm=1'
                        END AS "Fix LogMeIn",
                        '{ACTION_BASE_URL}/agent-compliance/action/exclude-org?pattern_hex='
                            || encode(convert_to(org_name, 'UTF8'), 'hex')
                            || '&confirm=1' AS "Exclude org"
                    FROM ninja_agent_compliance.org_alignment_current
                    WHERE overall_status NOT LIKE 'OK%'
                    ORDER BY org_name
                    LIMIT 500
                """,
                0, 0, 24, 8,
            ),
            _card(
                "unresolved_observations",
                "Unresolved Observations",
                "table",
                f"""
                    SELECT
                        source_name AS "Source",
                        platform AS "Platform",
                        COALESCE(NULLIF(platform_group_name, ''), 'No group name') AS "Group",
                        COALESCE(NULLIF(platform_group_id, ''), 'No group id') AS "Group ID",
                        COUNT(*) AS "Devices",
                        MAX(observed_at) AS "Last seen",
                        MIN(CASE
                            WHEN COALESCE(NULLIF(platform_group_name, ''), '') <> '' THEN
                                '{ACTION_BASE_URL}/agent-compliance/action/exclude-org?pattern_hex='
                                || encode(convert_to(platform_group_name, 'UTF8'), 'hex')
                                || '&confirm=1'
                        END) AS "Exclude org"
                    FROM ninja_agent_compliance.platform_observations
                    WHERE resolved_client_id IS NULL
                      AND observed_at > now() - INTERVAL '7 days'
                      AND NOT EXISTS (
                            SELECT 1
                            FROM ninja_agent_compliance.org_excludes e
                            WHERE e.enabled
                              AND lower(trim(COALESCE(platform_group_name, ''))) = e.pattern
                      )
                    GROUP BY
                        source_name,
                        platform,
                        COALESCE(NULLIF(platform_group_name, ''), 'No group name'),
                        COALESCE(NULLIF(platform_group_id, ''), 'No group id')
                    ORDER BY "Devices" DESC, source_name
                    LIMIT 200
                """,
                0, 8, 24, 8,
            ),
            _card(
                "known_exclusions",
                "Suppressed Names",
                "table",
                f"""
                    SELECT
                        pattern AS "Org",
                        source AS "Source",
                        COALESCE(NULLIF(notes, ''), 'No notes') AS "Notes",
                        COALESCE(TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Updated",
                        CASE
                            WHEN source = 'manual' THEN
                                '{ACTION_BASE_URL}/agent-compliance/action/unexclude-org?pattern_hex='
                                || encode(convert_to(pattern, 'UTF8'), 'hex')
                                || '&confirm=1'
                            ELSE NULL
                        END AS "Restore"
                    FROM ninja_agent_compliance.org_excludes
                    WHERE enabled
                    ORDER BY source, pattern
                    LIMIT 200
                """,
                0, 16, 24, 6,
            ),
            _card(
                "org_candidates",
                "New Names",
                "table",
                """
                    SELECT
                        candidate_name AS "Candidate",
                        platform AS "Platform",
                        observed_count AS "Hits",
                        COALESCE(NULLIF(source_name, ''), 'Unknown') AS "Source",
                        COALESCE(NULLIF(suggested_target, ''), 'Review needed') AS "Suggested target",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen"
                    FROM ninja_agent_compliance.v_org_candidates_current
                    ORDER BY last_seen_at DESC, candidate_name
                    LIMIT 200
                """,
                0, 22, 24, 6,
            ),
        ],
    },
    {
        "name": DASH_SOURCE,
        "cards": [
            _card(
                "missing_by_platform",
                "Missing by Platform",
                "bar",
                """
                    SELECT platform AS "Platform", COUNT(*) AS "Devices"
                    FROM ninja_agent_compliance.v_compliance_matrix_current m
                    CROSS JOIN LATERAL unnest(m.missing_required_platforms) AS platform
                    GROUP BY platform
                    ORDER BY "Devices" DESC
                """,
                0, 0, 12, 8,
            ),
            _card(
                "source_health",
                "Health",
                "table",
                """
                    SELECT
                        platform AS "Platform",
                        source_name AS "Source",
                        COALESCE(NULLIF(client_name, ''), 'Shared') AS "Client",
                        status AS "Status",
                        rows_observed AS "Rows",
                        finished_at AS "Finished",
                        COALESCE(NULLIF(error_text, ''), 'OK') AS "Issue"
                    FROM ninja_agent_compliance.v_source_health_current
                    ORDER BY platform, source_name
                """,
                0, 12, 12, 8,
            ),
        ],
    },
    {
        "name": DASH_DEBUG,
        "cards": [
            _card(
                "raw_observations",
                "Raw Observations",
                "table",
                """
                    SELECT
                        observed_at AS "Observed at",
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
                0, 0, 24, 12,
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

        _set_custom_homepage(client, dash_id_by_name.get(DASH_COMMAND))
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
        label = NAV_DISPLAY_NAMES.get(name, name)
        if name == current_dash_name:
            parts.append(f"**{label}**")
            continue
        dash_id = dash_id_by_name.get(name)
        if dash_id is None:
            continue
        parts.append(f"[{label}](/dashboard/{dash_id})")
    return "**Navigate:** " + " &nbsp;&nbsp;•&nbsp;&nbsp; ".join(parts)


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
            if not click_spec:
                continue
            cb = _build_click_behavior_json(click_spec, dash_id_by_name)
            if not cb:
                continue
            card_id = card_ids_by_dash[current_dash_name][card_spec["key"]]
            r = client.get(f"/api/card/{card_id}")
            r.raise_for_status()
            current = r.json().get("visualization_settings") or {}
            current["click_behavior"] = cb
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
