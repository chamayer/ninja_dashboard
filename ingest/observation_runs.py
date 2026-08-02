"""Snapshot-run bookkeeping and complete-snapshot reconciliation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def begin_run(cur: Any, tenant_id: int, source_binding_id: uuid.UUID,
              snapshot_scope: str, snapshot_at: datetime,
              expected_rows: int = 0) -> tuple[uuid.UUID, uuid.UUID]:
    run_id = uuid.uuid4()
    cur.execute(
        """
        INSERT INTO operations.observation_snapshot_runs
          (run_id, tenant_id, source_binding_id, source_instance_id,
           snapshot_scope, snapshot_at, run_started_at, is_complete_snapshot,
           status, expected_rows, written_rows, failed_rows, error)
        SELECT %s, %s, sb.id, sb.source_instance_id, %s, %s, %s, NULL,
               'started', %s, 0, 0, ''
          FROM operations.source_bindings sb
         WHERE sb.id = %s AND sb.tenant_id = %s
        RETURNING source_instance_id
        """,
        (run_id, tenant_id, snapshot_scope, snapshot_at, snapshot_at,
         expected_rows, source_binding_id, tenant_id),
    )
    result = cur.fetchone()
    if result is None:
        raise ValueError("source binding does not belong to the run tenant")
    return run_id, result[0]


def complete_run(cur: Any, run_id: uuid.UUID, written_rows: int,
                 failed_rows: int = 0, error: str = "",
                 *, is_complete_snapshot: bool = True) -> None:
    status = "failed" if failed_rows else "complete"
    complete_snapshot = bool(is_complete_snapshot and not failed_rows)
    cur.execute(
        """
        UPDATE operations.observation_snapshot_runs
           SET status = %s, written_rows = %s, failed_rows = %s,
               error = %s, completed_at = clock_timestamp(),
               is_complete_snapshot = %s
         WHERE run_id = %s
        """,
        (status, written_rows, failed_rows, error[:4000], complete_snapshot, run_id),
    )


def reconcile_complete_run(cur: Any, run_id: uuid.UUID) -> int:
    """Withdraw rows absent from a complete run; returns rows withdrawn."""
    cur.execute(
        """
        UPDATE operations.entity_observation_current c
           SET active = FALSE,
               withdrawn_at = r.snapshot_at,
               last_snapshot_run_id = r.run_id
          FROM operations.observation_snapshot_runs r
         WHERE r.run_id = %s
           AND r.status = 'complete'
           AND c.tenant_id = r.tenant_id
           AND c.source_binding_id = r.source_binding_id
           AND c.snapshot_scope = r.snapshot_scope
           AND c.active = TRUE
           AND (c.last_snapshot_run_id IS DISTINCT FROM r.run_id)
        """,
        (run_id,),
    )
    withdrawn = cur.rowcount
    cur.execute(
        """
        UPDATE operations.entity_observation_history h
           SET effective_to = r.snapshot_at,
               active = FALSE,
               last_seen_at = r.snapshot_at
          FROM operations.observation_snapshot_runs r
          JOIN operations.entity_observation_current c
            ON c.tenant_id = r.tenant_id
           AND c.source_binding_id = r.source_binding_id
           AND c.snapshot_scope = r.snapshot_scope
         WHERE r.run_id = %s
           AND r.status = 'complete'
           AND c.active = FALSE
           AND c.last_snapshot_run_id = r.run_id
           AND h.tenant_id = c.tenant_id
           AND h.source_binding_id = c.source_binding_id
           AND h.entity_type = c.entity_type
           AND h.parent_source_key = c.parent_source_key
           AND h.entity_key = c.entity_key
           AND h.effective_to IS NULL
        """,
        (run_id,),
    )
    return withdrawn
