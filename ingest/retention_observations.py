"""Bounded retention for closed observation history versions.

Delegates to `operations.purge_closed_observation_history(cutoff)`
(migration 0074), a security-definer function that owns the guard:

    DELETE ... WHERE effective_to IS NOT NULL AND effective_to < cutoff

Routing through the function guarantees no caller can accidentally delete
an open SCD-2 version by writing bad SQL — the invariant is textual in the
migration and cannot be reintroduced from Python.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ingest import db

log = logging.getLogger(__name__)


def purge_all(days: int = 90) -> tuple[int, int]:
    """Delete closed history rows older than `days` across all tenants.

    Returns `(generic_deleted, software_deleted)`. The security-definer
    function bypasses RLS by design — retention is a cross-tenant
    maintenance operation.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with db.transaction() as cur:
        cur.execute(
            "SELECT generic_deleted, software_deleted "
            "FROM operations.purge_closed_observation_history(%s)",
            (cutoff,),
        )
        row = cur.fetchone()
    generic = int(row[0] or 0) if row else 0
    software = int(row[1] or 0) if row else 0
    log.info(
        "Observation history retention: generic=%d software=%d "
        "cutoff=%s (%d days)",
        generic, software, cutoff.isoformat(), days,
    )
    return generic, software
