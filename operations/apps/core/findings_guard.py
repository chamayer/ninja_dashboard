"""Findings writer guard for Operations requests and actions (PLAN-003 R2).

Database triggers reject writes to findings, condition assessments and condition
participants unless the transaction holds the exclusive tenant guard and declares
the findings contract. Call ``guard_findings`` at the start of a handler or action
that writes them, before any statement that locks rows; the guard lasts until the
request transaction ends.
"""

from __future__ import annotations

from django.db import connection
from shared.findings_contract import guard_findings_writes

from apps.core.db.tenant import DEFAULT_TENANT_ID


def guard_findings(tenant_id: int = DEFAULT_TENANT_ID) -> None:
    with connection.cursor() as cursor:
        guard_findings_writes(cursor, tenant_id)
