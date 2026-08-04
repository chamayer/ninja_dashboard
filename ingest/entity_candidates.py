"""Bounded projection for the generic candidate/event authority."""

from __future__ import annotations

import logging
from typing import Any

from ingest import db

log = logging.getLogger(__name__)


def project_all(batch_size: int = 5000, max_batches: int = 100) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "status": "complete",
        "batches": 0,
        "created": 0,
        "reopened": 0,
        "attached": 0,
    }
    with db.transaction() as cur:
        cur.execute(
            "SELECT to_regprocedure("
            "'operations.sync_entity_candidates(integer)'"
            ") IS NOT NULL"
        )
        if not cur.fetchone()[0]:
            totals["status"] = "migration_pending"
            return totals

    for _ in range(max_batches):
        with db.transaction() as cur:
            cur.execute(
                "SELECT * FROM operations.sync_entity_candidates(%s)",
                (batch_size,),
            )
            created, reopened, attached = cur.fetchone()
        changed = int(created or 0) + int(reopened or 0) + int(attached or 0)
        if changed == 0:
            break
        totals["batches"] += 1
        totals["created"] += int(created or 0)
        totals["reopened"] += int(reopened or 0)
        totals["attached"] += int(attached or 0)
    else:
        totals["status"] = "batch_limit"

    log.info("Generic candidate projection: %s", totals)
    return totals
