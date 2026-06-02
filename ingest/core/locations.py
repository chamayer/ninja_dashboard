"""Locations ingest.

Source: GET /v2/locations (paginate_after).
Target: ninja_core.locations (upsert on id).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from psycopg.types.json import Json

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log

log = logging.getLogger(__name__)


def run(client: NinjaClient) -> int:
    """Fetch all locations and upsert. Returns row count affected."""
    with run_log("core.locations") as stats:
        now = datetime.now(timezone.utc)
        rows = [
            {
                "id":              loc["id"],
                "organization_id": loc["organizationId"],
                "name":            loc["name"],
                "address":         loc.get("address"),
                "data":            Json(loc),
                "updated_at":      now,
            }
            for loc in client.paginate_after("/locations")
        ]
        log.info("Fetched %d locations", len(rows))
        with db.transaction() as cur:
            count = db.upsert(
                cur,
                "ninja_core.locations",
                rows,
                conflict_keys=["id"],
            )
        stats["rows_upserted"] = count
        log.info("Upserted %d locations", count)
        return count
