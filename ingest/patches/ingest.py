"""Patches ingest.

Sources (both paginate_cursor):
  - GET /v2/queries/os-patch-installs   → INSTALLED, FAILED  (events)
  - GET /v2/queries/os-patches          → PENDING, APPROVED, REJECTED  (state)

Both feed ninja_patches.patch_facts; `status` distinguishes the source.

SCD-2: insert new row on content_hash change, otherwise advance
last_observed_at on the existing row. content_hash excludes Ninja's
`timestamp` field (data-collection time) so re-fetches dedupe.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log
from ingest.util import content_hash, ninja_epoch_to_dt

log = logging.getLogger(__name__)


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (rows_changed, rows_observed).
    rows_changed = inserts on hash difference.
    rows_observed = all (device, patch) pairs seen this run."""
    with run_log("patches") as stats:
        rows: list[dict] = []

        for record in client.paginate_cursor("/queries/os-patch-installs"):
            rows.append(_to_row(record, snapshot_at))

        for record in client.paginate_cursor("/queries/os-patches"):
            rows.append(_to_row(record, snapshot_at))

        log.info("Fetched %d patch records (installs + pending)", len(rows))

        with db.transaction() as cur:
            rows_changed = db.upsert(
                cur,
                "ninja_patches.patch_facts",
                rows,
                conflict_keys=["device_id", "patch_uid", "content_hash"],
                # SCD-2: only advance last_observed_at on duplicate hash;
                # first_observed_at is preserved.
                update_cols=["last_observed_at", "ninja_observed_at", "data"],
            )

        stats["rows_inserted"] = rows_changed
        stats["rows_upserted"] = len(rows)
        log.info(
            "patch_facts: %d rows observed, %d inserts/updates",
            len(rows), rows_changed,
        )
        return rows_changed, len(rows)


def _to_row(rec: dict[str, Any], snapshot_at: datetime) -> dict[str, Any]:
    installed_at = ninja_epoch_to_dt(rec.get("installedAt"))
    h = content_hash(
        rec.get("status"),
        installed_at,
        rec.get("severity"),
        rec.get("type"),
        rec.get("kbNumber"),
        rec.get("name"),
    )
    return {
        "device_id":         rec["deviceId"],
        "patch_uid":         rec["id"],
        "kb_number":         rec.get("kbNumber"),
        "name":              rec.get("name"),
        "status":            rec["status"],
        "severity":          rec.get("severity"),
        "type":              rec.get("type"),
        "installed_at":      installed_at,
        "ninja_observed_at": ninja_epoch_to_dt(rec.get("timestamp")),
        "content_hash":      h,
        "first_observed_at": snapshot_at,
        "last_observed_at":  snapshot_at,
        "data":              Json(rec),
    }
