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

Then from the host:
  docker exec -it ninja-ingest python -m ingest.metabase_bootstrap \\
      --user you@example.com --password 'YourMetabasePassword'

Re-runs are safe — find cards/dashboards by name, update vs. create.

Layout uses Metabase's 24-column grid:
  Row 0 (y=0)  : 4 number cards, 6 cols each
  Row 1 (y=4)  : pie (12 cols) + horizontal bar (12 cols)
  Row 2 (y=12) : reboot table (full 24 cols)
  Row 3 (y=20) : run-log table (full 24 cols)
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import httpx

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
            "pie.dimension": "status",
            "pie.metric":    "n",
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
        "key":        "needs_reboot",
        "name":       "Devices Needing Reboot",
        "display":    "table",
        "row": 12, "col": 0, "size_x": 24, "size_y": 8,
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
        "row": 20, "col": 0, "size_x": 24, "size_y": 8,
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
DASHBOARD_NAME  = "Ninja — Overview"


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
    body = {
        "name":                   spec["name"],
        "display":                spec["display"],
        "visualization_settings": spec.get("viz_settings", {}),
        "collection_id":          collection_id,
        "dataset_query": {
            "type":     "native",
            "database": db_id,
            "native":   {"query": spec["query"].strip()},
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
) -> dict[str, Any]:
    r = client.get("/api/dashboard")
    r.raise_for_status()
    for d in r.json():
        if d.get("name") == name and d.get("collection_id") == collection_id:
            r = client.get(f"/api/dashboard/{d['id']}")
            r.raise_for_status()
            log.info("Using existing dashboard: %s (id=%s)", name, d["id"])
            return r.json()
    r = client.post("/api/dashboard", json={
        "name": name, "collection_id": collection_id,
    })
    r.raise_for_status()
    log.info("Created dashboard: %s (id=%d)", name, r.json()["id"])
    return r.json()


def _set_dashboard_layout(
    client: httpx.Client, dashboard: dict, specs: list[dict],
    card_ids: dict[str, int],
) -> None:
    """Replace the dashboard's dashcards with our layout. Uses PUT
    /api/dashboard/:id with a full `dashcards` array — modern
    Metabase replaces dashcards atomically."""
    dashcards = []
    for i, spec in enumerate(specs):
        dashcards.append({
            "id":                     -(i + 1),  # negative = new dashcard
            "card_id":                card_ids[spec["key"]],
            "row":                    spec["row"],
            "col":                    spec["col"],
            "size_x":                 spec["size_x"],
            "size_y":                 spec["size_y"],
            "parameter_mappings":     [],
            "visualization_settings": {},
        })
    r = client.put(
        f"/api/dashboard/{dashboard['id']}",
        json={"dashcards": dashcards},
    )
    r.raise_for_status()
    log.info("Set dashboard layout: %d cards", len(dashcards))


# ── Entry point ─────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the Ninja Overview dashboard in Metabase")
    parser.add_argument("--url", default="http://metabase:3000",
                        help="Metabase base URL (default: http://metabase:3000)")
    parser.add_argument("--user", required=True, help="Metabase admin email")
    parser.add_argument("--password", required=True, help="Metabase admin password")
    parser.add_argument("--db-name", default="Ninja",
                        help="Display name of the Postgres data source in Metabase (default: Ninja)")
    args = parser.parse_args()

    logging.basicConfig(
        level="INFO", format="%(asctime)s %(levelname)s %(message)s",
    )

    with httpx.Client(base_url=args.url, timeout=60) as client:
        _authenticate(client, args.user, args.password)
        db_id = _find_database(client, args.db_name)
        log.info("Using database: %s (id=%d)", args.db_name, db_id)

        col_id = _upsert_collection(client, COLLECTION_NAME)
        existing_cards = _list_cards_in_collection(client, col_id)
        card_ids: dict[str, int] = {}
        for spec in OVERVIEW_CARDS:
            card_ids[spec["key"]] = _upsert_card(
                client, spec, db_id, col_id, existing_cards,
            )

        dashboard = _upsert_dashboard(client, DASHBOARD_NAME, col_id)
        _set_dashboard_layout(client, dashboard, OVERVIEW_CARDS, card_ids)

        print()
        print(f"✓ Dashboard ready: {args.url}/dashboard/{dashboard['id']}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
