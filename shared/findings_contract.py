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


def database_findings_contract(cur: Any) -> int | None:
    """The contract the database accepts, or None before it publishes one."""
    cur.execute(
        "SELECT to_regprocedure('operations.finding_contract_version()') IS NOT NULL"
    )
    if not cur.fetchone()[0]:
        return None
    cur.execute("SELECT operations.finding_contract_version()")
    return cur.fetchone()[0]


def declare_findings_contract(cur: Any, tenant_id: int) -> None:
    """Declare the session tenant and contract in the current transaction only."""
    cur.execute(
        "SELECT set_config('operations.tenant_id', %s, true),"
        " set_config('operations.finding_contract', %s, true)",
        (str(tenant_id), str(FINDING_CONTRACT)),
    )


def lock_tenant_session(cur: Any, tenant_id: int) -> None:
    """Hold the exclusive tenant guard for the session, for a later snapshot.

    A repeatable-read writer must not wait for the guard after its snapshot is
    taken, so it takes the guard here in a short transaction first, then opens
    its snapshot transaction. Release it with ``unlock_tenant_session``.
    """
    cur.execute(
        "SELECT pg_advisory_lock(operations.tenant_guard_key(%s))", (tenant_id,)
    )


def unlock_tenant_session(cur: Any, tenant_id: int) -> None:
    cur.execute(
        "SELECT pg_advisory_unlock(operations.tenant_guard_key(%s))", (tenant_id,)
    )
