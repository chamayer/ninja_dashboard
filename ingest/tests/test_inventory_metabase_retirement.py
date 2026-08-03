from ingest.inventory.metabase_retirement import DASHBOARD_NAMES, _archive_inventory


class _Response:
    def __init__(self, payload=None):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, *, collections, dashboards, items=None):
        self.collections = collections
        self.dashboards = dashboards
        self.items = items or {}
        self.puts = []

    def get(self, path):
        if path == "/api/collection":
            return _Response(self.collections)
        if path == "/api/dashboard":
            return _Response(self.dashboards)
        collection_id = int(path.split("/")[3])
        return _Response(self.items.get(collection_id, []))

    def put(self, path, json):
        self.puts.append((path, json))
        return _Response({})


def test_archive_inventory_is_scoped_to_active_inventory_collection():
    inventory_dashboards = [
        {
            "id": dashboard_id,
            "name": name,
            "collection_id": "10",
            "archived": False,
        }
        for dashboard_id, name in enumerate(sorted(DASHBOARD_NAMES), start=1)
    ]
    client = _Client(
        collections=[
            {"id": 10, "name": "Inventory", "archived": False},
            {"id": 20, "name": "Other", "archived": False},
        ],
        dashboards=inventory_dashboards + [
            {
                "id": 10,
                "name": "Inventory - Overview",
                "collection_id": 10,
                "archived": True,
            },
            {
                "id": 11,
                "name": "Unrelated",
                "collection_id": 10,
                "archived": False,
            },
            {
                "id": 12,
                "name": "Inventory - Overview",
                "collection_id": 20,
                "archived": False,
            },
        ],
        items={
            10: {
                "data": [
                    {"id": 101, "model": "card", "archived": False},
                    {"id": 102, "model": "card", "archived": True},
                    {"id": 103, "model": "dashboard", "archived": False},
                ]
            }
        },
    )

    assert _archive_inventory(client) == {
        "dashboards": 5,
        "cards": 1,
        "collections": 1,
    }
    assert client.puts == [
        *[
            (f"/api/dashboard/{dashboard_id}", {"archived": True})
            for dashboard_id in range(1, 6)
        ],
        ("/api/card/101", {"archived": True}),
        ("/api/collection/10", {"archived": True}),
    ]


def test_archive_inventory_is_noop_without_active_collection():
    client = _Client(
        collections=[{"id": 10, "name": "Inventory", "archived": True}],
        dashboards=[],
    )

    assert _archive_inventory(client) == {
        "dashboards": 0,
        "cards": 0,
        "collections": 0,
    }
    assert client.puts == []
