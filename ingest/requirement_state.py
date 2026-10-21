"""Consistency check for ``operations.device_requirement_state`` (ADR-0035).

The evaluator's coverage pass writes the verdicts in the transaction that
writes its findings (migration 0332); nothing else writes them. This module
only audits them against the open missing/stale findings.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def check_state(cur: Any, tenant_id: int = 1) -> int:
    """Record every disagreement between verdicts and open findings; return the open count.

    Disagreements are kept in ``device_requirement_state_drift`` until they
    clear. They are not repaired: the evaluator is the authority, so each one
    is a defect to explain, not a value to overwrite.
    """
    cur.execute(
        "SELECT to_regprocedure('operations.check_device_requirement_state(bigint)') IS NOT NULL"
    )
    row = cur.fetchone()
    if not bool(next(iter(row.values())) if isinstance(row, dict) else row[0]):
        return 0
    cur.execute("SELECT operations.check_device_requirement_state(%s)", (tenant_id,))
    row = cur.fetchone()
    count = int(next(iter(row.values())) if isinstance(row, dict) else row[0])
    if count:
        log.warning(
            "requirement state drift: %d open disagreement(s) with findings", count
        )
    return count
