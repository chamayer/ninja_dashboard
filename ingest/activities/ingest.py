"""Activities ingest.

Source: GET /v2/activities

Pagination model (different from /queries/* endpoints — confirmed via
probe_activities):
  - Response shape: {lastActivityId, activities: [...]}
  - Records returned newest-first.
  - Walk back: `olderThan=<id>` returns records with id < <id>.
  - Walk forward: `after=<id>` / `newer=<id>` / `newerThan=<id>` all
    work; we use `after` for incremental cursor.

Filter:
  - Server-side: `type=<source>` where source ∈ INGEST_ACTIVITY_SOURCES
    (e.g. PATCH_MANAGEMENT, SYSTEM). Despite the field on records being
    `activityType`, the query param is just `type`. Don't ask why.
    `activityType=...` param exists but is silently ignored.
  - Client-side: optional `statusCode` allowlist from
    INGEST_ACTIVITY_TYPES_INCLUDE (these are statusCode values like
    PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED, not "activity types" per se,
    but the env-var name predates this knowledge).

Target: ninja_activities.activities — insert-once, dedup on Ninja's
stable activity id (PK).

State: ninja_core.ingest_state key='activities.last_id' holds the
high-water mark. First run sets the cursor to the latest activity id
without ingesting anything (no backfill).

Walking model: for each source, paginate back from latest using
`olderThan`, processing records until we cross last_id. Then move to
the next source. Cursor updated to MAX(id seen) at the end.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.types.json import Json

from ingest import db
from ingest.config import settings
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log
from ingest.util import ninja_epoch_to_dt
from ingest.inventory.queue import SOFTWARE_ACTIVITY_TYPES, enqueue_activity

log = logging.getLogger(__name__)

_STATE_KEY = "activities.last_id"
_PAGE_SIZE = 500
_MAX_PAGES_PER_SOURCE = 200  # safety cap: 200 * 500 = 100k records / source / run


def run(client: NinjaClient) -> int:
    """Fetch new activities since the cursor. Returns rows inserted.

    Preferred strategy: iterate by `statusCode=<code>` for each entry
    in INGEST_ACTIVITY_TYPES_INCLUDE. Server-side filter returns only
    that exact event type, regardless of which `type` bucket
    (PATCH_MANAGEMENT / MONITOR / SYSTEM / etc.) Ninja files it under.

    Fallback (empty allowlist): iterate by `type=<source>` for each
    entry in INGEST_ACTIVITY_SOURCES, with no client-side filter.
    Less precise, more API cost — set the allowlist instead."""
    with run_log("activities") as stats:
        last_id_str = _get_last_id()
        if last_id_str is None:
            return _first_run(client)
        last_id = int(last_id_str)

        statuscode_allowlist = settings.activity_types_include
        sources = settings.activity_sources
        known_device_ids = _fetch_known_device_ids()
        all_rows: list[dict[str, Any]] = []
        max_id = last_id
        total_fetched = 0

        if statuscode_allowlist:
            log.info(
                "activities: filtering server-side by %d statusCode(s)",
                len(statuscode_allowlist),
            )
            for code in sorted(statuscode_allowlist):
                fetched, max_id = _pull_one(
                    client, {"statusCode": code}, code,
                    last_id, max_id, known_device_ids, all_rows,
                )
                total_fetched += fetched
        elif sources:
            log.warning(
                "INGEST_ACTIVITY_TYPES_INCLUDE not set — falling back to "
                "type-based pull for %d source(s) (less precise)",
                len(sources),
            )
            for source in sources:
                fetched, max_id = _pull_one(
                    client, {"type": source}, source,
                    last_id, max_id, known_device_ids, all_rows,
                )
                total_fetched += fetched
        else:
            log.warning(
                "Neither INGEST_ACTIVITY_TYPES_INCLUDE nor "
                "INGEST_ACTIVITY_SOURCES is set — skipping activities"
            )

        inserted = 0
        if all_rows:
            with db.transaction() as cur:
                inserted = db.insert_ignore(
                    cur, "ninja_activities.activities", all_rows,
                    conflict_keys=["id"],
                )

        if max_id > last_id:
            _set_last_id(max_id)

        if settings.SOFTWARE_QUEUE_ENABLED and all_rows:
            _enqueue_software_activities(all_rows)

        _refresh_activity_summary_views()
        stats["rows_inserted"] = inserted
        log.info(
            "activities: fetched %d total, kept %d, inserted %d, cursor %d → %d",
            total_fetched, len(all_rows), inserted, last_id, max_id,
        )
        return inserted


def _pull_one(
    client: NinjaClient,
    filter_params: dict[str, Any],
    label: str,
    last_id: int,
    max_id: int,
    known_device_ids: set[int],
    out_rows: list[dict],
) -> tuple[int, int]:
    """Walk back from latest with the given server-side filter, until
    we cross last_id. Server-side filter means everything returned is
    kept (no client-side rejection). Returns (fetched, new_max_id)."""
    log.info("Pulling activities for %s (last_id=%d)", label, last_id)
    cursor: int | None = None
    fetched = 0
    kept = 0

    for page_num in range(1, _MAX_PAGES_PER_SOURCE + 1):
        params: dict[str, Any] = {"pageSize": _PAGE_SIZE, **filter_params}
        if cursor is not None:
            params["olderThan"] = cursor

        resp = client.get("/activities", params)
        records = resp.get("activities") or []
        if not records:
            break
        fetched += len(records)

        stop = False
        oldest_seen: int | None = None
        for rec in records:
            rec_id = rec.get("id")
            if rec_id is None:
                continue
            if oldest_seen is None or rec_id < oldest_seen:
                oldest_seen = rec_id
            if rec_id <= last_id:
                stop = True
                break

            out_rows.append(_to_row(rec, known_device_ids))
            kept += 1
            if rec_id > max_id:
                max_id = rec_id

        if stop:
            log.info(
                "  reached last_id (%d), stopping %s — fetched %d, kept %d",
                last_id, label, fetched, kept,
            )
            break

        if cursor is not None and oldest_seen is not None and oldest_seen >= cursor:
            log.warning("  cursor didn't advance for %s, stopping", label)
            break
        cursor = oldest_seen

        if page_num % 10 == 0:
            log.info("  %s: page %d, %d fetched", label, page_num, fetched)
    else:
        log.warning("Hit %d-page cap for %s", _MAX_PAGES_PER_SOURCE, label)

    if fetched > 0:
        log.info("  %s done: fetched %d, kept %d", label, fetched, kept)
    return fetched, max_id


def _first_run(client: NinjaClient) -> int:
    """Establish cursor on first run — fetch the latest activity id
    (any type), store it, ingest nothing. Avoids accidentally pulling
    years of history."""
    log.info("Activities first run — setting cursor, no backfill")
    resp = client.get("/activities", {"pageSize": 1})
    records = resp.get("activities") or []
    if records and isinstance(records[0].get("id"), int):
        latest_id = records[0]["id"]
        _set_last_id(latest_id)
        log.info("Cursor set to id=%d", latest_id)
    else:
        # API returned nothing — leave cursor unset so next run tries again
        log.warning("First run: no activities returned, cursor not set")
    return 0


def _fetch_known_device_ids() -> set[int]:
    """Pre-fetch all device IDs so we can null out activity.device_id
    when the referenced device isn't in our table (PENDING/
    DECOMMISSIONED, or just not-yet-ingested)."""
    with db.transaction() as cur:
        cur.execute("SELECT id FROM ninja_core.devices")
        return {row[0] for row in cur.fetchall()}


def _to_row(rec: dict[str, Any], known_device_ids: set[int]) -> dict[str, Any]:
    """Map a Ninja activity record to our row shape.

    API field        → our column
      id             → id
      activityTime   → activity_time
      deviceId       → device_id        (NULL if device unknown)
      userId         → user_id
      activityType   → source_name      (broad bucket: MONITOR, PATCH_MANAGEMENT, ...)
      type           → source_type      (friendly: "Monitor", "Patch Management", ...)
      statusCode     → activity_type    (specific event code: USER_LOGGED_IN,
                                         PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED, ...)
      status         → subject          (human label: "User Account Logged In")
      message        → message
      (n/a)          → severity         (NULL — Ninja doesn't return severity here)
      whole record   → data jsonb
    """
    dev_id = rec.get("deviceId")
    if dev_id is not None and dev_id not in known_device_ids:
        dev_id = None
    return {
        "id":            rec["id"],
        "activity_time": ninja_epoch_to_dt(rec.get("activityTime")),
        "device_id":     dev_id,
        "user_id":       rec.get("userId"),
        "source_name":   rec.get("activityType"),
        "source_type":   rec.get("type"),
        "activity_type": rec.get("statusCode"),
        "severity":      None,
        "subject":       rec.get("status"),
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


def _enqueue_software_activities(rows: list[dict]) -> None:
    enqueued = 0
    for row in rows:
        if row.get("activity_type") not in SOFTWARE_ACTIVITY_TYPES:
            continue
        ninja_device_id = row.get("device_id")
        if ninja_device_id is None:
            continue
        if enqueue_activity(int(ninja_device_id), reason="ninja.ingest.activity"):
            enqueued += 1
    if enqueued:
        log.info("activities: enqueued %d device(s) to software activity queue", enqueued)


def _refresh_activity_summary_views() -> None:
    views = (
        "ninja_activities.device_activity_signal",
        "ninja_activities.patch_warning_events_recent",
        "ninja_activities.system_reboot_events_recent",
    )
    try:
        with db.transaction() as cur:
            for view_name in views:
                cur.execute(f"REFRESH MATERIALIZED VIEW {view_name}")
        log.info("Refreshed activity summary materialized views")
    except (psycopg.errors.UndefinedTable, psycopg.errors.WrongObjectType):
        log.info(
            "One or more activity summary views are not materialized yet; "
            "skipping refresh"
        )
