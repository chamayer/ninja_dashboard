"""Policies ingest.

Source: GET /v2/policies (no pagination per the OpenAPI spec — plain GET).
Target: ninja_core.policies (upsert on id).
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
    """Fetch all policies and upsert. Returns row count affected."""
    with run_log("core.policies") as stats:
        now = datetime.now(timezone.utc)
        policies = client.get("/policies")
        rows = [
            {
                "id":                    p["id"],
                "parent_policy_id":      p.get("parentPolicyId"),
                "name":                  p["name"],
                "node_class":            p.get("nodeClass"),
                "is_node_class_default": p.get("nodeClassDefault"),
                "data":                  Json(p),
                "updated_at":            now,
            }
            for p in policies
        ]
        log.info("Fetched %d policies", len(rows))
        with db.transaction() as cur:
            count = db.upsert(
                cur,
                "ninja_core.policies",
                rows,
                conflict_keys=["id"],
            )
        stats["rows_upserted"] = count
        log.info("Upserted %d policies", count)
        return count
