"""Organizations ingest.

Source: GET /v2/organizations (paginate_after).
Target: ninja_core.organizations (upsert on id).
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
    """Fetch all organizations and upsert. Returns row count affected."""
    with run_log("core.organizations") as stats:
        now = datetime.now(timezone.utc)
        rows = [
            {
                "id":                 org["id"],
                "name":               org["name"],
                "description":        org.get("description"),
                "node_approval_mode": org.get("nodeApprovalMode"),
                "data":               Json(org),
                "updated_at":         now,
            }
            for org in client.paginate_after("/organizations")
        ]
        log.info("Fetched %d organizations", len(rows))
        with db.transaction() as cur:
            count = db.upsert(
                cur,
                "ninja_core.organizations",
                rows,
                conflict_keys=["id"],
            )
        stats["rows_upserted"] = count
        log.info("Upserted %d organizations", count)
        return count
