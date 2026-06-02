"""Activities ingest.

Source: GET /v2/activities
  - Server-side: `sourceName=PATCH_MANAGEMENT,SYSTEM` (settings.activity_sources).
  - Server-side: `after=<last_id>` for incremental pulls.
  - Client-side: drop records whose `activityType` is not in
    settings.activity_types_include (when set).

Target: ninja_activities.activities — insert-once, dedup on Ninja's
stable activity id (PK).

State: ninja_core.ingest_state key='activities.last_id' holds the
high-water mark.

First run: do NOT backfill. Fetch the newest page only to set the
cursor, ingest nothing. Avoids accidentally pulling years of history.
Backfill is a separate one-shot script (TODO.md).
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.config import settings
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log
from ingest.util import ninja_epoch_to_dt

log = logging.getLogger(__name__)

_STATE_KEY = "activities.last_id"
_PAGE_SIZE = 500


def run(client: NinjaClient) -> int:
    """Fetch new activities since the cursor, filter, insert.
    Returns rows inserted (post-filter, post-dedup)."""
    with run_log("activities") as stats:
        last_id_str = _get_last_id()
        sources_csv = ",".join(settings.activity_sources)
        include_types = settings.activity_types_include

        if last_id_str is None:
            return _first_run(client, sources_csv)

        last_id = int(last_id_str)
        params: dict[str, Any] = {"sourceName": sources_csv, "after": last_id}

        rows: list[dict[str, Any]] = []
        max_id = last_id
        total_fetched = 0
        for rec in client.paginate_after(
            "/activities", page_size=_PAGE_SIZE, params=params,
        ):
            total_fetched += 1
            rec_id = rec.get("id")
            if rec_id is None:
                continue
            if rec_id > max_id:
                max_id = rec_id
            if include_types and rec.get("activityType") not in include_types:
                continue
            rows.append(_to_row(rec))

        inserted = 0
        if rows:
            with db.transaction() as cur:
                inserted = db.insert_ignore(
                    cur, "ninja_activities.activities", rows,
                    conflict_keys=["id"],
                )

        if max_id > last_id:
            _set_last_id(max_id)

        stats["rows_inserted"] = inserted
        log.info(
            "activities: fetched %d, allowlisted %d, inserted %d, cursor %d → %d",
            total_fetched, len(rows), inserted, last_id, max_id,
        )
        return inserted


def _first_run(client: NinjaClient, sources_csv: str) -> int:
    """Establish cursor on first run — fetch newest page, take max id,
    ingest nothing."""
    log.info("Activities first run — setting cursor, no backfill")
    resp = client.get("/activities", {
        "sourceName": sources_csv, "pageSize": _PAGE_SIZE,
    })
    records = _records_from_response(resp)
    max_id = max(
        (r["id"] for r in records if isinstance(r.get("id"), int)),
        default=0,
    )
    if max_id > 0:
        _set_last_id(max_id)
    log.info(
        "Cursor set to id=%d (skipped %d records on first run)",
        max_id, len(records),
    )
    return 0


def _records_from_response(resp: Any) -> list[dict]:
    """Tolerate flat-list, {activities: [...]}, or {results: [...]}."""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("activities", "results", "data"):
            if k in resp and isinstance(resp[k], list):
                return resp[k]
    return []


def _to_row(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id":            rec["id"],
        "activity_time": ninja_epoch_to_dt(
            rec.get("activityTime") or rec.get("timestamp"),
        ),
        "device_id":     rec.get("deviceId"),
        "user_id":       rec.get("userId"),
        "source_name":   rec.get("sourceName"),
        "source_type":   rec.get("sourceType"),
        "activity_type": rec.get("activityType"),
        "severity":      rec.get("severity") or rec.get("status"),
        "subject":       rec.get("subject"),
        "message":       rec.get("message"),
        "data":          Json(rec),
    }


def _get_last_id() -> str | None:
    with db.transaction() as cur:
        cur.execute(
            "SELECT value FROM ninja_core.ingest_state WHERE key = %s",
            (_STATE_KEY,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _set_last_id(value: int) -> None:
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO ninja_core.ingest_state (key, value, updated_at) "
            "VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = NOW()",
            (_STATE_KEY, str(value)),
        )
