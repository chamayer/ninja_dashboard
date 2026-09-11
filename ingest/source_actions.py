"""Worker for explicit, source-side actions requested in Operations.

Only ingest resolves source credentials.  Operations can enqueue an exact
target, but never performs an external mutation itself.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.connectors.hudu import archive_asset
from ingest.sources import SourceConfig, load_sources

log = logging.getLogger(__name__)

_TABLE = "operations.source_action_requests"
_ACTION_ARCHIVE_HUDU = "archive_hudu_asset"
_LEASE_MINUTES = 5


def process_pending(*, limit: int = 10) -> dict[str, int]:
    """Process a small leased batch and refresh Hudu evidence after success."""
    recover_stale()
    completed = failed = cancelled = 0
    refresh_source: SourceConfig | None = None
    for _ in range(limit):
        request_row = _claim_next()
        if request_row is None:
            break
        status, source = _process_one(request_row)
        if status == "completed":
            completed += 1
            refresh_source = source or refresh_source
        elif status == "cancelled":
            cancelled += 1
        else:
            failed += 1
    if refresh_source is not None:
        _refresh_hudu_evidence(refresh_source)
    return {"completed": completed, "failed": failed, "cancelled": cancelled}


def _claim_next() -> dict[str, Any] | None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            WITH candidate AS (
                SELECT id
                  FROM {_TABLE}
                 WHERE tenant_id = 1 AND status = 'pending'
                 ORDER BY queued_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE {_TABLE} request
               SET status = 'processing', started_at = NOW(),
                   lease_expires_at = NOW() + INTERVAL '{_LEASE_MINUTES} minutes',
                   attempts = attempts + 1
              FROM candidate
             WHERE request.id = candidate.id
            RETURNING request.id, request.finding_id, request.source_instance_id,
                      request.action_key, request.parent_external_id, request.external_id
            """
        )
        row = cur.fetchone()
    if row is None:
        return None
    keys = ("id", "finding_id", "source_instance_id", "action_key", "company_id", "asset_id")
    return dict(zip(keys, row))


def _process_one(request_row: dict[str, Any]) -> tuple[str, SourceConfig | None]:
    action_key = request_row["action_key"]
    if action_key != _ACTION_ARCHIVE_HUDU:
        _finish(request_row["id"], "failed", error=f"Unsupported source action: {action_key}")
        return "failed", None

    source = next(
        (
            configured
            for configured in load_sources()
            if str(configured.source_instance_id) == str(request_row["source_instance_id"])
            and configured.platform == "Hudu"
        ),
        None,
    )
    if source is None:
        _finish(request_row["id"], "failed", error="Configured Hudu source is unavailable")
        return "failed", None
    if not _still_eligible(request_row):
        _finish(request_row["id"], "cancelled", error="Target no longer meets the archive rule")
        return "cancelled", source

    try:
        status_code = archive_asset(
            source,
            company_id=request_row["company_id"],
            asset_id=request_row["asset_id"],
        )
    except Exception as exc:
        log.exception("source action %s failed", request_row["id"])
        _finish(request_row["id"], "failed", error=str(exc)[:2000])
        return "failed", source
    _finish(
        request_row["id"],
        "completed",
        outcome={"source": "Hudu", "action": "archived", "http_status": status_code},
    )
    return "completed", source


def _still_eligible(request_row: dict[str, Any]) -> bool:
    """Require the same current Hudu evidence that emitted the finding."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM operations.entity_observation_current eo
                  JOIN operations.source_instances si ON si.id = eo.source_instance_id
                  JOIN operations.sources s ON s.id = si.source_id
                 WHERE eo.tenant_id = 1
                   AND eo.source_instance_id = %s
                   AND COALESCE(eo.raw_data->>'company_id', '') = %s
                   AND eo.external_id = %s
                   AND eo.active
                   AND s.name = 'Hudu'
                   AND eo.entity_type = 'cmdb.asset'
                   AND eo.canonical_data->>'link_verdict' = 'stale'
                   AND COALESCE((eo.canonical_data->>'archived')::boolean, FALSE) IS FALSE
            )
            """,
            (request_row["source_instance_id"], request_row["company_id"], request_row["asset_id"]),
        )
        return bool(cur.fetchone()[0])


def _finish(
    request_id: int,
    status: str,
    *,
    outcome: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    with db.transaction() as cur:
        cur.execute(
            f"""
            UPDATE {_TABLE}
               SET status = %s, completed_at = NOW(), lease_expires_at = NULL,
                   outcome = %s, error = %s
             WHERE id = %s
            """,
            (status, Json(outcome or {}), error, request_id),
        )


def recover_stale() -> int:
    """Fail closed after a lost worker lease; never repeat a source mutation."""
    with db.transaction() as cur:
        cur.execute(
            f"""
            UPDATE {_TABLE}
               SET status = 'failed', completed_at = NOW(),
                   error = 'worker lease expired; verify the source before requeueing'
             WHERE status = 'processing' AND lease_expires_at < NOW()
            """
        )
        return cur.rowcount


def _refresh_hudu_evidence(source: SourceConfig) -> None:
    """Let normal collection prove the Hudu result and resolve the finding."""
    try:
        from ingest import cmdb_findings
        from ingest.source_observations import run_source_observations

        run_source_observations([source], datetime.now(timezone.utc))
        cmdb_findings.evaluate(dry_run=False)
    except Exception:
        # The source action outcome is still retained; a later scheduled Hudu
        # run will reconcile the evidence and candidate finding.
        log.exception("Hudu refresh after source actions failed")
