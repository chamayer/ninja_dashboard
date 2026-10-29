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
    max_age_hours: int = 24,
) -> bool:
    """Return true only for a recent, complete, internally consistent run."""
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
         ORDER BY GREATEST(
             COALESCE(completed_at, '-infinity'::timestamptz),
             COALESCE(run_started_at, '-infinity'::timestamptz)
         ) DESC
         LIMIT 1
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return False
    status, complete, expected, written, failed, started, completed = row
    return bool(
        status == "complete" and complete is True and failed == 0
        and expected == written and started is not None and completed is not None
        and started <= completed <= now
        and completed >= now - timedelta(hours=max_age_hours)
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
                WHERE f.tenant_id = d.tenant_id
                  AND (f.subject_id = d.id OR f.finding_details->'candidate_device_ids'
                       @> jsonb_build_array(d.id::text))
                  AND ft.name = 'identity_conflict'
                  AND f.status IN ('open','acknowledged','investigating','suppressed')
                  AND NOT EXISTS (
                      SELECT 1
                        FROM operations.condition_reviewed_distinct reviewed
                       WHERE reviewed.tenant_id = f.tenant_id
                         AND reviewed.condition_identity = f.condition_key
                         AND reviewed.membership_fingerprint = encode(
                             pg_catalog.sha256(convert_to(
                                 (f.finding_details->'candidate_device_ids')::text,
                                 'UTF8')), 'hex')
                         AND reviewed.evidence_fingerprint = encode(
                             pg_catalog.sha256(convert_to(
                                 f.finding_details::text, 'UTF8')), 'hex')
                  ))
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


_NAMESPACES = {"findings": "entity", "admin_findings": "admin"}

# Upserts an admin-namespace condition into the common findings ledger. Every
# parameter is cast: in INSERT ... SELECT PostgreSQL cannot infer them. The
# subject is normalized by the same database function the M2 conversion used,
# and the producer's subject reference is kept as ``legacy_ref``. Append
# ``RETURNING id`` when the caller needs the finding ID.
ADMIN_FINDING_UPSERT_SQL = """
    INSERT INTO operations.findings (
        id, version, tenant_id, finding_type_id, condition_key, severity, status,
        subject_type, subject_id, client_id, subject_ref, finding_details,
        first_seen_at, last_seen_at, last_detected_at, confidence, condition_namespace
    )
    SELECT gen_random_uuid(), 1, %(tenant)s::bigint, %(finding_type)s::smallint,
           %(key)s::varchar, %(severity)s::varchar, 'open',
           s.subject_type, s.subject_id, s.client_id, s.subject_ref, %(details)s::jsonb,
           %(now)s::timestamptz, %(now)s::timestamptz, %(now)s::timestamptz, '', 'admin'
      FROM operations.normalize_admin_subject(
               %(tenant)s::bigint, %(ref)s::jsonb, %(details)s::jsonb) s
    ON CONFLICT (tenant_id, condition_namespace, condition_key)
        WHERE condition_key > ''
          AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
    DO UPDATE SET
        last_detected_at = EXCLUDED.last_detected_at,
        last_seen_at = EXCLUDED.last_seen_at,
        finding_details = EXCLUDED.finding_details,
        subject_type = EXCLUDED.subject_type,
        subject_id = EXCLUDED.subject_id,
        client_id = EXCLUDED.client_id,
        subject_ref = EXCLUDED.subject_ref,
        severity = EXCLUDED.severity
"""


def admin_finding_upsert_params(
    tenant_id: int,
    finding_type_id: int,
    condition_key: str,
    severity: str,
    subject_ref: dict[str, Any],
    details: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "tenant": tenant_id,
        "finding_type": finding_type_id,
        "key": condition_key,
        "severity": severity,
        "ref": json.dumps(subject_ref),
        "details": json.dumps(details),
        "now": now,
    }


def preserve_operator_episode(
    cur: Any, table: str, tenant_id: int, condition_key: str, now: datetime,
    details: dict[str, Any],
) -> str | None:
    """Refresh an operator-managed episode instead of creating a duplicate.

    ``table`` names the legacy ledger, which is now the finding's namespace in
    the common findings ledger.
    """
    if table not in _NAMESPACES:
        raise ValueError("Unsupported condition table")
    cur.execute(
        """
        UPDATE operations.findings
           SET finding_details = %s::jsonb, last_seen_at = %s, last_detected_at = %s
         WHERE tenant_id = %s AND condition_namespace = %s AND condition_key = %s
           AND status IN ('investigating', 'suppressed')
        RETURNING id
        """,
        (json.dumps(details), now, now, tenant_id, _NAMESPACES[table], condition_key),
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
                      AND (conflict.subject_id = d.id OR conflict.finding_details->'candidate_device_ids'
                           @> jsonb_build_array(d.id::text))
                      AND conflict_type.name = 'identity_conflict'
                      AND conflict.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
                      AND NOT EXISTS (
                          SELECT 1
                            FROM operations.condition_reviewed_distinct reviewed
                           WHERE reviewed.tenant_id = conflict.tenant_id
                             AND reviewed.condition_identity = conflict.condition_key
                             AND reviewed.membership_fingerprint = encode(
                                 pg_catalog.sha256(convert_to(
                                     (conflict.finding_details->'candidate_device_ids')::text,
                                     'UTF8')), 'hex')
                             AND reviewed.evidence_fingerprint = encode(
                                 pg_catalog.sha256(convert_to(
                                     conflict.finding_details::text, 'UTF8')), 'hex')
                      )
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
