"""Snapshot-run bookkeeping and complete-snapshot reconciliation."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


def begin_run(
    cur: Any,
    tenant_id: int,
    source_binding_id: uuid.UUID,
    snapshot_scope: str,
    snapshot_at: datetime,
    expected_rows: int = 0,
) -> tuple[uuid.UUID, uuid.UUID]:
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
        (
            run_id,
            tenant_id,
            snapshot_scope,
            snapshot_at,
            snapshot_at,
            expected_rows,
            source_binding_id,
            tenant_id,
        ),
    )
    result = cur.fetchone()
    if result is None:
        raise ValueError("source binding does not belong to the run tenant")
    source_instance_id = result[0]
    _lock_snapshot_scope(
        cur,
        tenant_id=tenant_id,
        source_instance_id=source_instance_id,
        snapshot_scope=snapshot_scope,
    )
    return run_id, source_instance_id


def _lock_snapshot_scope(
    cur: Any,
    *,
    tenant_id: int,
    source_instance_id: uuid.UUID,
    snapshot_scope: str,
) -> None:
    """Serialize database application for one authoritative snapshot scope."""
    cur.execute(
        """
        SELECT pg_advisory_xact_lock(
            hashtextextended(%s || '|' || %s || '|' || %s, 0)
        )
        """,
        (str(tenant_id), str(source_instance_id), snapshot_scope),
    )


def observed_identity_summary(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[int, bytes]:
    """Return a collision-free count and deterministic digest without storage.

    The source-native IDs exist in memory already for the current-row write.
    Only the count and SHA-256 digest are retained on the run record.
    """
    identities = {
        (
            str(row["source_instance_id"]),
            str(row["external_namespace"]),
            str(row.get("parent_external_namespace") or ""),
            str(row.get("parent_external_id") or ""),
            str(row["external_id"]),
        )
        for row in rows
    }
    digest = hashlib.sha256()
    for identity in sorted(identities):
        digest.update(
            json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        digest.update(b"\n")
    return len(identities), digest.digest()


def complete_run(
    cur: Any,
    run_id: uuid.UUID,
    written_rows: int,
    failed_rows: int = 0,
    error: str = "",
    *,
    is_complete_snapshot: bool = True,
    identity_rows: Iterable[Mapping[str, Any]] | None = None,
) -> None:
    status = "failed" if failed_rows else "complete"
    complete_snapshot = bool(is_complete_snapshot and not failed_rows)
    if identity_rows is None:
        observed_count, observed_digest = written_rows, None
    else:
        observed_count, observed_digest = observed_identity_summary(identity_rows)
    cur.execute(
        """
        UPDATE operations.observation_snapshot_runs
           SET status = %s, written_rows = %s, failed_rows = %s,
               error = %s, completed_at = clock_timestamp(),
               is_complete_snapshot = %s,
               observed_identity_count = %s,
               observed_identity_digest = %s
         WHERE run_id = %s
        """,
        (
            status,
            written_rows,
            failed_rows,
            error[:4000],
            complete_snapshot,
            observed_count,
            observed_digest,
            run_id,
        ),
    )


def reconcile_complete_run(cur: Any, run_id: uuid.UUID) -> int:
    """Withdraw stale source evidence after one authoritative full snapshot.

    Membership is represented by the run marker on each current row. Evidence
    received at or after this run began wins over this run's absence claim, so
    an older overlapping run cannot withdraw newer evidence.
    """
    cur.execute(
        """
        SELECT tenant_id, source_instance_id, snapshot_scope, run_started_at
          FROM operations.observation_snapshot_runs
         WHERE run_id = %s
           AND status = 'complete'
           AND is_complete_snapshot IS TRUE
           AND source_instance_id IS NOT NULL
           AND run_started_at IS NOT NULL
         FOR UPDATE
        """,
        (run_id,),
    )
    run = cur.fetchone()
    if run is None:
        return 0

    tenant_id, source_instance_id, snapshot_scope, _run_started_at = run
    _lock_snapshot_scope(
        cur,
        tenant_id=tenant_id,
        source_instance_id=source_instance_id,
        snapshot_scope=snapshot_scope,
    )
    cur.execute(
        """
        WITH deciding_run AS (
            SELECT run_id, tenant_id, source_instance_id, snapshot_scope,
                   snapshot_at, run_started_at
              FROM operations.observation_snapshot_runs
             WHERE run_id = %s
               AND status = 'complete'
               AND is_complete_snapshot IS TRUE
        ),
        withdrawn AS (
            UPDATE operations.entity_observation_current c
               SET active = FALSE,
                   withdrawn_at = r.snapshot_at,
                   last_snapshot_run_id = r.run_id
              FROM deciding_run r
             WHERE c.tenant_id = r.tenant_id
               AND c.source_instance_id = r.source_instance_id
               AND c.snapshot_scope = r.snapshot_scope
               AND c.active = TRUE
               AND c.last_snapshot_run_id IS DISTINCT FROM r.run_id
               AND c.last_received_at < r.run_started_at
            RETURNING c.tenant_id, c.source_instance_id,
                      c.external_namespace, c.parent_external_namespace,
                      c.parent_external_id, c.external_id, c.last_seen_at,
                      r.snapshot_at, r.run_id
        ),
        closed AS (
            UPDATE operations.entity_observation_history h
               SET effective_to = w.snapshot_at,
                   last_seen_at = w.last_seen_at,
                   closed_by_snapshot_run_id = w.run_id
              FROM withdrawn w
             WHERE h.tenant_id = w.tenant_id
               AND h.source_instance_id = w.source_instance_id
               AND h.external_namespace = w.external_namespace
               AND h.parent_external_namespace = w.parent_external_namespace
               AND h.parent_external_id = w.parent_external_id
               AND h.external_id = w.external_id
               AND h.effective_to IS NULL
            RETURNING h.id
        )
        SELECT (SELECT COUNT(*) FROM withdrawn),
               (SELECT COUNT(*) FROM closed)
        """,
        (run_id,),
    )
    withdrawn, closed = cur.fetchone()
    if withdrawn != closed:
        raise RuntimeError(
            "complete-run reconciliation found current/history mismatch: "
            f"withdrawn={withdrawn}, closed={closed}"
        )
    return withdrawn
