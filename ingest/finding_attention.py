"""Consistency check for ``operations.finding_state``.

The stored state is written by database triggers in the same transaction as every change that
affects it (migrations 0301, 0302); nothing in Python refreshes it. This module only audits it.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def check_and_repair_state(cur: Any, tenant_id: int = 1) -> int:
    """Recompute every active finding's stored state and compare it with ``finding_state``.

    The state is written in the same transaction as each input change (database triggers,
    migration 0301), so a disagreement means a missed input. Each one is kept in
    ``finding_state_drift`` (what was stored, what the rule says, when) before it is repaired,
    and logged, so nothing is corrected silently. A stored state that is merely older than the
    policy's freshness window is not drift: the page already reads it as pending.
    """
    cur.execute("SELECT to_regprocedure('operations.refresh_finding_state(uuid[])') IS NOT NULL")
    row = cur.fetchone()
    if not bool(next(iter(row.values())) if isinstance(row, dict) else row[0]):
        return 0
    cur.execute(
        """
        WITH active AS (
            SELECT f.id FROM operations.findings f
             WHERE f.tenant_id = %s AND f.status IN ('open', 'acknowledged', 'investigating')
        ), drift AS (
            SELECT c.finding_id, c.tenant_id, ft.name AS type_name,
                   s.attention AS stored, c.attention AS computed
              FROM operations.compute_finding_state(ARRAY(SELECT id FROM active)) c
              JOIN operations.finding_types ft ON ft.id = c.finding_type_id
         LEFT JOIN operations.finding_state s ON s.finding_id = c.finding_id
             WHERE s.attention IS DISTINCT FROM c.attention
                OR s.covered_by IS DISTINCT FROM c.covered_by
        ), logged AS (
            INSERT INTO operations.finding_state_drift
                (tenant_id, finding_id, finding_type, stored_attention, computed_attention)
            SELECT tenant_id, finding_id, type_name, stored, computed FROM drift
            RETURNING finding_id
        )
        SELECT operations.refresh_finding_state(ARRAY(SELECT finding_id FROM logged)),
               (SELECT count(*) FROM logged)
        """,
        (tenant_id,),
    )
    row = cur.fetchone()
    count = int(row["count"] if isinstance(row, dict) else row[1])
    if count:
        log.warning("finding state drift: %d finding(s) disagreed with the rule and were repaired", count)
    return count
