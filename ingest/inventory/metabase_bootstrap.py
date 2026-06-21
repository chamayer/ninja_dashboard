"""Provision the Inventory Metabase collection and dashboards."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ingest import db

log = logging.getLogger(__name__)

COLLECTION_NAME = "Inventory"

DASH_OVERVIEW = "Inventory - Overview"
DASH_DEVICES = "Inventory - Devices"
DASH_IDENTITY = "Inventory - Identity Review"
DASH_SERIALS = "Inventory - Serial Quality"
DASH_SOURCES = "Inventory - Source Records"

NAV_ORDER = [DASH_OVERVIEW, DASH_DEVICES, DASH_IDENTITY, DASH_SERIALS, DASH_SOURCES]
NAV_LABELS = {
    DASH_OVERVIEW: "Overview",
    DASH_DEVICES: "Devices",
    DASH_IDENTITY: "Identity",
    DASH_SERIALS: "Serials",
    DASH_SOURCES: "Source Records",
}
NAV_HEIGHT = 2
SECTION_HEADER_HEIGHT = 1

PARAM_CUSTOMER = "p_inv_customer"
PARAM_STATE = "p_inv_state"
PARAM_PLATFORM = "p_inv_platform"
PARAM_SERIAL_QUALITY = "p_inv_serial_quality"

PLATFORM_VALUES = ["Ninja", "SentinelOne", "LogMeIn", "ScreenConnect"]
STATE_VALUES = [
    "Managed",
    "Managed - Stale",
    "Missing Coverage",
    "Review",
    "Unknown",
    "Unmanaged",
    "Ignored",
]
SERIAL_QUALITY_VALUES = ["valid", "missing", "invalid_placeholder", "invalid_short"]


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
    column_widths: dict[str, int] | None = None,
    template_tags: dict[str, dict[str, Any]] | None = None,
    param_mappings: dict[str, list[Any]] | None = None,
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
    if column_widths is not None:
        card["column_widths"] = column_widths
    if template_tags is not None:
        card["template_tags"] = template_tags
    if param_mappings is not None:
        card["param_mappings"] = param_mappings
    return card


def _tag(name: str, display_name: str) -> dict[str, Any]:
    return {
        "id": f"tt_{name}",
        "name": name,
        "display-name": display_name,
        "type": "text",
    }


def _param_multiselect(pid: str, name: str, slug: str, values: list[str]) -> dict[str, Any]:
    return {
        "id": pid,
        "name": name,
        "slug": slug,
        "type": "category",
        "values_query_type": "list",
        "values_source_type": "static-list",
        "values_source_config": {"values": [[v] for v in values]},
        "isMultiSelect": True,
    }


def _mapping(slug: str) -> list[Any]:
    return ["variable", ["template-tag", slug]]


def _fetch_customer_values() -> list[str]:
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT customer_name
                FROM ninja_inventory.v_devices_current
                WHERE COALESCE(NULLIF(customer_name, ''), '') <> ''
                ORDER BY customer_name
                """
            )
            return [row[0] for row in cur.fetchall()]
    except Exception:
        log.exception("Inventory customer parameter lookup failed")
        return []


def _build_inventory_parameters() -> list[dict[str, Any]]:
    return [
        _param_multiselect(PARAM_CUSTOMER, "Customer", "customer", _fetch_customer_values()),
        _param_multiselect(PARAM_STATE, "Inventory state", "state", STATE_VALUES),
        _param_multiselect(PARAM_PLATFORM, "Platform", "platform", PLATFORM_VALUES),
        _param_multiselect(
            PARAM_SERIAL_QUALITY,
            "Serial quality",
            "serial_quality",
            SERIAL_QUALITY_VALUES,
        ),
    ]


_FILTER_TAGS = {
    "customer": _tag("customer", "Customer"),
    "state": _tag("state", "Inventory state"),
    "platform": _tag("platform", "Platform"),
    "serial_quality": _tag("serial_quality", "Serial quality"),
}


def _dashboard_link(target: str, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    return {"target": target, "params": params or []}


def _dashboards() -> list[dict[str, Any]]:
    return [
        {
            "name": DASH_OVERVIEW,
            "cards": [
                _card(
                    "inventory_total_devices",
                    "Resolved devices",
                    "scalar",
                    """
                    SELECT COUNT(*) AS "Resolved devices"
                    FROM ninja_inventory.v_devices_current
                    """,
                    0, 0, 4, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "inventory_managed_devices",
                    "Managed devices",
                    "scalar",
                    """
                    SELECT COUNT(*) AS "Managed devices"
                    FROM ninja_inventory.v_devices_current
                    WHERE inventory_state LIKE 'Managed%'
                    """,
                    0, 4, 4, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "inventory_missing_coverage",
                    "Missing coverage",
                    "scalar",
                    """
                    SELECT COUNT(*) AS "Missing coverage"
                    FROM ninja_inventory.v_devices_current
                    WHERE inventory_state = 'Missing Coverage'
                    """,
                    0, 8, 4, 4,
                    click_behavior=_dashboard_link(DASH_DEVICES),
                ),
                _card(
                    "inventory_unresolved_records",
                    "Unresolved records",
                    "scalar",
                    """
                    SELECT COUNT(*) AS "Unresolved records"
                    FROM ninja_inventory.v_unresolved_source_records_current
                    """,
                    0, 12, 4, 4,
                    click_behavior=_dashboard_link(DASH_SOURCES),
                ),
                _card(
                    "inventory_conflicts",
                    "Identity conflicts",
                    "scalar",
                    """
                    SELECT COUNT(*) AS "Identity conflicts"
                    FROM ninja_inventory.v_identity_conflicts_current
                    """,
                    0, 16, 4, 4,
                    click_behavior=_dashboard_link(DASH_IDENTITY),
                ),
                _card(
                    "inventory_merge_candidates_count",
                    "Merge candidates",
                    "scalar",
                    """
                    SELECT COUNT(*) AS "Merge candidates"
                    FROM ninja_inventory.v_merge_candidates_current
                    """,
                    0, 20, 4, 4,
                    click_behavior=_dashboard_link(DASH_IDENTITY),
                ),
                _card(
                    "inventory_state_summary",
                    "Inventory states",
                    "bar",
                    """
                    SELECT inventory_state AS "State", COUNT(*) AS "Devices"
                    FROM ninja_inventory.v_devices_current
                    GROUP BY inventory_state
                    ORDER BY "Devices" DESC, inventory_state
                    """,
                    4, 0, 12, 8,
                    click_behavior=_dashboard_link(DASH_DEVICES, [("state", "State")]),
                ),
                _card(
                    "inventory_platform_coverage",
                    "Devices by platform",
                    "table",
                    """
                    SELECT platform AS "Platform", COUNT(DISTINCT inventory_device_id) AS "Devices"
                    FROM ninja_inventory.v_devices_current d
                    CROSS JOIN LATERAL unnest(d.present_platforms) AS p(platform)
                    GROUP BY platform
                    ORDER BY "Devices" DESC, platform
                    """,
                    4, 12, 12, 8,
                    click_behavior=_dashboard_link(DASH_DEVICES, [("platform", "Platform")]),
                    column_widths={"Platform": 180, "Devices": 120},
                ),
                _card(
                    "inventory_attention",
                    "Inventory attention",
                    "table",
                    """
                    SELECT
                        'Identity conflicts' AS "Queue",
                        COUNT(*) AS "Rows"
                    FROM ninja_inventory.v_identity_conflicts_current
                    UNION ALL
                    SELECT 'Merge candidates', COUNT(*)
                    FROM ninja_inventory.v_merge_candidates_current
                    UNION ALL
                    SELECT 'Unresolved source records', COUNT(*)
                    FROM ninja_inventory.v_unresolved_source_records_current
                    UNION ALL
                    SELECT 'Missing serials', COUNT(*)
                    FROM ninja_inventory.v_serial_quality_current
                    WHERE serial_quality = 'missing'
                    UNION ALL
                    SELECT 'Invalid serials', COUNT(*)
                    FROM ninja_inventory.v_serial_quality_current
                    WHERE serial_quality LIKE 'invalid%'
                    ORDER BY "Rows" DESC, "Queue"
                    """,
                    12, 0, 24, 6,
                    column_widths={"Queue": 320, "Rows": 120},
                ),
            ],
        },
        {
            "name": DASH_DEVICES,
            "parameters_builder": _build_inventory_parameters,
            "cards": [
                _card(
                    "inventory_devices",
                    "Device inventory (top 500)",
                    "table",
                    """
                    SELECT
                        COUNT(*) OVER() AS "Total matching rows",
                        customer_name AS "Customer",
                        display_name AS "Device",
                        inventory_state AS "Inventory state",
                        compliance_state AS "Compliance",
                        INITCAP(device_type) AS "Type",
                        os_family AS "OS family",
                        COALESCE(array_to_string(serial_numbers, ', '), '-') AS "Serial",
                        COALESCE(array_to_string(present_platforms, ', '), '-') AS "Found in",
                        COALESCE(array_to_string(active_platforms, ', '), '-') AS "Active in",
                        COALESCE(TO_CHAR(inventory_last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Never') AS "Last seen"
                    FROM ninja_inventory.v_devices_current
                    WHERE 1=1
                      [[AND customer_name IN ({{customer}})]]
                      [[AND inventory_state IN ({{state}})]]
                      [[AND EXISTS (
                          SELECT 1
                          FROM unnest(present_platforms) p
                          WHERE p IN ({{platform}})
                      )]]
                    ORDER BY customer_name, display_name
                    LIMIT 500
                    """,
                    0, 0, 24, 14,
                    template_tags={
                        "customer": _FILTER_TAGS["customer"],
                        "state": _FILTER_TAGS["state"],
                        "platform": _FILTER_TAGS["platform"],
                    },
                    param_mappings={
                        PARAM_CUSTOMER: _mapping("customer"),
                        PARAM_STATE: _mapping("state"),
                        PARAM_PLATFORM: _mapping("platform"),
                    },
                    column_widths={
                        "Customer": 260,
                        "Device": 260,
                        "Inventory state": 150,
                        "Compliance": 130,
                        "Serial": 220,
                    },
                ),
                _card(
                    "inventory_devices_by_customer",
                    "Inventory by customer (top 300)",
                    "table",
                    """
                    SELECT
                        COUNT(*) OVER() AS "Total matching rows",
                        customer_name AS "Customer",
                        COUNT(*) AS "Devices",
                        COUNT(*) FILTER (WHERE inventory_state LIKE 'Managed%') AS "Managed",
                        COUNT(*) FILTER (WHERE inventory_state = 'Missing Coverage') AS "Missing coverage",
                        COUNT(*) FILTER (WHERE inventory_state = 'Review') AS "Review",
                        COUNT(*) FILTER (WHERE ignored) AS "Ignored"
                    FROM ninja_inventory.v_devices_current
                    WHERE 1=1
                      [[AND customer_name IN ({{customer}})]]
                    GROUP BY customer_name
                    ORDER BY "Devices" DESC, customer_name
                    LIMIT 300
                    """,
                    14, 0, 24, 8,
                    click_behavior=_dashboard_link(DASH_DEVICES, [("customer", "Customer")]),
                    template_tags={"customer": _FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                    column_widths={"Customer": 280},
                ),
            ],
        },
        {
            "name": DASH_IDENTITY,
            "parameters_builder": _build_inventory_parameters,
            "section_headers": [
                {"row": 0, "text": "### Conflicts"},
                {"row": 12, "text": "### Merge candidates"},
            ],
            "cards": [
                _card(
                    "inventory_identity_conflicts",
                    "Identity conflicts (top 300)",
                    "table",
                    """
                    SELECT
                        COUNT(*) OVER() AS "Total matching rows",
                        conflict_type AS "Conflict",
                        identity_key AS "Key",
                        customer_count AS "Customers",
                        record_count AS "Records",
                        COALESCE(array_to_string(customers, ', '), '-') AS "Customer names",
                        COALESCE(array_to_string(platforms, ', '), '-') AS "Platforms",
                        COALESCE(array_to_string(hostnames, ', '), '-') AS "Devices",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen",
                        reason AS "Reason"
                    FROM ninja_inventory.v_identity_conflicts_current
                    ORDER BY customer_count DESC, record_count DESC, conflict_type, identity_key
                    LIMIT 300
                    """,
                    0, 0, 24, 10,
                    column_widths={
                        "Conflict": 240,
                        "Key": 220,
                        "Customer names": 320,
                        "Devices": 360,
                        "Reason": 420,
                    },
                ),
                _card(
                    "inventory_merge_candidates",
                    "Merge candidates (top 300)",
                    "table",
                    """
                    SELECT
                        COUNT(*) OVER() AS "Total matching rows",
                        customer_name AS "Customer",
                        candidate_type AS "Candidate",
                        match_key AS "Key",
                        platform_count AS "Platforms",
                        norm_count AS "Names",
                        record_count AS "Records",
                        COALESCE(array_to_string(platforms, ', '), '-') AS "Found in",
                        COALESCE(array_to_string(hostnames, ', '), '-') AS "Devices",
                        COALESCE(array_to_string(platform_device_ids, ', '), '-') AS "Platform IDs",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen",
                        reason AS "Reason"
                    FROM ninja_inventory.v_merge_candidates_current
                    WHERE 1=1
                      [[AND customer_name IN ({{customer}})]]
                    ORDER BY customer_name, match_key
                    LIMIT 300
                    """,
                    12, 0, 24, 10,
                    template_tags={"customer": _FILTER_TAGS["customer"]},
                    param_mappings={PARAM_CUSTOMER: _mapping("customer")},
                    column_widths={
                        "Customer": 240,
                        "Key": 220,
                        "Devices": 380,
                        "Platform IDs": 260,
                        "Reason": 360,
                    },
                ),
            ],
        },
        {
            "name": DASH_SERIALS,
            "parameters_builder": _build_inventory_parameters,
            "cards": [
                _card(
                    "inventory_serial_quality_summary",
                    "Serial quality by platform",
                    "table",
                    """
                    SELECT
                        platform AS "Platform",
                        serial_quality AS "Serial quality",
                        COUNT(*) AS "Records",
                        COUNT(DISTINCT COALESCE(customer_name, 'Unresolved')) AS "Customers"
                    FROM ninja_inventory.v_serial_quality_current
                    WHERE 1=1
                      [[AND platform IN ({{platform}})]]
                      [[AND serial_quality IN ({{serial_quality}})]]
                    GROUP BY platform, serial_quality
                    ORDER BY platform, "Records" DESC, serial_quality
                    """,
                    0, 0, 12, 8,
                    template_tags={
                        "platform": _FILTER_TAGS["platform"],
                        "serial_quality": _FILTER_TAGS["serial_quality"],
                    },
                    param_mappings={
                        PARAM_PLATFORM: _mapping("platform"),
                        PARAM_SERIAL_QUALITY: _mapping("serial_quality"),
                    },
                ),
                _card(
                    "inventory_serial_quality_details",
                    "Serial quality details (top 500)",
                    "table",
                    """
                    SELECT
                        COUNT(*) OVER() AS "Total matching rows",
                        platform AS "Platform",
                        customer_name AS "Customer",
                        hostname AS "Device",
                        COALESCE(serial_number, '-') AS "Serial",
                        serial_quality AS "Quality",
                        serial_quality_reason AS "Reason",
                        COALESCE(manufacturer, '-') AS "Manufacturer",
                        COALESCE(model, '-') AS "Model",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen"
                    FROM ninja_inventory.v_serial_quality_current
                    WHERE 1=1
                      [[AND platform IN ({{platform}})]]
                      [[AND customer_name IN ({{customer}})]]
                      [[AND serial_quality IN ({{serial_quality}})]]
                    ORDER BY
                        CASE serial_quality WHEN 'valid' THEN 3 WHEN 'missing' THEN 1 ELSE 0 END,
                        platform,
                        customer_name,
                        hostname
                    LIMIT 500
                    """,
                    0, 12, 12, 12,
                    template_tags={
                        "platform": _FILTER_TAGS["platform"],
                        "customer": _FILTER_TAGS["customer"],
                        "serial_quality": _FILTER_TAGS["serial_quality"],
                    },
                    param_mappings={
                        PARAM_PLATFORM: _mapping("platform"),
                        PARAM_CUSTOMER: _mapping("customer"),
                        PARAM_SERIAL_QUALITY: _mapping("serial_quality"),
                    },
                    column_widths={
                        "Customer": 220,
                        "Device": 260,
                        "Serial": 200,
                        "Reason": 320,
                    },
                ),
            ],
        },
        {
            "name": DASH_SOURCES,
            "parameters_builder": _build_inventory_parameters,
            "cards": [
                _card(
                    "inventory_unresolved_source_records",
                    "Unresolved / excluded source records (top 500)",
                    "table",
                    """
                    SELECT
                        COUNT(*) OVER() AS "Total matching rows",
                        record_state AS "State",
                        platform AS "Platform",
                        source_name AS "Source",
                        COALESCE(platform_customer_name, 'Unknown') AS "Source customer",
                        COALESCE(platform_customer_id, '-') AS "Source customer ID",
                        hostname AS "Device",
                        COALESCE(platform_device_id, '-') AS "Device ID",
                        COALESCE(serial_number, '-') AS "Serial",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen",
                        reason AS "Reason"
                    FROM ninja_inventory.v_unresolved_source_records_current
                    WHERE 1=1
                      [[AND platform IN ({{platform}})]]
                    ORDER BY observed_at DESC, platform, platform_customer_name, hostname
                    LIMIT 500
                    """,
                    0, 0, 24, 10,
                    template_tags={"platform": _FILTER_TAGS["platform"]},
                    param_mappings={PARAM_PLATFORM: _mapping("platform")},
                    column_widths={
                        "State": 190,
                        "Source customer": 260,
                        "Device": 260,
                        "Reason": 420,
                    },
                ),
                _card(
                    "inventory_source_observations",
                    "Current source observations (top 500)",
                    "table",
                    """
                    SELECT
                        COUNT(*) OVER() AS "Total matching rows",
                        platform AS "Platform",
                        source_name AS "Source",
                        COALESCE(customer_name, 'Unresolved') AS "Resolved customer",
                        COALESCE(platform_customer_name, 'Unknown') AS "Source customer",
                        hostname AS "Device",
                        COALESCE(platform_device_id, '-') AS "Device ID",
                        COALESCE(serial_number, '-') AS "Serial",
                        serial_quality AS "Serial quality",
                        COALESCE(TO_CHAR(last_seen_at, 'YYYY-MM-DD HH24:MI'), 'Unknown') AS "Last seen"
                    FROM ninja_inventory.v_source_observations_current
                    WHERE 1=1
                      [[AND platform IN ({{platform}})]]
                      [[AND COALESCE(customer_name, 'Unresolved') IN ({{customer}})]]
                      [[AND serial_quality IN ({{serial_quality}})]]
                    ORDER BY platform, source_name, "Resolved customer", hostname
                    LIMIT 500
                    """,
                    10, 0, 24, 10,
                    template_tags={
                        "platform": _FILTER_TAGS["platform"],
                        "customer": _FILTER_TAGS["customer"],
                        "serial_quality": _FILTER_TAGS["serial_quality"],
                    },
                    param_mappings={
                        PARAM_PLATFORM: _mapping("platform"),
                        PARAM_CUSTOMER: _mapping("customer"),
                        PARAM_SERIAL_QUALITY: _mapping("serial_quality"),
                    },
                    column_widths={
                        "Resolved customer": 240,
                        "Source customer": 240,
                        "Device": 260,
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
        dashboards = _dashboards()

        all_cards = [card for dash in dashboards for card in dash["cards"]]
        card_ids = {
            card["key"]: _upsert_card(client, card, db_id, collection_id, existing_cards)
            for card in all_cards
        }

        dashboard_params: dict[str, list[dict[str, Any]]] = {}
        for dash_spec in dashboards:
            builder = dash_spec.get("parameters_builder")
            if builder is None:
                continue
            dashboard_params[dash_spec["name"]] = builder()

        dash_id_by_name: dict[str, int] = {}
        dash_obj_by_name: dict[str, dict[str, Any]] = {}
        urls: list[str] = []
        for dash_spec in dashboards:
            dashboard = _upsert_dashboard(
                client,
                dash_spec["name"],
                collection_id,
                parameters=dashboard_params.get(dash_spec["name"]),
            )
            dash_id_by_name[dash_spec["name"]] = int(dashboard["id"])
            dash_obj_by_name[dash_spec["name"]] = dashboard
            urls.append(f"dashboard/{dashboard['id']}  ({dash_spec['name']})")

        for dash_spec in dashboards:
            _set_layout(
                client,
                dash_obj_by_name[dash_spec["name"]],
                dash_spec["cards"],
                card_ids,
                nav_markdown=_build_nav_markdown(dash_spec["name"], dash_id_by_name),
                dash_id_by_name=dash_id_by_name,
                section_headers=dash_spec.get("section_headers"),
            )

        card_ids_by_dash = {
            dash_spec["name"]: {card["key"]: card_ids[card["key"]] for card in dash_spec["cards"]}
            for dash_spec in dashboards
        }
        _apply_click_behaviors(client, dashboards, card_ids_by_dash, dash_id_by_name)
        return urls


def _authenticate(client: httpx.Client, user: str, password: str) -> None:
    resp = client.post("/api/session", json={"username": user, "password": password})
    resp.raise_for_status()
    client.headers["X-Metabase-Session"] = resp.json()["id"]


def _find_database(client: httpx.Client, name: str) -> int:
    resp = client.get("/api/database")
    resp.raise_for_status()
    for database in resp.json().get("data", []):
        if database.get("name") == name:
            return int(database["id"])
    raise RuntimeError(f"Metabase database not found: {name}")


def _upsert_collection(client: httpx.Client, name: str) -> int:
    resp = client.get("/api/collection")
    resp.raise_for_status()
    for collection in resp.json():
        if collection.get("name") == name and not collection.get("archived", False):
            return int(collection["id"])
    resp = client.post("/api/collection", json={"name": name, "color": "#00897B"})
    resp.raise_for_status()
    return int(resp.json()["id"])


def _list_cards(client: httpx.Client, collection_id: int) -> list[dict[str, Any]]:
    resp = client.get(f"/api/collection/{collection_id}/items", params={"models": "card"})
    resp.raise_for_status()
    payload = resp.json()
    items = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    return [item for item in items if item.get("model") == "card"]


def _uid(key: str) -> str:
    return f"inventory:{key}"


def _upsert_card(
    client: httpx.Client,
    spec: dict[str, Any],
    db_id: int,
    collection_id: int,
    existing_cards: list[dict[str, Any]],
) -> int:
    native: dict[str, Any] = {"query": spec["query"].strip()}
    if "template_tags" in spec:
        native["template-tags"] = spec["template_tags"]
    body = {
        "name": spec["name"],
        "description": _uid(spec["key"]),
        "display": spec["display"],
        "visualization_settings": {},
        "collection_id": collection_id,
        "dataset_query": {
            "type": "native",
            "database": db_id,
            "native": native,
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


def _upsert_dashboard(
    client: httpx.Client,
    name: str,
    collection_id: int,
    parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resp = client.get("/api/dashboard")
    resp.raise_for_status()
    dashboard = None
    for d in resp.json():
        if d.get("name") == name and d.get("collection_id") == collection_id:
            detail = client.get(f"/api/dashboard/{d['id']}")
            detail.raise_for_status()
            dashboard = detail.json()
            break
    if dashboard is None:
        resp = client.post("/api/dashboard", json={"name": name, "collection_id": collection_id})
        resp.raise_for_status()
        dashboard = resp.json()
    if parameters is not None:
        resp = client.put(f"/api/dashboard/{dashboard['id']}", json={"parameters": parameters})
        resp.raise_for_status()
        dashboard = resp.json()
    return dashboard


def _build_nav_markdown(current_dash_name: str, dash_id_by_name: dict[str, int]) -> str:
    parts: list[str] = []
    for name in NAV_ORDER:
        label = NAV_LABELS.get(name, name)
        if name == current_dash_name:
            parts.append(f"**{label}**")
            continue
        dash_id = dash_id_by_name.get(name)
        if dash_id is not None:
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


def _section_header_dashcard(text: str, row: int, idx: int) -> dict[str, Any]:
    return {
        "id": -(1000 + idx),
        "card_id": None,
        "row": row,
        "col": 0,
        "size_x": 24,
        "size_y": SECTION_HEADER_HEIGHT,
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
    nav_markdown: str,
    dash_id_by_name: dict[str, int],
    section_headers: list[dict[str, Any]] | None = None,
) -> None:
    dashcards = [_nav_dashcard(nav_markdown)]
    headers = sorted(section_headers or [], key=lambda h: h["row"])

    def shift(orig_row: int) -> int:
        return orig_row + sum(
            SECTION_HEADER_HEIGHT for h in headers if h["row"] <= orig_row
        )

    for i, h in enumerate(headers):
        prior = sum(1 for hh in headers if hh["row"] < h["row"])
        dashcards.append(_section_header_dashcard(h["text"], h["row"] + prior + NAV_HEIGHT, i))

    for i, spec in enumerate(specs):
        card_id = card_ids[spec["key"]]
        param_mappings = [
            {"parameter_id": pid, "card_id": card_id, "target": target}
            for pid, target in (spec.get("param_mappings") or {}).items()
        ]
        viz: dict[str, Any] = {}
        column_settings = _build_column_settings(spec, dash_id_by_name)
        if column_settings:
            viz["column_settings"] = column_settings
        dashcards.append({
            "id": -(i + 2),
            "card_id": card_id,
            "row": shift(spec["row"]) + NAV_HEIGHT,
            "col": spec["col"],
            "size_x": spec["size_x"],
            "size_y": spec["size_y"],
            "parameter_mappings": param_mappings,
            "visualization_settings": viz,
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
        for card_spec in dash_spec["cards"]:
            click_spec = card_spec.get("click_behavior")
            column_specs = card_spec.get("column_click_behaviors") or {}
            if not click_spec and not column_specs:
                continue
            card_id = card_ids_by_dash[dash_spec["name"]][card_spec["key"]]
            resp = client.get(f"/api/card/{card_id}")
            resp.raise_for_status()
            current = resp.json().get("visualization_settings") or {}
            if click_spec:
                cb = _build_click_behavior_json(click_spec, dash_id_by_name)
                if cb:
                    current["click_behavior"] = cb
            if column_specs:
                column_settings = dict(current.get("column_settings") or {})
                for col, col_spec in column_specs.items():
                    cb = _build_click_behavior_json(col_spec, dash_id_by_name)
                    if cb:
                        column_settings[f'["name","{col}"]'] = {"click_behavior": cb}
                if column_settings:
                    current["column_settings"] = column_settings
            resp = client.put(f"/api/card/{card_id}", json={"visualization_settings": current})
            resp.raise_for_status()


def _build_column_settings(
    spec: dict[str, Any],
    dash_id_by_name: dict[str, int],
) -> dict[str, dict[str, Any]]:
    column_settings: dict[str, dict[str, Any]] = {}
    for col, width in (spec.get("column_widths") or {}).items():
        column_settings[f'["name","{col}"]'] = {"column_width": int(width)}
    for col, col_spec in (spec.get("column_click_behaviors") or {}).items():
        cb = _build_click_behavior_json(col_spec, dash_id_by_name)
        if cb:
            column_settings.setdefault(f'["name","{col}"]', {})["click_behavior"] = cb
    return column_settings


def _build_click_behavior_json(
    spec: dict[str, Any],
    dash_id_by_name: dict[str, int],
) -> dict[str, Any] | None:
    target = spec.get("target")
    if not target:
        return None
    dash_id = dash_id_by_name.get(target)
    if dash_id is None:
        log.warning("Click behavior: unknown target dashboard %r", target)
        return None
    params = spec.get("params") or []
    if params:
        query = "&".join(f"{key}={{{{{field}}}}}" for key, field in params)
        link = f"/dashboard/{dash_id}?{query}"
    else:
        link = f"/dashboard/{dash_id}"
    return {
        "type": "link",
        "linkType": "url",
        "linkTemplate": link,
    }
