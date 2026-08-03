"""Recoverably archive the retired Inventory Metabase surface."""

from __future__ import annotations

from typing import Any

COLLECTION_NAME = "Inventory"
DASHBOARD_NAMES = frozenset(
    {
        "Inventory - Overview",
        "Inventory - Devices",
        "Inventory - Identity Review",
        "Inventory - Serial Quality",
        "Inventory - Source Records",
    }
)


def retire_inventory_metabase(
    url: str,
    user: str,
    password: str,
) -> dict[str, int]:
    """Archive Inventory dashboards, cards, and collection if still active."""
    import httpx

    with httpx.Client(base_url=url, timeout=60) as client:
        _authenticate(client, user, password)
        return _archive_inventory(client)


def _authenticate(client: Any, user: str, password: str) -> None:
    response = client.post(
        "/api/session",
        json={"username": user, "password": password},
    )
    response.raise_for_status()
    client.headers["X-Metabase-Session"] = response.json()["id"]


def _archive_inventory(client: Any) -> dict[str, int]:
    collections_response = client.get("/api/collection")
    collections_response.raise_for_status()
    collections = collections_response.json()
    collection_ids = {
        int(collection["id"])
        for collection in collections
        if collection.get("name") == COLLECTION_NAME
        and not collection.get("archived", False)
    }
    counts = {"dashboards": 0, "cards": 0, "collections": 0}
    if not collection_ids:
        return counts

    dashboards_response = client.get("/api/dashboard")
    dashboards_response.raise_for_status()
    for dashboard in dashboards_response.json():
        if dashboard.get("archived", False):
            continue
        if dashboard.get("name") not in DASHBOARD_NAMES:
            continue
        try:
            collection_id = int(dashboard.get("collection_id"))
        except (TypeError, ValueError):
            continue
        if collection_id not in collection_ids:
            continue
        response = client.put(
            f"/api/dashboard/{int(dashboard['id'])}",
            json={"archived": True},
        )
        response.raise_for_status()
        counts["dashboards"] += 1

    for collection_id in sorted(collection_ids):
        items_response = client.get(f"/api/collection/{collection_id}/items")
        items_response.raise_for_status()
        payload = items_response.json()
        items = payload.get("data", []) if isinstance(payload, dict) else payload
        for item in items:
            if item.get("model") != "card" or item.get("archived", False):
                continue
            response = client.put(
                f"/api/card/{int(item['id'])}",
                json={"archived": True},
            )
            response.raise_for_status()
            counts["cards"] += 1
        response = client.put(
            f"/api/collection/{collection_id}",
            json={"archived": True},
        )
        response.raise_for_status()
        counts["collections"] += 1

    return counts
