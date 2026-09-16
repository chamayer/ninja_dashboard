"""Measured source-evidence predicates used by condition producers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from shared.conditions.contracts import Participant, Readiness, Signal


def complete_snapshot_available(
    cur: Any,
    tenant_id: int,
    source_instance_id: str,
    *,
    source_binding_id: str | None = None,
    snapshot_scope: str | None = None,
    now: datetime,
) -> bool:
    """Return true only for a complete, internally consistent current run."""
    scope_clause = "AND snapshot_scope = %s" if snapshot_scope else ""
    binding_clause = "AND source_binding_id = %s" if source_binding_id else ""
    params = [tenant_id, source_instance_id]
    if source_binding_id:
        params.append(source_binding_id)
    if snapshot_scope:
        params.append(snapshot_scope)
    cur.execute(
        f"""
        SELECT status, is_complete_snapshot, expected_rows, written_rows,
               failed_rows, run_started_at, completed_at
         FROM operations.observation_snapshot_runs
         WHERE tenant_id = %s AND source_instance_id = %s
           {binding_clause}
           {scope_clause}
         ORDER BY completed_at DESC NULLS LAST, run_started_at DESC
         LIMIT 1
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return False
    status, complete, expected, written, failed, started, completed = row
    return bool(
        status == "complete"
        and complete is True
        and failed == 0
        and expected == written
        and started is not None
        and completed is not None
        and started <= completed <= now
    )


def device_identity_signals(cur: Any, tenant_id: int, device_ids: list[str]) -> dict[str, Signal]:
    """Batch-load identity readiness; absence is unknown, never ready."""
    if not device_ids:
        return {}
    cur.execute(
        """
        SELECT d.id, d.entity_id IS NOT NULL AND d.client_id IS NOT NULL,
               EXISTS (SELECT 1 FROM operations.findings f
                 JOIN operations.finding_types ft ON ft.id = f.finding_type_id
                WHERE f.tenant_id = d.tenant_id AND f.subject_id = d.id
                  AND ft.name = 'identity_conflict'
                  AND f.status IN ('open','acknowledged','investigating','suppressed'))
          FROM operations.devices d
         WHERE d.tenant_id = %s AND d.id = ANY(%s::uuid[]) AND d.deleted_at IS NULL
        """,
        (tenant_id, device_ids),
    )
    result = {}
    for device_id, attached, conflicted in cur.fetchall():
        participant = Participant("device", str(device_id), "affected", tenant_id)
        result[str(device_id)] = Signal(
            "identity", participant,
            Readiness.BLOCKED if conflicted else Readiness.READY if attached else Readiness.UNKNOWN,
            "identity:unsettled_group" if conflicted else "identity:stable_attachment" if attached
            else "identity:readiness_not_measured",
        )
    return result


def offline_readiness(
    contacts: list[datetime | None], *, now: datetime, offline_days: int,
    retired: bool = False, withdrawn: bool = False,
) -> tuple[Readiness, str]:
    """Classify agent contact evidence without trusting a source online flag."""
    if retired:
        return Readiness.UNKNOWN, "offline:retired"
    if withdrawn:
        return Readiness.UNKNOWN, "offline:withdrawn"
    if any(contact is not None and contact > now for contact in contacts):
        return Readiness.UNKNOWN, "offline:future_contact"
    valid = [contact for contact in contacts if contact is not None]
    if not valid:
        return Readiness.UNKNOWN, "offline:contact_not_measured"
    latest = max(valid)
    if latest < now - timedelta(days=offline_days):
        return Readiness.BLOCKED, "offline:extended_absence"
    return Readiness.READY, "offline:recent_contact"


def successful_run_available(
    cur: Any, tenant_id: int, kind: str, *, now: datetime, max_age_hours: int = 24
) -> bool:
    """Require a completed successful non-snapshot run within its freshness window."""
    cur.execute(
        """
        SELECT 1 FROM operations.run_log
         WHERE tenant_id = %s AND kind = %s AND ok IS TRUE
           AND ended_at IS NOT NULL AND ended_at <= %s
           AND ended_at >= %s - (%s * interval '1 hour')
         ORDER BY ended_at DESC LIMIT 1
        """,
        (tenant_id, kind, now, now, max_age_hours),
    )
    return cur.fetchone() is not None


def preserve_operator_episode(
    cur: Any, table: str, tenant_id: int, condition_key: str, now: datetime,
    details: dict[str, Any],
) -> str | None:
    """Refresh an operator-managed episode instead of creating a duplicate."""
    if table not in {"findings", "admin_findings"}:
        raise ValueError("Unsupported condition table")
    details_column = "finding_details" if table == "findings" else "details"
    timestamps = "last_seen_at = %s, last_detected_at = %s" if table == "findings" else "last_detected_at = %s"
    timestamp_values = (now, now) if table == "findings" else (now,)
    cur.execute(
        f"""
        UPDATE operations.{table}
           SET {details_column} = %s::jsonb,
               {timestamps}
         WHERE tenant_id = %s AND condition_key = %s
           AND status IN ('investigating', 'suppressed')
        RETURNING id
        """,
        (json.dumps(details), *timestamp_values, tenant_id, condition_key),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def device_identity_signal(
    cur: Any,
    tenant_id: int,
    device_id: str,
    *,
    participant_role: str = "affected",
) -> Signal:
    """Measure stable device attachment and unresolved identity conflicts."""
    participant = Participant("device", str(device_id), participant_role, tenant_id)
    cur.execute(
        """
        SELECT d.entity_id IS NOT NULL AND d.client_id IS NOT NULL,
               EXISTS (
                   SELECT 1
                     FROM operations.findings conflict
                     JOIN operations.finding_types conflict_type
                       ON conflict_type.id = conflict.finding_type_id
                    WHERE conflict.tenant_id = d.tenant_id
                      AND conflict.subject_id = d.id
                      AND conflict_type.name = 'identity_conflict'
                      AND conflict.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
               )
          FROM operations.devices d
         WHERE d.tenant_id = %s AND d.id = %s AND d.deleted_at IS NULL
        """,
        (tenant_id, device_id),
    )
    row = cur.fetchone()
    if row and row[0] and not row[1]:
        return Signal("identity", participant, Readiness.READY, "identity:stable_attachment")
    conflicted = bool(row and row[1])
    return Signal(
        "identity",
        participant,
        Readiness.BLOCKED if conflicted else Readiness.UNKNOWN,
        "identity:unsettled_group" if conflicted else "identity:readiness_not_measured",
    )
