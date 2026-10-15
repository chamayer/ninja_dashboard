"""Keep ``findings.attention`` current: the rolled-up state of a finding's assessments.

The rule lives in one SQL function, ``operations.refresh_finding_attention`` (migration
0297). This module only calls it, from ``record_assessment`` right after the assessment
rows are written, so the stored value is exactly as old as the assessment it summarizes.
A database trigger refreshes the findings a status change touches (a parent clearing).
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_CHECK_SECONDS = 60.0
_available: dict[str, Any] = {"at": 0.0, "ok": False, "warned": False}


def function_available(cur: Any) -> bool:
    """Whether migration 0297 has landed (ingest can start before Django migrates)."""
    now = time.monotonic()
    if now - _available["at"] < _CHECK_SECONDS:
        return _available["ok"]
    cur.execute(
        "SELECT to_regprocedure('operations.refresh_finding_attention(uuid[])') IS NOT NULL"
    )
    row = cur.fetchone()
    ok = bool(next(iter(row.values())) if isinstance(row, dict) else row[0])
    _available.update(at=now, ok=ok)
    if not ok and not _available["warned"]:
        _available["warned"] = True
        log.warning("finding attention is not refreshed: migration 0297 has not been applied yet")
    return ok


def refresh(cur: Any, finding_ids: list[str]) -> None:
    """Recompute the stored attention for these entity findings."""
    if finding_ids and function_available(cur):
        cur.execute("SELECT operations.refresh_finding_attention(%s::uuid[])", (finding_ids,))


def check_and_repair(cur: Any, tenant_id: int = 1) -> int:
    """Recompute every active finding's attention, record each disagreement, repair it.

    The stored value is written with every assessment and by a trigger on status changes,
    so a disagreement means one of those paths missed something. Each one is kept in
    ``finding_attention_drift`` (what was stored, what the rule says, when) before it is
    repaired, and logged, so nothing is corrected silently.
    """
    if not function_available(cur):
        return 0
    cur.execute(
        """
        WITH active AS (
            SELECT f.id FROM operations.findings f
             WHERE f.tenant_id = %s AND f.status IN ('open', 'acknowledged', 'investigating')
        ), drift AS (
            SELECT f.id, f.tenant_id, ft.name AS type_name,
                   f.attention AS stored, c.attention AS computed
              FROM operations.compute_finding_attention(ARRAY(SELECT id FROM active)) c
              JOIN operations.findings f ON f.id = c.finding_id
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE f.attention IS DISTINCT FROM c.attention
        ), logged AS (
            INSERT INTO operations.finding_attention_drift
                (tenant_id, finding_id, finding_type, stored_attention, computed_attention)
            SELECT tenant_id, id, type_name, stored, computed FROM drift
            RETURNING finding_id
        )
        SELECT operations.refresh_finding_attention(ARRAY(SELECT finding_id FROM logged)),
               (SELECT count(*) FROM logged)
        """,
        (tenant_id,),
    )
    row = cur.fetchone()
    count = int(row["count"] if isinstance(row, dict) else row[1])
    if count:
        log.warning("finding attention drift: %d finding(s) disagreed with the rule and were repaired", count)
    return count
