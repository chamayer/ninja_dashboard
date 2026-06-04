"""Activities backfill — one-shot CLI to walk /v2/activities backward
from the oldest record we already have in Postgres and pull older
history into `ninja_activities.activities`.

The regular hourly ingest only moves forward from the cursor. After
first deploy there's no history; this script fills it in.

Operator runs (inside the ingest container):
    docker exec ninja-ingest python -m ingest.activities.backfill --days 90

Stops at any of:
- An empty page (no more older activities)
- The --days cutoff (defaults to 90)
- The --max-pages cap (defaults to 500 = 250k records max per source)
- An interrupt (Ctrl-C)

Uses the same INGEST_ACTIVITY_TYPES_INCLUDE / INGEST_ACTIVITY_SOURCES
filter the regular ingest uses. Inserts are idempotent — re-running
against rows already present is a no-op (PK on id).

Does NOT touch the high-water mark cursor in
`ninja_core.ingest_state` — that's owned by the forward-ingest.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.config import settings
from ingest.ninja_client import NinjaClient
from ingest.util import ninja_epoch_to_dt

log = logging.getLogger(__name__)

_PAGE_SIZE = 500


_INTERRUPTED = False


def _handle_sigint(signum, frame) -> None:  # noqa: ARG001
    global _INTERRUPTED
    _INTERRUPTED = True
    log.warning("Interrupted — finishing current page and stopping")


def _oldest_id_in_db() -> int | None:
    """Return the smallest activity id currently in
    `ninja_activities.activities`, or None if the table is empty."""
    with db.transaction() as cur:
        cur.execute("SELECT MIN(id) FROM ninja_activities.activities")
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None


def _fetch_known_device_ids() -> set[int]:
    with db.transaction() as cur:
        cur.execute("SELECT id FROM ninja_core.devices")
        return {row[0] for row in cur.fetchall()}


def _to_row(rec: dict[str, Any], known_device_ids: set[int]) -> dict[str, Any]:
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


def _walk_back(
    client: NinjaClient,
    filter_params: dict[str, Any],
    label: str,
    start_id: int,
    cutoff: datetime,
    max_pages: int,
    known_device_ids: set[int],
) -> tuple[int, int]:
    """Walk backward from start_id via olderThan. Insert rows older
    than start_id and newer than cutoff. Returns (fetched, inserted)."""
    log.info(
        "Backfilling %s — older than id=%d, cutoff=%s",
        label, start_id, cutoff.isoformat(),
    )
    cursor: int = start_id
    fetched = 0
    inserted_total = 0
    pages_done = 0

    for page_num in range(1, max_pages + 1):
        if _INTERRUPTED:
            break

        params: dict[str, Any] = {
            "pageSize":  _PAGE_SIZE,
            "olderThan": cursor,
            **filter_params,
        }
        resp = client.get("/activities", params)
        records = resp.get("activities") or []
        if not records:
            log.info("  %s: no more records older than %d", label, cursor)
            break
        fetched += len(records)

        rows: list[dict[str, Any]] = []
        oldest_seen_id: int | None = None
        oldest_seen_time: datetime | None = None
        crossed_cutoff = False

        for rec in records:
            rec_id = rec.get("id")
            if rec_id is None:
                continue
            if oldest_seen_id is None or rec_id < oldest_seen_id:
                oldest_seen_id = rec_id
            act_dt = ninja_epoch_to_dt(rec.get("activityTime"))
            if act_dt is not None:
                if oldest_seen_time is None or act_dt < oldest_seen_time:
                    oldest_seen_time = act_dt
            if act_dt is not None and act_dt < cutoff:
                crossed_cutoff = True
                continue
            rows.append(_to_row(rec, known_device_ids))

        if rows:
            with db.transaction() as cur:
                inserted = db.insert_ignore(
                    cur, "ninja_activities.activities", rows,
                    conflict_keys=["id"],
                )
            inserted_total += inserted

        pages_done = page_num
        if page_num % 5 == 0:
            log.info(
                "  %s: page %d (%d fetched, %d inserted so far; "
                "oldest seen id=%s time=%s)",
                label, page_num, fetched, inserted_total,
                oldest_seen_id,
                oldest_seen_time.isoformat() if oldest_seen_time else "?",
            )

        if crossed_cutoff:
            log.info(
                "  %s: crossed --days cutoff, stopping after page %d",
                label, page_num,
            )
            break
        if oldest_seen_id is None or oldest_seen_id >= cursor:
            log.warning(
                "  %s: cursor didn't advance (oldest=%s, cursor=%d), stopping",
                label, oldest_seen_id, cursor,
            )
            break
        cursor = oldest_seen_id
    else:
        log.warning(
            "  %s: hit --max-pages cap (%d). Re-run to continue.",
            label, max_pages,
        )

    log.info(
        "  %s done: %d pages, %d fetched, %d inserted",
        label, pages_done, fetched, inserted_total,
    )
    return fetched, inserted_total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill historical /v2/activities into Postgres."
    )
    parser.add_argument(
        "--days", type=int, default=90,
        help="Stop after going more than N days back (default: 90).",
    )
    parser.add_argument(
        "--max-pages", type=int, default=500,
        help="Safety cap: max pages per source-filter pass "
             "(default: 500 = 250k records).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGINT, _handle_sigint)

    db.init(settings.postgres_dsn)
    oldest = _oldest_id_in_db()
    if oldest is None:
        log.error(
            "ninja_activities.activities is empty — backfill needs at "
            "least one record as the starting cursor. Run the regular "
            "ingest first."
        )
        return 1
    log.info("Oldest activity id currently in DB: %d", oldest)

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    known_device_ids = _fetch_known_device_ids()
    log.info("Known device ids: %d", len(known_device_ids))

    statuscode_allowlist = settings.activity_types_include
    sources = settings.activity_sources

    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        total_fetched = 0
        total_inserted = 0

        if statuscode_allowlist:
            log.info(
                "Backfilling by %d statusCode(s)", len(statuscode_allowlist)
            )
            for code in sorted(statuscode_allowlist):
                if _INTERRUPTED:
                    break
                f, i = _walk_back(
                    client, {"statusCode": code}, code,
                    oldest, cutoff, args.max_pages, known_device_ids,
                )
                total_fetched += f
                total_inserted += i
        elif sources:
            log.warning(
                "INGEST_ACTIVITY_TYPES_INCLUDE empty — falling back to "
                "type-based backfill for %d source(s)", len(sources),
            )
            for source in sources:
                if _INTERRUPTED:
                    break
                f, i = _walk_back(
                    client, {"type": source}, source,
                    oldest, cutoff, args.max_pages, known_device_ids,
                )
                total_fetched += f
                total_inserted += i
        else:
            log.error(
                "Neither INGEST_ACTIVITY_TYPES_INCLUDE nor "
                "INGEST_ACTIVITY_SOURCES is set — nothing to backfill"
            )
            return 1

    log.info(
        "Backfill complete: fetched %d, inserted %d new rows",
        total_fetched, total_inserted,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
