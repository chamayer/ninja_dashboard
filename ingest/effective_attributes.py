"""Bounded orchestration for generic effective attribute projection."""

from __future__ import annotations

import logging
from typing import Any

from ingest import db

log = logging.getLogger(__name__)


def project_all(batch_size: int = 500, max_batches: int = 1000) -> dict[str, Any]:
    """Drain changed entity/attribute keys in separately committed batches."""
    totals: dict[str, Any] = {
        "status": "complete",
        "batches": 0,
        "processed": 0,
        "effective_writes": 0,
        "member_writes": 0,
        "support_writes": 0,
        "conflicts": 0,
        "conflict_support_writes": 0,
    }
    with db.transaction() as cur:
        cur.execute(
            "SELECT to_regprocedure("
            "'operations.sync_entity_attribute_effective(integer)'"
            ") IS NOT NULL"
        )
        if not cur.fetchone()[0]:
            totals["status"] = "migration_pending"
            return totals

    for _ in range(max_batches):
        with db.transaction() as cur:
            cur.execute(
                "SELECT operations.sync_entity_attribute_effective(%s)",
                (batch_size,),
            )
            result = cur.fetchone()[0] or {}
        status = result.get("status", "unknown")
        processed = int(result.get("processed", 0) or 0)
        if status == "busy":
            totals["status"] = "busy"
            break
        if processed == 0:
            totals["status"] = "complete"
            break
        totals["batches"] += 1
        for key in (
            "processed",
            "effective_writes",
            "member_writes",
            "support_writes",
            "conflicts",
            "conflict_support_writes",
        ):
            totals[key] += int(result.get(key, 0) or 0)
    else:
        totals["status"] = "batch_limit"

    log.info("Effective attribute projection: %s", totals)
    return totals
