"""Patches ingest.

Sources (both paginate_cursor):
  - GET /v2/queries/os-patch-installs   → INSTALLED, FAILED  (events)
  - GET /v2/queries/os-patches          → PENDING, APPROVED, REJECTED  (state)

Both feed ninja_patches.patch_facts; `status` distinguishes the source.

SCD-2: insert new row on content_hash change, otherwise advance
last_observed_at on the existing row. content_hash excludes Ninja's
`timestamp` field (data-collection time) so re-fetches dedupe.

Upserts are batched (BATCH_SIZE rows at a time) so the full hundreds
of thousands of patch rows don't sit in Python memory waiting for a
single end-of-run upsert. Also means partial progress is committed
if the container is restarted mid-run.
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

_BATCH_SIZE = 5000


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (rows_changed, rows_observed)."""
    with run_log("patches") as stats:
        total_observed = 0
        total_changed = 0

        for source_path in ("/queries/os-patch-installs", "/queries/os-patches"):
            batch: list[dict[str, Any]] = []
            for rec in client.paginate_cursor(source_path):
                batch.append(_to_row(rec, snapshot_at))
                total_observed += 1
                if len(batch) >= _BATCH_SIZE:
                    total_changed += _flush(batch)
                    batch.clear()
            if batch:
                total_changed += _flush(batch)
            log.info(
                "%s: complete, total observed so far: %d",
                source_path, total_observed,
            )

        stats["rows_inserted"] = total_changed
        stats["rows_upserted"] = total_observed
        log.info(
            "patch_facts: %d observed, %d inserts/updates",
            total_observed, total_changed,
        )
        return total_changed, total_observed


def _flush(rows: list[dict[str, Any]]) -> int:
    with db.transaction() as cur:
        return db.upsert(
            cur,
            "ninja_patches.patch_facts",
            rows,
            conflict_keys=["device_id", "patch_uid", "content_hash"],
            # SCD-2: only advance last_observed_at on duplicate hash;
            # first_observed_at is preserved.
            update_cols=["last_observed_at", "ninja_observed_at", "data"],
        )


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
