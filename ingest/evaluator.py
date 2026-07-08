"""Platform evaluator.

Reads coverage_requirements and entity_observations to generate and update
entity findings in operations.findings. Runs after each AC ingest cycle
and on a 4-hour sweep.

All operations.* access runs under SET LOCAL operations.tenant_id so RLS
is satisfied. Severity is immutable once set; only confidence and
last_detected_at are updated on repeat detections.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ingest import db

log = logging.getLogger(__name__)

_DEVICE_LONG_OFFLINE_DAYS = 7
_DEVICE_MISSING_MIN_AGE_HOURS = 1


def evaluate(tenant_id: int, device_id: uuid.UUID | None = None) -> int:
    """Evaluate coverage gaps and lifecycle events for a tenant.

    Returns the number of findings opened or updated.
    """
    now = datetime.now(timezone.utc)
    affected = 0

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
            affected += _evaluate_coverage(cur, tenant_id, device_id, now)
            affected += _evaluate_device_lifecycle(cur, tenant_id, device_id, now)
            affected += _auto_resolve(cur, tenant_id, device_id, now)

    log.info("evaluator: tenant=%d findings_affected=%d", tenant_id, affected)
    return affected


def _evaluate_coverage(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Open/update missing_required_platform findings from coverage_requirements."""
    cur.execute(
        """
        SELECT id, client_id, entity_type, platform, device_scope,
               severity, gap_after_hours, confidence_probable, confidence_confirmed
        FROM operations.coverage_requirements
        WHERE tenant_id = %s AND enabled = TRUE
        """,
        (tenant_id,),
    )
    requirements = cur.fetchall()
    if not requirements:
        return 0

    finding_type_id = _get_finding_type_id(cur, "missing_required_platform")
    if finding_type_id is None:
        log.warning("evaluator: finding_type 'missing_required_platform' not found")
        return 0

    count = 0
    for req_id, client_id, entity_type, platform, device_scope, severity, gap_hours, prob_hours, conf_hours in requirements:
        cur.execute(
            """
            SELECT d.id, d.client_id, d.canonical_hostname,
                   MAX(o.observed_at) AS last_observed_at,
                   d.created_at
            FROM operations.devices d
            LEFT JOIN operations.entity_observations o
                ON o.tenant_id = d.tenant_id
               AND o.device_id = d.id
               AND o.entity_type = %s
               AND (%s = '' OR o.platform = %s)
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND (%s IS NULL OR d.client_id = %s)
              AND (%s IS NULL OR d.id = %s)
            GROUP BY d.id, d.client_id, d.canonical_hostname, d.created_at
            """,
            (entity_type, platform, platform, tenant_id, client_id, client_id, device_id, device_id),
        )
        devices = cur.fetchall()

        for dev_id, dev_client_id, hostname, last_observed, dev_created_at in devices:
            reference_ts = last_observed or dev_created_at
            if reference_ts is None:
                continue
            if reference_ts.tzinfo is None:
                reference_ts = reference_ts.replace(tzinfo=timezone.utc)
            gap_age_hours = (now - reference_ts).total_seconds() / 3600
            if gap_age_hours < gap_hours:
                continue

            if gap_age_hours >= conf_hours:
                confidence = "confirmed"
            elif gap_age_hours >= prob_hours:
                confidence = "probable"
            else:
                confidence = "possible"

            ckey = _condition_key(tenant_id, dev_client_id, dev_id, "missing_required_platform", platform)
            count += _upsert_finding(
                cur, tenant_id, finding_type_id, dev_client_id, dev_id,
                ckey, severity, confidence, now,
                {"entity_type": entity_type, "platform": platform, "hostname": hostname},
            )

    return count


def _evaluate_device_lifecycle(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Open device_missing_from_source and device_long_offline findings."""
    count = 0

    # device_missing_from_source
    missing_type_id = _get_finding_type_id(cur, "device_missing_from_source")
    if missing_type_id:
        threshold = now - timedelta(hours=_DEVICE_MISSING_MIN_AGE_HOURS)
        cur.execute(
            """
            SELECT DISTINCT d.id, d.client_id, d.canonical_hostname
            FROM operations.devices d
            JOIN operations.device_links dl ON dl.device_id = d.id AND dl.tenant_id = d.tenant_id
            JOIN operations.sources s ON s.id = dl.source_id
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND dl.missing_since IS NOT NULL
              AND dl.missing_since <= %s
              AND (%s IS NULL OR d.id = %s)
            """,
            (tenant_id, threshold, device_id, device_id),
        )
        for dev_id, dev_client_id, hostname in cur.fetchall():
            ckey = _condition_key(tenant_id, dev_client_id, dev_id, "device_missing_from_source", "")
            count += _upsert_finding(
                cur, tenant_id, missing_type_id, dev_client_id, dev_id,
                ckey, "high", "confirmed", now,
                {"hostname": hostname},
            )

    # device_long_offline
    offline_type_id = _get_finding_type_id(cur, "device_long_offline")
    if offline_type_id:
        offline_threshold = now - timedelta(days=_DEVICE_LONG_OFFLINE_DAYS)
        cur.execute(
            """
            SELECT DISTINCT ON (d.id) d.id, d.client_id, d.canonical_hostname
            FROM operations.devices d
            JOIN ninja_core.device_snapshots ds ON ds.device_id = (
                SELECT dl2.external_id::bigint
                FROM operations.device_links dl2
                JOIN operations.sources s2 ON s2.id = dl2.source_id AND s2.name = 'Ninja'
                WHERE dl2.device_id = d.id AND dl2.tenant_id = d.tenant_id
                LIMIT 1
            )
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND ds.offline = TRUE
              AND ds.snapshot_at <= %s
              AND (%s IS NULL OR d.id = %s)
            ORDER BY d.id, ds.snapshot_at DESC
            """,
            (tenant_id, offline_threshold, device_id, device_id),
        )
        for dev_id, dev_client_id, hostname in cur.fetchall():
            ckey = _condition_key(tenant_id, dev_client_id, dev_id, "device_long_offline", "")
            count += _upsert_finding(
                cur, tenant_id, offline_type_id, dev_client_id, dev_id,
                ckey, "medium", "confirmed", now,
                {"hostname": hostname},
            )

    return count


def _auto_resolve(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Resolve findings where the condition has cleared."""
    count = 0

    # Resolve missing_required_platform if observation now exists within threshold
    ft_id = _get_finding_type_id(cur, "missing_required_platform")
    if ft_id:
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved',
                last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s IS NULL OR f.subject_id = %s)
              AND EXISTS (
                  SELECT 1 FROM operations.entity_observations o
                  WHERE o.tenant_id = f.tenant_id
                    AND o.device_id = f.subject_id
                    AND o.entity_type = (f.finding_details->>'entity_type')
                    AND (f.finding_details->>'platform' = '' OR o.platform = f.finding_details->>'platform')
                    AND o.observed_at > now() - INTERVAL '48 hours'
              )
            """,
            (now, tenant_id, ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve device_missing_from_source if device_links.missing_since cleared
    missing_ft_id = _get_finding_type_id(cur, "device_missing_from_source")
    if missing_ft_id:
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved',
                last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s IS NULL OR f.subject_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM operations.device_links dl
                  WHERE dl.device_id = f.subject_id
                    AND dl.tenant_id = f.tenant_id
                    AND dl.missing_since IS NOT NULL
              )
            """,
            (now, tenant_id, missing_ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    return count


_finding_type_cache: dict[str, int] = {}


def _get_finding_type_id(cur: Any, name: str) -> int | None:
    if name in _finding_type_cache:
        return _finding_type_cache[name]
    cur.execute(
        "SELECT id FROM operations.finding_types WHERE name = %s LIMIT 1",
        (name,),
    )
    row = cur.fetchone()
    if row:
        _finding_type_cache[name] = row[0]
        return row[0]
    return None


def _condition_key(
    tenant_id: int,
    client_id: Any,
    device_id: uuid.UUID,
    finding_type: str,
    platform: str,
) -> str:
    raw = f"{tenant_id}:{client_id}:{device_id}:{finding_type}:{platform}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _upsert_finding(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    client_id: Any,
    device_id: uuid.UUID,
    condition_key: str,
    severity: str,
    confidence: str,
    now: datetime,
    details: dict[str, Any],
) -> int:
    """UPSERT a finding. Severity is immutable; confidence and timestamps update."""
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, finding_details,
            condition_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s,
            'device', %s, %s::jsonb,
            %s, %s, %s, 'open',
            %s, %s, %s
        )
        ON CONFLICT ON CONSTRAINT uq_findings_active_condition_key DO UPDATE SET
            confidence      = EXCLUDED.confidence,
            last_seen_at    = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            status          = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        """,
        (
            tenant_id, finding_type_id, client_id,
            device_id, _json_str(details),
            condition_key, severity, confidence,
            now, now, now,
        ),
    )
    return 1


def _json_str(d: dict[str, Any]) -> str:
    import json
    return json.dumps(d)
