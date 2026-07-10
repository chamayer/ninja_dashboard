"""Platform evaluator.

Reads coverage_requirements and entity_observations to generate and update
entity findings in operations.findings. Runs after each ingest cycle and
on a 4-hour sweep.

Pipeline per run (device_id=None means full sweep):
  1. Source-failure guard — platforms whose latest run_log entry failed
     or is overdue are skipped for coverage this cycle and raise an
     admin_findings row (resolved automatically once healthy).
  2. Device-role sync — devices get their server/workstation role from
     the latest role-bearing observation of any source; disagreeing
     sources raise device_role_conflict (Ninja stays authoritative).
  3. Coverage — missing_required_platform (never observed) and
     stale_required_platform (observed before, quiet past the gap
     threshold). Requirements filter on device_scope and skip exempted
     entity_types. Confidence is capped at 'probable' unless another
     source saw the device online recently (corroboration).
  4. Lifecycle — device_missing_from_source, device_long_offline,
     device_stale_data, cross_client_conflict.
  5. Auto-resolve for all of the above once conditions clear.

All operations.* access runs under SET LOCAL operations.tenant_id so RLS
is satisfied. Severity is immutable once set; only confidence and
last_detected_at are updated on repeat detections.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ingest import db
from ingest.normalize import normalize_hostname, parse_dt

log = logging.getLogger(__name__)

_DEVICE_MISSING_MIN_AGE_HOURS = 1
_SOURCE_OVERDUE_HOURS = 24
_CORROBORATION_WINDOW_HOURS = 48
_LONG_OFFLINE_DAYS = 7
_STALE_DATA_DAYS = 7


def evaluate(tenant_id: int, device_id: uuid.UUID | None = None) -> int:
    """Evaluate coverage gaps and lifecycle events for a tenant.

    Returns the number of findings opened or updated.
    """
    now = datetime.now(timezone.utc)
    affected = 0

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
            skip_platforms = _source_failure_guard(cur, tenant_id, now)
            if device_id is None:
                affected += _sync_device_roles(cur, tenant_id, now)
            corroborated = _load_corroborated_devices(cur, tenant_id)
            affected += _evaluate_coverage(
                cur, tenant_id, device_id, now, skip_platforms, corroborated
            )
            affected += _evaluate_device_lifecycle(cur, tenant_id, device_id, now)
            if device_id is None:
                affected += _evaluate_cross_client(cur, tenant_id, now)
            affected += _auto_resolve(cur, tenant_id, device_id, now)

    log.info(
        "evaluator: tenant=%d findings_affected=%d skipped_platforms=%s",
        tenant_id, affected, sorted(skip_platforms) or "-",
    )
    return affected


# --------------------------------------------------------------------------
# 1. Source-failure guard
# --------------------------------------------------------------------------

def _source_failure_guard(cur: Any, tenant_id: int, now: datetime) -> set[str]:
    """Return platforms to skip this cycle; maintain source_failure admin findings.

    A platform is skipped when its latest run_log entry failed, or its
    latest success is older than _SOURCE_OVERDUE_HOURS. Platforms with no
    run_log rows at all are treated as healthy (transition period — the
    writers only started recording runs with this release).
    """
    cur.execute(
        """
        SELECT DISTINCT platform FROM operations.coverage_requirements
        WHERE tenant_id = %s AND enabled = TRUE
        """,
        (tenant_id,),
    )
    platforms = [row[0] for row in cur.fetchall()]

    ft_id = _get_finding_type_id(cur, "source_failure")
    skip: set[str] = set()
    for platform in platforms:
        cur.execute(
            """
            SELECT ok, ended_at, error FROM operations.run_log
            WHERE tenant_id = %s
              AND (kind = %s OR kind LIKE %s)
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (tenant_id, f"source.{platform}", f"source.{platform}.%"),
        )
        row = cur.fetchone()
        if row is None:
            continue
        ok, ended_at, error = row
        reason = ""
        if not ok:
            reason = f"latest run failed: {error or 'unknown error'}"
        elif ended_at is not None:
            if ended_at.tzinfo is None:
                ended_at = ended_at.replace(tzinfo=timezone.utc)
            if now - ended_at > timedelta(hours=_SOURCE_OVERDUE_HOURS):
                reason = f"no successful run since {ended_at.isoformat()}"

        condition_key = f"source_failure:{platform}"
        if reason:
            skip.add(platform)
            if ft_id:
                severity = "critical" if platform == "Ninja" else "high"
                _upsert_admin_finding(
                    cur, tenant_id, ft_id, condition_key, severity, now,
                    {"platform": platform},
                    {"reason": reason[:500]},
                )
        else:
            cur.execute(
                """
                UPDATE operations.admin_findings
                SET status = 'resolved', resolved_at = %s
                WHERE tenant_id = %s AND condition_key = %s
                  AND status IN ('open', 'acknowledged')
                """,
                (now, tenant_id, condition_key),
            )

    return skip


def _upsert_admin_finding(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    condition_key: str,
    severity: str,
    now: datetime,
    subject_ref: dict[str, Any],
    details: dict[str, Any],
) -> None:
    cur.execute(
        """
        INSERT INTO operations.admin_findings (
            id, version, tenant_id, finding_type_id, condition_key, severity,
            status, subject_ref, details, first_detected_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s, %s, 'open', %s::jsonb, %s::jsonb, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE status IN ('open', 'acknowledged')
        DO UPDATE SET
            last_detected_at = EXCLUDED.last_detected_at,
            details          = EXCLUDED.details
        """,
        (
            tenant_id, finding_type_id, condition_key, severity,
            json.dumps(subject_ref), json.dumps(details), now, now,
        ),
    )


# --------------------------------------------------------------------------
# 2. Device-role sync (any source, never guessed)
# --------------------------------------------------------------------------

def _sync_device_roles(cur: Any, tenant_id: int, now: datetime) -> int:
    """Set device_role from any source's explicit signal; flag disagreements.

    Ninja stays authoritative when sources disagree (the Ninja pull
    already synced its own signal in ingest.core.devices); this fills in
    devices Ninja gave no signal for and raises device_role_conflict
    when sources' latest claims differ.
    """
    cur.execute(
        """
        SELECT DISTINCT ON (device_id, platform)
               device_id, platform,
               COALESCE(canonical_data ->> 'device_role',
                        canonical_data ->> 'device_type') AS device_role
        FROM operations.entity_observations
        WHERE tenant_id = %s AND device_id IS NOT NULL
          AND COALESCE(canonical_data ->> 'device_role',
                       canonical_data ->> 'device_type') IS NOT NULL
          AND observed_at > now() - INTERVAL '7 days'
        ORDER BY device_id, platform, observed_at DESC
        """,
        (tenant_id,),
    )
    claims: dict[uuid.UUID, dict[str, str]] = {}
    for dev_id, platform, role in cur.fetchall():
        claims.setdefault(dev_id, {})[platform] = role

    if not claims:
        return 0

    cur.execute(
        """
        SELECT id, client_id, canonical_hostname, device_role
        FROM operations.devices
        WHERE tenant_id = %s AND deleted_at IS NULL AND id = ANY(%s)
        """,
        (tenant_id, list(claims)),
    )
    devices = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

    ft_id = _get_finding_type_id(cur, "device_role_conflict")
    count = 0
    conflict_ids: list[uuid.UUID] = []
    for dev_id, dev_claims in claims.items():
        info = devices.get(dev_id)
        if info is None:
            continue
        client_id, hostname, current_role = info
        distinct = set(dev_claims.values())
        target = dev_claims.get("Ninja") or (
            next(iter(distinct)) if len(distinct) == 1 else None
        )
        if target and target != current_role:
            cur.execute(
                "UPDATE operations.devices SET device_role = %s WHERE id = %s",
                (target, dev_id),
            )
        if len(distinct) > 1:
            conflict_ids.append(dev_id)
            if ft_id:
                ckey = _condition_key(
                    tenant_id, client_id, dev_id, "device_role_conflict", ""
                )
                count += _upsert_finding(
                    cur, tenant_id, ft_id, client_id, dev_id,
                    ckey, "low", "confirmed", now,
                    {"hostname": hostname, "claims": dev_claims},
                )

    if ft_id:
        _resolve_findings_absent(cur, tenant_id, ft_id, conflict_ids, now)
    return count


# --------------------------------------------------------------------------
# 3. Coverage
# --------------------------------------------------------------------------

def _load_corroborated_devices(cur: Any, tenant_id: int) -> set[uuid.UUID]:
    """Devices some source saw online recently — allows 'confirmed' gaps."""
    cur.execute(
        """
        SELECT DISTINCT device_id
        FROM operations.entity_observations
        WHERE tenant_id = %s AND device_id IS NOT NULL
          AND observed_at > now() - %s::interval
          AND canonical_data ->> 'is_online' = 'true'
        """,
        (tenant_id, f"{_CORROBORATION_WINDOW_HOURS} hours"),
    )
    return {row[0] for row in cur.fetchall()}


def _evaluate_coverage(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
    skip_platforms: set[str],
    corroborated: set[uuid.UUID],
) -> int:
    """Open/update missing/stale_required_platform findings per requirement."""
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

    missing_ft = _get_finding_type_id(cur, "missing_required_platform")
    stale_ft = _get_finding_type_id(cur, "stale_required_platform")
    if missing_ft is None:
        log.warning("evaluator: finding_type 'missing_required_platform' not found")
        return 0

    count = 0
    for (req_id, client_id, entity_type, platform, device_scope,
         severity, gap_hours, prob_hours, conf_hours) in requirements:
        if platform in skip_platforms:
            continue
        cur.execute(
            """
            SELECT d.id, d.client_id, d.canonical_hostname,
                   apc.last_observed_at, d.created_at
            FROM operations.devices d
            LEFT JOIN operations.agent_presence_current apc
                ON apc.tenant_id = d.tenant_id
               AND apc.device_id = d.id
               AND apc.entity_type = %s
               AND apc.platform = %s
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND d.lifecycle_status != 'retired'
              AND (%s = 'all' OR d.device_role = %s)
              AND NOT jsonb_exists(d.exemptions, %s)
              AND (%s::uuid IS NULL OR d.client_id = %s)
              AND (%s::uuid IS NULL OR d.id = %s)
            """,
            (
                entity_type, platform, tenant_id,
                device_scope, device_scope, entity_type,
                client_id, client_id, device_id, device_id,
            ),
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
            # Corroboration: only call a gap 'confirmed' when another
            # source saw the device online recently (legacy confirmed_gap).
            if confidence == "confirmed" and dev_id not in corroborated:
                confidence = "probable"

            if last_observed is None:
                ftype, ft_name, sev = missing_ft, "missing_required_platform", severity
            else:
                if stale_ft is None:
                    continue
                ftype, ft_name, sev = stale_ft, "stale_required_platform", "medium"

            ckey = _condition_key(tenant_id, dev_client_id, dev_id, ft_name, platform)
            count += _upsert_finding(
                cur, tenant_id, ftype, dev_client_id, dev_id,
                ckey, sev, confidence, now,
                {"entity_type": entity_type, "platform": platform, "hostname": hostname},
            )

    return count


# --------------------------------------------------------------------------
# 4. Lifecycle
# --------------------------------------------------------------------------

def _evaluate_device_lifecycle(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """device_missing_from_source, device_long_offline, device_stale_data."""
    count = 0

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
              AND (%s::uuid IS NULL OR d.id = %s)
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

    if device_id is None:
        count += _evaluate_long_offline(cur, tenant_id, now)
        count += _evaluate_stale_data(cur, tenant_id, now)
    return count


def _evaluate_long_offline(cur: Any, tenant_id: int, now: datetime) -> int:
    """Devices Ninja still reports but that haven't contacted it in a week."""
    ft_id = _get_finding_type_id(cur, "device_long_offline")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT DISTINCT ON (eo.device_id)
               eo.device_id, d.client_id, d.canonical_hostname,
               eo.canonical_data ->> 'last_seen_at'
        FROM operations.entity_observations eo
        JOIN operations.devices d
             ON d.id = eo.device_id AND d.tenant_id = eo.tenant_id
        WHERE eo.tenant_id = %s AND eo.platform = 'Ninja'
          AND eo.device_id IS NOT NULL
          AND eo.observed_at > now() - INTERVAL '2 days'
          AND d.deleted_at IS NULL
        ORDER BY eo.device_id, eo.observed_at DESC
        """,
        (tenant_id,),
    )
    threshold = now - timedelta(days=_LONG_OFFLINE_DAYS)
    count = 0
    offenders: list[uuid.UUID] = []
    for dev_id, client_id, hostname, last_seen_raw in cur.fetchall():
        last_seen = parse_dt(last_seen_raw)
        if last_seen is None:
            continue
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if last_seen >= threshold:
            continue
        offenders.append(dev_id)
        ckey = _condition_key(tenant_id, client_id, dev_id, "device_long_offline", "")
        count += _upsert_finding(
            cur, tenant_id, ft_id, client_id, dev_id,
            ckey, "medium", "confirmed", now,
            {"hostname": hostname, "last_seen_at": last_seen_raw},
        )
    _resolve_findings_absent(cur, tenant_id, ft_id, offenders, now)
    return count


def _evaluate_stale_data(cur: Any, tenant_id: int, now: datetime) -> int:
    """Devices no source has observed at all in the stale window."""
    ft_id = _get_finding_type_id(cur, "device_stale_data")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT apc.device_id, d.client_id, d.canonical_hostname,
               MAX(apc.last_observed_at)
        FROM operations.agent_presence_current apc
        JOIN operations.devices d
             ON d.id = apc.device_id AND d.tenant_id = apc.tenant_id
        WHERE apc.tenant_id = %s AND d.deleted_at IS NULL
        GROUP BY apc.device_id, d.client_id, d.canonical_hostname
        HAVING MAX(apc.last_observed_at) < now() - %s::interval
        """,
        (tenant_id, f"{_STALE_DATA_DAYS} days"),
    )
    count = 0
    offenders: list[uuid.UUID] = []
    for dev_id, client_id, hostname, last_observed in cur.fetchall():
        offenders.append(dev_id)
        ckey = _condition_key(tenant_id, client_id, dev_id, "device_stale_data", "")
        count += _upsert_finding(
            cur, tenant_id, ft_id, client_id, dev_id,
            ckey, "low", "confirmed", now,
            {
                "hostname": hostname,
                "last_observed_at": last_observed.isoformat() if last_observed else None,
            },
        )
    _resolve_findings_absent(cur, tenant_id, ft_id, offenders, now)
    return count


def _evaluate_cross_client(cur: Any, tenant_id: int, now: datetime) -> int:
    """Same normalized hostname under different clients → conflict finding."""
    ft_id = _get_finding_type_id(cur, "cross_client_conflict")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT id, client_id, canonical_hostname
        FROM operations.devices
        WHERE tenant_id = %s AND deleted_at IS NULL
        """,
        (tenant_id,),
    )
    by_norm: dict[str, list[tuple[uuid.UUID, Any, str]]] = {}
    for dev_id, client_id, hostname in cur.fetchall():
        norm = normalize_hostname(hostname)
        if norm:
            by_norm.setdefault(norm, []).append((dev_id, client_id, hostname))

    count = 0
    offenders: list[uuid.UUID] = []
    for norm, entries in by_norm.items():
        clients = {e[1] for e in entries}
        if len(clients) < 2:
            continue
        for dev_id, client_id, hostname in entries:
            offenders.append(dev_id)
            ckey = _condition_key(tenant_id, client_id, dev_id, "cross_client_conflict", norm)
            count += _upsert_finding(
                cur, tenant_id, ft_id, client_id, dev_id,
                ckey, "medium", "confirmed", now,
                {"hostname": hostname, "client_count": len(clients)},
            )
    _resolve_findings_absent(cur, tenant_id, ft_id, offenders, now)
    return count


# --------------------------------------------------------------------------
# 5. Auto-resolve
# --------------------------------------------------------------------------

def _auto_resolve(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Resolve findings where the condition has cleared."""
    count = 0

    # Resolve missing/stale_required_platform when the platform has
    # observed the device again recently.
    for ft_name in ("missing_required_platform", "stale_required_platform"):
        ft_id = _get_finding_type_id(cur, ft_name)
        if not ft_id:
            continue
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved',
                last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND EXISTS (
                  SELECT 1 FROM operations.agent_presence_current apc
                  WHERE apc.tenant_id = f.tenant_id
                    AND apc.device_id = f.subject_id
                    AND apc.entity_type = (f.finding_details->>'entity_type')
                    AND apc.platform = (f.finding_details->>'platform')
                    AND apc.last_observed_at > now() - INTERVAL '48 hours'
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
              AND (%s::uuid IS NULL OR f.subject_id = %s)
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


def _resolve_findings_absent(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    current_subject_ids: list[uuid.UUID],
    now: datetime,
) -> None:
    """Resolve open findings of a type whose subject is no longer an offender."""
    cur.execute(
        """
        UPDATE operations.findings
        SET status = 'resolved', last_seen_at = %s
        WHERE tenant_id = %s
          AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (subject_id = ANY(%s::uuid[]))
        """,
        (now, tenant_id, finding_type_id, current_subject_ids),
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

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
        ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
        DO UPDATE SET
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
            device_id, json.dumps(details),
            condition_key, severity, confidence,
            now, now, now,
        ),
    )
    return 1
