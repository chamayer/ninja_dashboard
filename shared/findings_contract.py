"""The findings writer contract shared by ingest and Operations (PLAN-003 R2).

Every transaction that writes findings, condition assessments or condition
participants declares ``FINDING_CONTRACT`` and holds the exclusive tenant guard
first; database triggers reject anything else. A process built for another
contract fails at its first findings write instead of writing with stale rules.
"""

from __future__ import annotations

from typing import Any

FINDING_CONTRACT = 4


def guard_findings_writes(cur: Any, tenant_id: int) -> None:
    """Declare the contract and take the exclusive tenant guard on ``cur``.

    Call it first in the transaction, before any statement that locks rows.
    The settings and the guard last until the transaction ends.
    """
    cur.execute(
        "SELECT set_config('operations.tenant_id', %s, true),"
        " set_config('operations.finding_contract', %s, true)",
        (str(tenant_id), str(FINDING_CONTRACT)),
    )
    cur.execute("SELECT operations.acquire_tenant_guard(%s, 'exclusive')", (tenant_id,))
