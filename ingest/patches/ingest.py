"""Patches ingest.

Two endpoints, two ingest strategies:

  - /v2/queries/os-patch-installs   (INSTALLED, FAILED — EVENTS)
      Incremental via ?installedAfter=<unix_seconds>. Highest
      installed_at we've already stored becomes the next request's
      lower bound. First run pulls everything.

  - /v2/queries/os-patches           (PENDING, APPROVED, REJECTED,
                                      DELAYED, MANUAL — STATE)
      Full pull every run. State can change without an event-style
      timestamp (admin re-approves a REJECTED patch, schedule moves,
      etc.) and the set isn't huge (~50k records).

Both feed ninja_patches.patch_facts; `fact_type` distinguishes state
rows from install-outcome rows.

SCD-2: insert new row on content_hash change, otherwise advance
last_observed_at on the existing row. content_hash excludes Ninja's
`timestamp` field so re-fetches dedupe.

Upserts batch every BATCH_SIZE rows so memory stays bounded and
partial progress is committed if the container is restarted mid-run.
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

        # ── /queries/os-patch-installs : INCREMENTAL ─────────────
        last_installed = _get_last_installed_at()
        installs_params: dict[str, Any] = {}
        if last_installed is not None:
            # Unix seconds. Re-fetched boundary records dedupe via
            # SCD-2 hash, so the exact threshold is safe.
            installs_params["installedAfter"] = int(last_installed.timestamp())
            log.info(
                "os-patch-installs: incremental from %s (installedAfter=%d)",
                last_installed.isoformat(),
                installs_params["installedAfter"],
            )
        else:
            log.info("os-patch-installs: first run (no high-water mark) — full pull")

        installs_count = 0
        batch: list[dict[str, Any]] = []
        for rec in client.paginate_cursor(
            "/queries/os-patch-installs", params=installs_params,
        ):
            batch.append(_to_row(rec, snapshot_at, "install_outcome"))
            total_observed += 1
            installs_count += 1
            if len(batch) >= _BATCH_SIZE:
                total_changed += _flush(batch)
                batch.clear()
        if batch:
            total_changed += _flush(batch)
            batch.clear()
        log.info("os-patch-installs: %d records pulled", installs_count)

        # ── /queries/os-patches : FULL PULL ───────────────────────
        # State endpoint — must walk the whole set each run because a
        # patch's status (PENDING/APPROVED/REJECTED) can flip without
        # a per-record event timestamp we could filter on.
        log.info("os-patches (state): full pull")
        pending_count = 0
        for rec in client.paginate_cursor("/queries/os-patches"):
            batch.append(_to_row(rec, snapshot_at, "patch_state"))
            total_observed += 1
            pending_count += 1
            if len(batch) >= _BATCH_SIZE:
                total_changed += _flush(batch)
                batch.clear()
        if batch:
            total_changed += _flush(batch)
        log.info("os-patches: %d records pulled", pending_count)

        stats["rows_inserted"] = total_changed
        stats["rows_upserted"] = total_observed
        log.info(
            "patch_facts: %d observed (installs %d + state %d), %d inserts/updates",
            total_observed, installs_count, pending_count, total_changed,
        )
        _refresh_summary_views()
        return total_changed, total_observed


def _get_last_installed_at() -> datetime | None:
    """Highest installed_at we've ever stored. None on a fresh DB."""
    with db.transaction() as cur:
        cur.execute(
            "SELECT MAX(installed_at) FROM ninja_patches.patch_facts "
            "WHERE fact_type = 'install_outcome' "
            "AND installed_at IS NOT NULL"
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def _flush(rows: list[dict[str, Any]]) -> int:
    with db.transaction() as cur:
        return db.upsert(
            cur,
            "ninja_patches.patch_facts",
            rows,
            conflict_keys=["device_id", "patch_uid", "content_hash"],
            update_cols=["fact_type", "last_observed_at", "ninja_observed_at", "data"],
        )


def _refresh_summary_views() -> None:
    """Refresh dashboard summary views after patch facts change."""
    with db.transaction() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW ninja_patches.current_patch_state")
        cur.execute("REFRESH MATERIALIZED VIEW ninja_patches.latest_install_outcome")
        cur.execute("REFRESH MATERIALIZED VIEW ninja_patches.device_patch_signal")
    log.info("Refreshed patch summary materialized views")


def _to_row(rec: dict[str, Any], snapshot_at: datetime, fact_type: str) -> dict[str, Any]:
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
        "fact_type":         fact_type,
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
