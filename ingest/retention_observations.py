"""Bounded retention for closed observation history versions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ingest import db


def purge(*, tenant_id: int, days: int = 90, batch_size: int = 1000) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    while True:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
            cur.execute(
                """
                DELETE FROM operations.entity_observation_history
                 WHERE id IN (
                     SELECT id
                       FROM operations.entity_observation_history
                      WHERE tenant_id = %s
                        AND effective_to IS NOT NULL
                        AND effective_to < %s
                      ORDER BY effective_to
                      LIMIT %s
                 )
                """,
                (tenant_id, cutoff, batch_size),
            )
            count = cur.rowcount
        deleted += count
        if count < batch_size:
            return deleted
