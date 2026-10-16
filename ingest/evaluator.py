"""Platform evaluator.

Reads coverage_requirements and entity_observations to generate and update
entity findings in operations.findings. Runs after each ingest cycle and
on a 4-hour sweep.

Pipeline per run (device_id=None means full sweep):
  1. Source-failure guard — failed or overdue configured source bindings raise
     a binding-scoped admin Issue. Dependent coverage results remain recorded
     but are blocked by that root Issue until current source data returns.
  2. Device-role sync — devices get their server/workstation role from
     the latest role-bearing observation of any source; disagreeing
     sources raise device_role_conflict (Ninja stays authoritative).
  3. Coverage — missing_required_platform (never observed) and
     stale_required_platform (observed before, quiet past the gap
     threshold). Requirements filter on device_scope and skip exempted
     entity_types. Confidence is capped at 'probable' unless another
     source saw the device online recently (corroboration).
  4. Lifecycle — device_source_record_withdrawn,
     device_missing_from_source, device_offline,
     device_stale_data. (cross_client_conflict removed 2026-07-14 —
     see BLUEPRINT §1.7.)
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
from ingest.condition_evidence import preserve_operator_episode
from ingest import computer_listing, device_status_settings
from ingest.conditions import record_assessment
from ingest.identity import findings as identity_findings
from ingest.intel.windows_servicing import sync as sync_windows_servicing
from ingest import normalize
from ingest.normalize import is_usable_serial, load_identity_value_rejections
from ingest.source_health import (
    SourceCollectionProblem,
    blockers_for_platform,
    collection_problems,
)
from shared.conditions.contracts import (
    Condition,
    EvaluationCoverage,
    Participant,
    Readiness,
    Signal,
)

log = logging.getLogger(__name__)

_DEVICE_MISSING_MIN_AGE_HOURS = 1
_CORROBORATION_WINDOW_HOURS = 48
_LONG_OFFLINE_DAYS = 7
_STALE_DATA_DAYS = 7


def _requirement_key(row: tuple) -> tuple:
    """Identify a requirement independently of its scope and thresholds."""
    agent_id, entity_type, platform = row[2], row[3], row[4]
    return ("agent", agent_id) if agent_id is not None else ("legacy", entity_type, platform)


def _apply_requirement_overrides(baseline: list[tuple], overrides: list[tuple]) -> list[tuple]:
    """Apply enabled/disabled client overrides to inherited requirements.

    Override tuples add ``enabled`` at index 11. Enabled rows replace the
    matching inherited requirement; disabled rows remove it.
    """
    effective = {_requirement_key(row): row for row in baseline}
    for row in overrides:
        if row[11]:
            effective[_requirement_key(row)] = row[:11]
        else:
            effective.pop(_requirement_key(row), None)
    return list(effective.values())


def evaluate(tenant_id: int, device_id: uuid.UUID | None = None) -> int:
    """Evaluate coverage gaps and lifecycle events for a tenant.

    Returns the number of findings opened or updated. Writes a
    `platform_evaluator` row to operations.run_log so operators can see
    when the evaluator ran and how many findings the run touched.
    """
    now = datetime.now(timezone.utc)
    evaluator_run_id = uuid.uuid4()
    affected = 0
    error_msg: str | None = None
    source_problems: list[SourceCollectionProblem] = []

    try:
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
                source_problems = _source_failure_guard(cur, tenant_id, now)
                listing_owned: set[uuid.UUID] = set()
                affected += _sync_source_withdrawal_lifecycle(
                    cur, tenant_id, now, evaluator_run_id, device_id, listing_owned
                )
                if device_id is None:
                    affected += _sync_device_roles(cur, tenant_id, now)
                    affected += _sync_lifecycle_status(
                        cur, tenant_id, now, evaluator_run_id, skip=listing_owned
                    )
                    affected += _evaluate_unknown_entities(cur, tenant_id, now)
                    affected += _evaluate_change_history_registry(cur, tenant_id, now)
                    affected += _evaluate_duplicate_records(cur, tenant_id, now)
                    affected += identity_findings.evaluate(cur, tenant_id, now)
                corroborated = _load_corroborated_devices(cur, tenant_id)
                affected += _evaluate_coverage(
                    cur, tenant_id, device_id, now, source_problems, corroborated
                )
                affected += _evaluate_unenrolled(cur, tenant_id, device_id, now)
                affected += _evaluate_device_lifecycle(
                    cur, tenant_id, device_id, now, source_problems
                )
                affected += sync_windows_servicing(
                    cur, tenant_id, device_id, now=now
                )
                # cross_client_conflict emitter removed 2026-07-14 — see
                # BLUEPRINT §1.7 for design rationale. Existing findings
                # closed in migration 0034.
                affected += _auto_resolve(cur, tenant_id, device_id, now)
    except Exception as exc:
        error_msg = str(exc)[:2000]
        raise
    finally:
        try:
            with db.transaction() as cur:
                cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
                cur.execute(
                    """
                    INSERT INTO operations.run_log
                        (id, tenant_id, kind, subject_ref, started_at,
                         ended_at, ok, rows, error)
                    VALUES (%s, %s, 'platform_evaluator',
                            %s::jsonb, %s, NOW(), %s, %s, %s)
                    """,
                    (
                        evaluator_run_id,
                        tenant_id,
                        json.dumps({"device_id": str(device_id) if device_id else None}),
                        now,
                        error_msg is None,
                        affected,
                        error_msg or "",
                    ),
                )
        except Exception:
            log.exception("evaluator: run_log write failed — continuing")

    log.info(
        "evaluator: tenant=%d findings_affected=%d blocked_sources=%s",
        tenant_id,
        affected,
        sorted(problem.source_name for problem in source_problems) or "-",
    )
    return affected


# --------------------------------------------------------------------------
# 1. Source-failure guard
# --------------------------------------------------------------------------


def _source_failure_guard(
    cur: Any, tenant_id: int, now: datetime
) -> list[SourceCollectionProblem]:
    """Emit source-bound root Issues and return their affected source scopes."""
    ft_id = _get_finding_type_id(cur, "source_failure")
    problems = collection_problems(cur, tenant_id, now)
    active_keys = [problem.condition_key for problem in problems]
    if ft_id:
        for problem in problems:
            _upsert_admin_finding(
                cur,
                tenant_id,
                ft_id,
                problem.condition_key,
                "high",
                now,
                {
                    "source_binding_id": problem.binding_id,
                    "platform": problem.platform,
                    "client_id": str(problem.client_id) if problem.client_id else None,
                },
                {
                    "source": problem.source_name,
                    "reason": problem.reason,
                    "last_failure_at": problem.last_failure_at.isoformat()
                    if problem.last_failure_at
                    else None,
                    "last_success_at": problem.last_success_at.isoformat()
                    if problem.last_success_at
                    else None,
                    "error": problem.error,
                },
                measured=True,
            )
        cur.execute(
            """
            UPDATE operations.admin_findings
               SET status = 'resolved', resolved_at = %s
             WHERE tenant_id = %s
               AND condition_key LIKE 'source_failure:binding:%%'
               AND status IN ('open', 'acknowledged', 'investigating')
               AND NOT (condition_key = ANY(%s::text[]))
               AND EXISTS (
                   SELECT 1 FROM operations.condition_assessments assessment
                   JOIN operations.condition_policy_versions policy
                     ON policy.version = assessment.policy_version AND policy.active
                  WHERE assessment.tenant_id = operations.admin_findings.tenant_id
                    AND assessment.row_kind = 'admin'
                    AND assessment.finding_id = operations.admin_findings.id
                    AND (assessment.response->>'may_clear')::boolean IS TRUE
                    AND assessment.assessed_at >= now() -
                        (policy.policy->>'freshness_hours')::integer * interval '1 hour'
               )
            """,
            (now, tenant_id, active_keys),
        )
    return problems


def _upsert_admin_finding(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    condition_key: str,
    severity: str,
    now: datetime,
    subject_ref: dict[str, Any],
    details: dict[str, Any],
    *,
    measured: bool = False,
) -> None:
    preserved = preserve_operator_episode(cur, "admin_findings", tenant_id, condition_key, now, details)
    if preserved is not None:
        finding_id = uuid.UUID(preserved)
    else:
        cur.execute(
        """
        INSERT INTO operations.admin_findings (
            id, version, tenant_id, finding_type_id, condition_key, severity,
            status, subject_ref, details, first_detected_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s, %s, 'open', %s::jsonb, %s::jsonb, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            last_detected_at = EXCLUDED.last_detected_at,
            details          = EXCLUDED.details
        RETURNING id
        """,
        (
            tenant_id,
            finding_type_id,
            condition_key,
            severity,
            json.dumps(subject_ref),
            json.dumps(details),
            now,
            now,
        ),
    )
        row = cur.fetchone()
        if row is None:
            return
        finding_id = row[0]
    condition = Condition(
        tenant_id,
        "admin",
        str(finding_id),
        _finding_type_name(cur, finding_type_id),
        condition_key,
        "open",
    )
    record_assessment(
        cur,
        condition,
        (),
        EvaluationCoverage(measured, measured, measured, measured),
        now=now,
        reevaluation_key=f"evaluator-admin:{condition_key}:{now.isoformat()}",
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
        FROM operations.entity_observation_current
        WHERE tenant_id = %s AND device_id IS NOT NULL
          AND active = TRUE
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
        # ADR-0012: the evaluator no longer writes device_role. Source
        # precedence belongs in the effective attribute contract, not in a
        # Python `dev_claims.get("Ninja")`, and the cache column is owned by
        # `ingest.device_cache_projector`. Detecting the conflict below is
        # still this evaluator's job — that is the operator-visible surface.
        if len(distinct) > 1:
            conflict_ids.append(dev_id)
            if ft_id:
                ckey = _condition_key(tenant_id, client_id, dev_id, "device_role_conflict", "")
                count += _upsert_finding(
                    cur,
                    tenant_id,
                    ft_id,
                    client_id,
                    dev_id,
                    ckey,
                    "low",
                    "confirmed",
                    now,
                    {"hostname": hostname, "claims": dev_claims},
                )

    if ft_id:
        _resolve_findings_absent(
            cur, tenant_id, ft_id, conflict_ids, now, assessment_required=True
        )
    return count


# --------------------------------------------------------------------------
# 2b. Lifecycle status sync (platform truth from device_agent_presence_current)
# --------------------------------------------------------------------------


_LIFECYCLE_POLICY_VERSION = "lifecycle-evidence-v1"
_LIFECYCLE_DIRECT_MODES = {"direct_contact", "direct_then_reported_state"}
_LIFECYCLE_REPORTED_MODES = {"reported_state", "direct_then_reported_state"}
_LIFECYCLE_POSITIVE_POWER_STATES = {"poweredon"}
_LIFECYCLE_NEGATIVE_POWER_STATES = {"poweredoff", "suspended"}


def _reported_lifecycle_state(
    power_state: str | None,
    has_power_state: bool,
    reported_online: bool | None,
    has_reported_online_state: bool,
) -> tuple[str | None, bool]:
    """Return (lifecycle evidence, is_unknown) for one reported state.

    Power state is authoritative when present. Do not fall back to the legacy
    ``reported_online`` projection in that case: the projection historically
    treated every non-powered-on value as offline, including new values the
    lifecycle policy has not approved. When power is absent, a recognized
    online/offline report is valid evidence; an unrecognized online field is a
    data-quality finding rather than an inferred lifecycle result.
    """
    if has_power_state:
        normalized = power_state.strip().lower() if isinstance(power_state, str) else ""
        if normalized in _LIFECYCLE_POSITIVE_POWER_STATES:
            return "active", False
        if normalized in _LIFECYCLE_NEGATIVE_POWER_STATES:
            return "offline_aging", False
        return None, True
    if reported_online is True:
        return "active", False
    if reported_online is False:
        return "offline_aging", False
    return None, has_reported_online_state


def _select_lifecycle_evidence(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool]:
    """Select newest qualified evidence, returning (evidence, conflict).

    A direct contact wins only when its timestamp exactly ties the newest
    reported-state evidence. Equally recent contradictory reported states are
    deliberately unresolved: lifecycle remains unchanged and a finding makes
    the conflict visible.
    """
    candidates: list[dict[str, Any]] = []
    for row in rows:
        mode = row["mode"]
        if mode in _LIFECYCLE_DIRECT_MODES and row["last_contact_at"] is not None:
            candidates.append(
                {
                    "kind": "direct_contact",
                    "status": "active",
                    "at": row["last_contact_at"],
                    "entity_type": row["entity_type"],
                    "platform": row["platform"],
                }
            )
        if mode in _LIFECYCLE_REPORTED_MODES:
            status, _ = _reported_lifecycle_state(
                row["last_power_state"],
                row["has_power_state"],
                row["reported_online"],
                row["has_reported_online_state"],
            )
            if status is not None:
                candidates.append(
                    {
                        "kind": "reported_state",
                        "status": status,
                        "at": row["last_observed_at"],
                        "entity_type": row["entity_type"],
                        "platform": row["platform"],
                    }
                )

    if not candidates:
        return None, False

    newest_at = max(candidate["at"] for candidate in candidates)
    newest = [candidate for candidate in candidates if candidate["at"] == newest_at]
    newest_direct = [
        candidate for candidate in newest if candidate["kind"] == "direct_contact"
    ]
    if newest_direct:
        return newest_direct[0], False

    statuses = {candidate["status"] for candidate in newest}
    if len(statuses) != 1:
        return None, True
    return newest[0], False


def _lifecycle_target(
    evidence: dict[str, Any],
    now: datetime,
    offline_after_days: int,
    retire_review_days: int,
) -> str:
    """Apply the three-state aging rules to selected evidence.

    The two thresholds are the tenant's Device status settings, not constants.
    """
    if evidence["at"] < now - timedelta(days=retire_review_days):
        return "pending_cleanup"
    if evidence["status"] == "offline_aging" or evidence["at"] < now - timedelta(
        days=offline_after_days
    ):
        return "offline_aging"
    return "active"


def _device_lifecycle_target(
    device: dict[str, Any],
    evidence: dict[str, Any],
    now: datetime,
    offline_after_days: int,
    retire_review_days: int,
    client_offline_days: dict[str, int],
) -> str:
    """Apply the aging rules with the device's client override, if any."""
    device_offline_days = client_offline_days.get(str(device["client_id"]), offline_after_days)
    return _lifecycle_target(
        evidence,
        now,
        device_offline_days,
        max(retire_review_days, device_offline_days + 1),
    )


def _load_lifecycle_evidence(
    cur: Any,
    tenant_id: int,
    device_ids: list[uuid.UUID] | None = None,
    *,
    include_retired: bool = False,
) -> dict[uuid.UUID, dict[str, Any]]:
    """Qualified lifecycle evidence rows per Computer (all, or only ``device_ids``).

    ``include_retired`` is for restoring a retired Computer that reports again.
    """
    cur.execute(
        """
        SELECT d.id, d.client_id, d.lifecycle_status,
               apc.entity_type, apc.platform, et.lifecycle_evidence_mode,
               apc.last_contact_at, apc.last_observed_at,
               apc.last_power_state, apc.reported_online,
               COALESCE(latest.canonical_data ? 'power_state', FALSE)
                   AS has_power_state,
               COALESCE(
                   latest.canonical_data ? 'is_online'
                   OR latest.canonical_data ? 'offline',
                   FALSE
               ) AS has_reported_online_state
          FROM operations.devices d
          JOIN operations.device_agent_presence_current apc
            ON apc.tenant_id = d.tenant_id AND apc.device_id = d.id
          JOIN operations.entity_types et
            ON et.name = apc.entity_type
          LEFT JOIN LATERAL (
              SELECT o.canonical_data
                FROM operations.entity_observation_current o
               WHERE o.tenant_id = apc.tenant_id
                 AND o.device_id = apc.device_id
                 AND o.entity_type = apc.entity_type
                 AND o.platform = apc.platform
                 AND o.active
               ORDER BY o.observed_at DESC, o.observation_id DESC
               LIMIT 1
          ) latest ON TRUE
         WHERE d.tenant_id = %s
           AND d.deleted_at IS NULL
           AND (%s OR d.lifecycle_status <> 'retired')
           AND et.lifecycle_evidence_mode <> 'none'
           AND (%s::uuid[] IS NULL OR d.id = ANY(%s::uuid[]))
           AND EXISTS (
               SELECT 1
                 FROM operations.entity_observation_current current_observation
                WHERE current_observation.tenant_id = d.tenant_id
                  AND current_observation.device_id = d.id
                  AND current_observation.active
           )
        """,
        (tenant_id, include_retired, device_ids, device_ids),
    )
    per_device: dict[uuid.UUID, dict[str, Any]] = {}
    for row in cur.fetchall():
        (
            device_id,
            client_id,
            lifecycle_status,
            entity_type,
            platform,
            mode,
            last_contact_at,
            last_observed_at,
            last_power_state,
            reported_online,
            has_power_state,
            has_reported_online_state,
        ) = row
        device = per_device.setdefault(
            device_id,
            {
                "client_id": client_id,
                "lifecycle_status": lifecycle_status,
                "rows": [],
            },
        )
        device["rows"].append(
            {
                "entity_type": entity_type,
                "platform": platform,
                "mode": mode,
                "last_contact_at": last_contact_at,
                "last_observed_at": last_observed_at,
                "last_power_state": last_power_state,
                "reported_online": reported_online,
                "has_power_state": has_power_state,
                "has_reported_online_state": has_reported_online_state,
            }
        )
    return per_device


def _resolve_lifecycle_findings_absent(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    condition_keys: set[str],
    now: datetime,
    device_id: uuid.UUID | None = None,
) -> None:
    """Resolve only lifecycle findings no longer emitted in this evaluator run."""
    cur.execute("SELECT to_regclass('operations.condition_assessments') IS NOT NULL")
    if cur.fetchone()[0]:
        cur.execute(
            """
            SELECT id, subject_id, condition_key, status
              FROM operations.findings
             WHERE tenant_id = %s
               AND finding_type_id = %s
               AND status IN ('open', 'acknowledged')
               AND (%s::uuid IS NULL OR subject_id = %s)
               AND NOT (condition_key = ANY(%s))
            """,
            (tenant_id, finding_type_id, device_id, device_id, list(condition_keys)),
        )
        for finding_id, subject_id, condition_key, status in cur.fetchall():
            _record_lifecycle_assessment(
                cur,
                tenant_id,
                finding_id,
                finding_type_id,
                condition_key,
                subject_id,
                status,
                now,
            )
    if condition_keys:
        cur.execute(
            """
            UPDATE operations.findings
               SET status = 'resolved', last_seen_at = %s
             WHERE tenant_id = %s
               AND finding_type_id = %s
               AND status IN ('open', 'acknowledged')
               AND (%s::uuid IS NULL OR subject_id = %s)
               AND NOT (condition_key = ANY(%s))
               AND EXISTS (
                   SELECT 1
                     FROM operations.condition_assessments a
                     JOIN operations.condition_policy_versions p
                       ON p.version = a.policy_version
                      AND p.active
                    WHERE a.tenant_id = operations.findings.tenant_id
                      AND a.row_kind = 'entity'
                      AND a.finding_id = operations.findings.id
                      AND (a.response->>'may_clear')::boolean IS TRUE
                      AND a.assessed_at >= now() - (p.policy->>'freshness_hours')::integer * interval '1 hour'
               )
            """,
            (now, tenant_id, finding_type_id, device_id, device_id, list(condition_keys)),
        )
    else:
        cur.execute(
            """
            UPDATE operations.findings
               SET status = 'resolved', last_seen_at = %s
             WHERE tenant_id = %s
               AND finding_type_id = %s
               AND status IN ('open', 'acknowledged')
               AND (%s::uuid IS NULL OR subject_id = %s)
               AND EXISTS (
                   SELECT 1
                     FROM operations.condition_assessments a
                     JOIN operations.condition_policy_versions p
                       ON p.version = a.policy_version
                      AND p.active
                    WHERE a.tenant_id = operations.findings.tenant_id
                      AND a.row_kind = 'entity'
                      AND a.finding_id = operations.findings.id
                      AND (a.response->>'may_clear')::boolean IS TRUE
                      AND a.assessed_at >= now() - (p.policy->>'freshness_hours')::integer * interval '1 hour'
               )
            """,
            (now, tenant_id, finding_type_id, device_id, device_id),
        )


_LIFECYCLE_FINDING_ACTIVE_STATUSES = (
    "open",
    "acknowledged",
    "investigating",
    "suppressed",
)


def _upsert_lifecycle_finding(
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
    """Refresh one active lifecycle finding without changing operator state.

    The generic finding uniqueness rule covers only ``open`` and
    ``acknowledged`` rows. Lifecycle findings also remain active while an
    operator is investigating or has suppressed notifications, so refresh
    those rows explicitly before using the generic insert-or-reopen path.
    Resolved and won't-fix findings intentionally retain their history and a
    later recurrence opens a new row.
    """
    cur.execute(
        """
        UPDATE operations.findings
           SET confidence = %s,
               finding_details = %s::jsonb,
               last_seen_at = %s,
               last_detected_at = %s
         WHERE tenant_id = %s
           AND condition_key = %s
           AND status = ANY(%s)
        """,
        (
            confidence,
            json.dumps(details),
            now,
            now,
            tenant_id,
            condition_key,
            list(_LIFECYCLE_FINDING_ACTIVE_STATUSES),
        ),
    )
    if cur.rowcount:
        cur.execute(
            "SELECT id, status FROM operations.findings WHERE tenant_id=%s AND condition_key=%s",
            (tenant_id, condition_key),
        )
        finding_id, status = cur.fetchone()
    else:
        _upsert_finding(
            cur,
            tenant_id,
            finding_type_id,
            client_id,
            device_id,
            condition_key,
            severity,
            confidence,
            now,
            details,
        )
        cur.execute(
            "SELECT id, status FROM operations.findings WHERE tenant_id=%s AND condition_key=%s",
            (tenant_id, condition_key),
        )
        finding_id, status = cur.fetchone()
    _record_lifecycle_assessment(
        cur, tenant_id, finding_id, finding_type_id, condition_key, device_id, status, now
    )
    return 1


def _record_lifecycle_assessment(
    cur: Any,
    tenant_id: int,
    finding_id: uuid.UUID,
    finding_type_id: int,
    condition_key: str,
    device_id: uuid.UUID,
    status: str,
    now: datetime,
) -> None:
    """Persist measured source/lifecycle evidence for an active device finding."""
    cur.execute("SELECT to_regclass('operations.condition_assessments') IS NOT NULL")
    if not cur.fetchone()[0]:
        return
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM operations.findings conflict
              JOIN operations.finding_types conflict_type
                ON conflict_type.id = conflict.finding_type_id
             WHERE conflict.tenant_id = %s
               AND conflict_type.name = 'identity_conflict'
               AND conflict.status IN ('open', 'acknowledged', 'investigating')
               AND conflict.finding_details->'candidate_device_ids' @> jsonb_build_array(%s::text)
        )
        """,
        (tenant_id, str(device_id)),
    )
    identity_blocked = bool(cur.fetchone()[0])
    participant = Participant("device", str(device_id), "affected", tenant_id)
    condition = Condition(
        tenant_id,
        "entity",
        str(finding_id),
        _finding_type_name(cur, finding_type_id),
        condition_key,
        status,
        (participant,),
    )
    record_assessment(
        cur,
        condition,
        (
            Signal(
                "identity",
                participant,
                Readiness.BLOCKED if identity_blocked else Readiness.READY,
                "identity:unsettled_group"
                if identity_blocked
                else "identity:readiness_established",
            ),
            Signal("collection", participant, Readiness.READY, "collection:complete_snapshot"),
        ),
        EvaluationCoverage(True, True, True, True),
        now=now,
        reevaluation_key=f"evaluator:lifecycle:{condition_key}:{now.isoformat()}",
        participant=participant,
    )


def _sync_source_withdrawal_lifecycle(
    cur: Any,
    tenant_id: int,
    now: datetime,
    evaluator_run_id: uuid.UUID,
    device_id: uuid.UUID | None,
    owned: set[uuid.UUID] | None = None,
) -> int:
    """Set each Computer's lifecycle from what lists it now (ADR-0032).

    ``computer_listing`` decides the state. A Computer something reports for
    (or whose agents are only silent) gets the state the contact policy
    selects, in one transition. A Computer only documentation, a stopped VM or
    archived documentation still lists goes to review (``pending_cleanup``);
    one nothing lists any more is retired, and a retired Computer that reports
    again is restored. The ids whose lifecycle this step decided are added to
    ``owned``, so the contact policy later in the run leaves them alone (it
    would otherwise move a stopped VM straight back out of review).
    """
    offline_after_days, retire_review_days = device_status_settings.load(cur, tenant_id)
    client_offline_days = device_status_settings.client_overrides(cur, tenant_id)
    listings = computer_listing.load(cur, tenant_id, now, device_id)
    states = {item.device_id: item.state(now, retire_review_days) for item in listings}
    contact_ids = [
        item.device_id
        for item in listings
        if states[item.device_id] in computer_listing.CONTACT_POLICY_STATES
        and item.lifecycle_status != "active"
        and (item.lifecycle_status != "retired" or item.reporting)
    ]
    contact_evidence = (
        _load_lifecycle_evidence(cur, tenant_id, contact_ids, include_retired=True)
        if contact_ids
        else {}
    )

    affected = 0
    for item in listings:
        state = states[item.device_id]
        previous = item.lifecycle_status
        evidence = None
        if state == "retire":
            target = "retired"
        elif state in computer_listing.REVIEW_STATES:
            target = "pending_cleanup"
        elif previous == "retired" and not item.reporting:
            # A source lists it again but it does not report: stays retired.
            continue
        else:
            target = "active"
            device = contact_evidence.get(item.device_id)
            if device is not None:
                selected, has_conflict = _select_lifecycle_evidence(device["rows"])
                if selected is not None and not has_conflict:
                    evidence = selected
                    target = _device_lifecycle_target(
                        device,
                        selected,
                        now,
                        offline_after_days,
                        retire_review_days,
                        client_offline_days,
                    )
        if item.in_use_confirmed and item.reporting:
            _clear_in_use_confirmation(cur, tenant_id, item.device_id)
        if owned is not None and (state not in computer_listing.CONTACT_POLICY_STATES
                                  or previous == "retired"):
            owned.add(item.device_id)
        if target == previous:
            continue
        if _transition_lifecycle(
            cur, tenant_id, item, previous, target, state, evidence, now, evaluator_run_id
        ):
            affected += 1
    return affected


def _clear_in_use_confirmation(cur: Any, tenant_id: int, device_id: uuid.UUID) -> None:
    """The machine reports again: the operator's confirmation has done its job."""
    cur.execute(
        """
        UPDATE operations.device_operator_decisions
           SET value = 'false'::jsonb, reason = %s, set_by = 'ingest.evaluator',
               set_at = now(), version = version + 1
         WHERE tenant_id = %s AND device_id = %s AND dimension = 'in_use_confirmed'
           AND value = 'true'::jsonb
        """,
        ("Cleared: the machine reports again.", tenant_id, device_id),
    )


_RETIRE_REASONS = {
    "retire": "Nothing lists this machine any more (ADR-0032).",
}


def _transition_lifecycle(
    cur: Any,
    tenant_id: int,
    item: Any,
    previous: str,
    target: str,
    state: str,
    evidence: dict[str, Any] | None,
    now: datetime,
    evaluator_run_id: uuid.UUID,
) -> bool:
    """Apply one lifecycle change with its audit row; retire and restore are explicit actions."""
    explicit = "retired" in (previous, target)
    if explicit:
        retiring = target == "retired"
        cur.execute(
            "SELECT operations.begin_change(%s, %s, %s::jsonb, 'process', NULL::bigint, "
            "'ingest.evaluator', '', %s::bigint, true)",
            (
                "computer.retire.automatic" if retiring else "computer.restore.automatic",
                "Nothing lists this machine any more."
                if retiring
                else "A source reports this machine again.",
                json.dumps({"state": state, "last_source": item.last_source}),
                tenant_id,
            ),
        )
    try:
        cur.execute(
            """
            UPDATE operations.devices
               SET lifecycle_status = %s
             WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
               AND lifecycle_status = %s
            RETURNING entity_id
            """,
            (target, item.device_id, tenant_id, previous),
        )
        row = cur.fetchone()
        if row is None:
            return False
        if explicit:
            cur.execute(
                """
                UPDATE operations.entities
                   SET retired_at = CASE WHEN %s THEN %s::timestamptz END,
                       retired_reason = CASE WHEN %s THEN %s ELSE '' END,
                       updated_at = %s, updated_reason = %s
                 WHERE id = %s AND tenant_id = %s
                """,
                (
                    target == "retired",
                    now,
                    target == "retired",
                    _RETIRE_REASONS["retire"],
                    now,
                    "lifecycle.retire.automatic" if target == "retired" else "lifecycle.restore.automatic",
                    row[0],
                    tenant_id,
                ),
            )
        cur.execute(
            """
            INSERT INTO operations.audit_log (
                audit_id, tenant_id, actor_id, actor_kind, source, action,
                entity_type, entity_id, before_state, after_state,
                ip_address, user_agent, occurred_at
            ) VALUES (
                gen_random_uuid(), %s, NULL, 'system', 'ingest',
                'lifecycle.transition', 'device', %s, %s::jsonb, %s::jsonb,
                NULL, '', %s
            )
            """,
            (
                tenant_id,
                item.device_id,
                json.dumps({"lifecycle_status": previous}),
                json.dumps(
                    {
                        "lifecycle_status": target,
                        "evidence_kind": state,
                        **(
                            {
                                "contact_evidence_kind": evidence["kind"],
                                "evidence_at": evidence["at"].isoformat(),
                                "evidence_entity_type": evidence["entity_type"],
                                "evidence_platform": evidence["platform"],
                            }
                            if evidence is not None
                            else {}
                        ),
                        "policy_version": _LIFECYCLE_POLICY_VERSION,
                        "evaluator_run_id": str(evaluator_run_id),
                    }
                ),
                now,
            ),
        )
        return True
    finally:
        if explicit:
            # The action covers this Computer only; later evaluator writes are implicit.
            cur.execute("SELECT set_config('operations.change_action_id', '', true)")


def _sync_lifecycle_status(
    cur: Any,
    tenant_id: int,
    now: datetime,
    evaluator_run_id: uuid.UUID,
    skip: set[uuid.UUID] | None = None,
) -> int:  # noqa: PLR0912 - policy branches map to explicit approved outcomes.
    """Apply explicit lifecycle policy and append transition audit events.

    The registry supplies the only lifecycle capability. Direct contact never
    falls back to collection time; reported state uses collection time because
    that is the source observation time for the reported state. ``retired`` is
    an operator decision and is never selected for an automatic update.
    """
    offline_after_days, retire_review_days = device_status_settings.load(cur, tenant_id)
    client_offline_days = device_status_settings.client_overrides(cur, tenant_id)
    per_device = _load_lifecycle_evidence(cur, tenant_id)

    affected = 0
    unknown_keys: set[str] = set()
    conflict_keys: set[str] = set()
    unknown_type_id = _get_finding_type_id(cur, "lifecycle_unknown_reported_state")
    conflict_type_id = _get_finding_type_id(cur, "lifecycle_reported_state_conflict")

    for device_id, device in per_device.items():
        for row in device["rows"]:
            if row["mode"] not in _LIFECYCLE_REPORTED_MODES:
                continue
            _, is_unknown = _reported_lifecycle_state(
                row["last_power_state"],
                row["has_power_state"],
                row["reported_online"],
                row["has_reported_online_state"],
            )
            if not is_unknown:
                continue
            key = _condition_key(
                tenant_id,
                device["client_id"],
                device_id,
                "lifecycle_unknown_reported_state",
                f"{row['entity_type']}:{row['platform']}",
            )
            unknown_keys.add(key)
            if unknown_type_id is not None:
                affected += _upsert_lifecycle_finding(
                    cur,
                    tenant_id,
                    unknown_type_id,
                    device["client_id"],
                    device_id,
                    key,
                    "medium",
                    "confirmed",
                    now,
                    {
                        "reason": "unrecognized_reported_state",
                        "evidence_mode": row["mode"],
                        "entity_type": row["entity_type"],
                        "platform": row["platform"],
                        "reported_state_kind": (
                            "power_state" if row["has_power_state"] else "online_state"
                        ),
                    },
                )

        evidence, has_conflict = _select_lifecycle_evidence(device["rows"])
        if has_conflict:
            key = _condition_key(
                tenant_id,
                device["client_id"],
                device_id,
                "lifecycle_reported_state_conflict",
                "reported_state",
            )
            conflict_keys.add(key)
            if conflict_type_id is not None:
                affected += _upsert_lifecycle_finding(
                    cur,
                    tenant_id,
                    conflict_type_id,
                    device["client_id"],
                    device_id,
                    key,
                    "medium",
                    "confirmed",
                    now,
                    {"reason": "equally_recent_conflicting_reported_states"},
                )
            continue
        if evidence is None:
            continue
        if skip and device_id in skip:
            # computer_listing decided this Computer's lifecycle (review or retired).
            continue

        target = _device_lifecycle_target(
            device,
            evidence,
            now,
            offline_after_days,
            retire_review_days,
            client_offline_days,
        )
        previous = device["lifecycle_status"]
        if target == previous:
            continue
        cur.execute(
            """
            UPDATE operations.devices
               SET lifecycle_status = %s
             WHERE id = %s
               AND tenant_id = %s
               AND deleted_at IS NULL
               AND lifecycle_status = %s
               AND lifecycle_status <> 'retired'
            RETURNING id
            """,
            (target, device_id, tenant_id, previous),
        )
        if cur.fetchone() is None:
            continue
        cur.execute(
            """
            INSERT INTO operations.audit_log (
                audit_id, tenant_id, actor_id, actor_kind, source, action,
                entity_type, entity_id, before_state, after_state,
                ip_address, user_agent, occurred_at
            ) VALUES (
                gen_random_uuid(), %s, NULL, 'system', 'ingest',
                'lifecycle.transition', 'device', %s, %s::jsonb, %s::jsonb,
                NULL, '', %s
            )
            """,
            (
                tenant_id,
                device_id,
                json.dumps({"lifecycle_status": previous}),
                json.dumps(
                    {
                        "lifecycle_status": target,
                        "evidence_kind": evidence["kind"],
                        "evidence_at": evidence["at"].isoformat(),
                        "evidence_entity_type": evidence["entity_type"],
                        "evidence_platform": evidence["platform"],
                        "policy_version": _LIFECYCLE_POLICY_VERSION,
                        "evaluator_run_id": str(evaluator_run_id),
                    }
                ),
                now,
            ),
        )
        affected += 1

    if unknown_type_id is not None:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, unknown_type_id, unknown_keys, now
        )
    if conflict_type_id is not None:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, conflict_type_id, conflict_keys, now
        )
    if affected:
        log.info("lifecycle sync: %d transitions or findings updated", affected)
    return affected


# --------------------------------------------------------------------------
# 2c. Unmapped node_class surveillance (nothing dropped silently)
# --------------------------------------------------------------------------


def _evaluate_unknown_entities(cur: Any, tenant_id: int, now: datetime) -> int:
    """Admin finding per Ninja node_class that has no entity_type mapping."""
    ft_id = _get_finding_type_id(cur, "unmapped_node_class")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT COALESCE(canonical_data ->> 'node_class', '(none)'),
               COUNT(*)::int
        FROM operations.entity_observation_current
        WHERE tenant_id = %s AND entity_type = 'unknown'
          AND active = TRUE
          AND observed_at > now() - INTERVAL '2 days'
        GROUP BY 1
        """,
        (tenant_id,),
    )
    rows = cur.fetchall()
    count = 0
    present_keys: list[str] = []
    for node_class, n in rows:
        ckey = f"unmapped_node_class:{node_class}"
        present_keys.append(ckey)
        _upsert_admin_finding(
            cur,
            tenant_id,
            ft_id,
            ckey,
            "medium",
            now,
            {"node_class": node_class},
            {"recent_observations": n},
        )
        count += 1
    cur.execute(
        """
        UPDATE operations.admin_findings
        SET status = 'resolved', resolved_at = %s
        WHERE tenant_id = %s AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
          AND EXISTS (
              SELECT 1 FROM operations.condition_assessments a
               WHERE a.tenant_id = operations.admin_findings.tenant_id
                 AND a.row_kind = 'admin'
                 AND a.finding_id = operations.admin_findings.id
                 AND (a.response->>'may_clear')::boolean IS TRUE
                 AND a.policy_version = (SELECT version FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
                 AND a.assessed_at >= now() - (SELECT (policy->>'freshness_hours')::integer * interval '1 hour' FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
          )
        """,
        (now, tenant_id, ft_id, present_keys),
    )
    return count


# --------------------------------------------------------------------------
# 2c'. Change-history registry coverage (ADR-0033: nothing unrecorded by accident)
# --------------------------------------------------------------------------


def _evaluate_change_history_registry(cur: Any, tenant_id: int, now: datetime) -> int:
    """Admin finding per operations table missing from the change history registry."""
    ft_id = _get_finding_type_id(cur, "change_history_unclassified")
    if ft_id is None:
        return 0
    cur.execute(
        "SELECT to_regprocedure('operations.change_history_unclassified()') IS NOT NULL"
    )
    if not cur.fetchone()[0]:
        return 0
    cur.execute("SELECT * FROM operations.change_history_unclassified()")
    tables = [row[0] for row in cur.fetchall()]
    present_keys = [f"change_history_unclassified:{table}" for table in tables]
    for table, ckey in zip(tables, present_keys, strict=True):
        _upsert_admin_finding(
            cur,
            tenant_id,
            ft_id,
            ckey,
            "medium",
            now,
            {"table": f"operations.{table}"},
            {"table": f"operations.{table}"},
            measured=True,
        )
    cur.execute(
        """
        UPDATE operations.admin_findings
        SET status = 'resolved', resolved_at = %s
        WHERE tenant_id = %s AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
          AND EXISTS (
              SELECT 1 FROM operations.condition_assessments a
               WHERE a.tenant_id = operations.admin_findings.tenant_id
                 AND a.row_kind = 'admin'
                 AND a.finding_id = operations.admin_findings.id
                 AND (a.response->>'may_clear')::boolean IS TRUE
                 AND a.policy_version = (SELECT version FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
                 AND a.assessed_at >= now() - (SELECT (policy->>'freshness_hours')::integer * interval '1 hour' FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
          )
        """,
        (now, tenant_id, ft_id, present_keys),
    )
    return len(tables)


# --------------------------------------------------------------------------
# 2d. Same-stream hostname duplicates (license-consuming rows, never merged)
# --------------------------------------------------------------------------


def _evaluate_duplicate_records(cur: Any, tenant_id: int, now: datetime) -> int:
    """Admin finding per Computer holding two records of one source (ADR-0032).

    Agent and VM records: two or more active records of one source and type on
    one Computer, unless their usable serials differ (two machines, a
    different finding). Hudu: two or more current (not archived) assets of one
    layout with the same name on one Computer, unless their serials differ;
    an archived asset beside a current one is replaced documentation, and a
    Computer page beside a Servers page is normal.
    """
    ft_id = _get_finding_type_id(cur, "duplicate_platform_record")
    if ft_id is None:
        return 0
    # Serials decide which groups are duplicates; without the rejection list
    # every serial reads as unusable, so skip rather than guess.
    load_identity_value_rejections(cur)
    if normalize._serial_rejection_cache is None:
        log.warning("evaluator: serial rejections unavailable, duplicate records skipped")
        return 0
    cur.execute(
        """
        SELECT eo.device_id, d.client_id, d.canonical_hostname, eo.platform, eo.entity_type,
               CASE WHEN eo.entity_type = 'cmdb.asset'
                    THEN coalesce(eo.canonical_data ->> 'hudu_layout', '') || ':'
                         || lower(coalesce(eo.canonical_data ->> 'hostname', ''))
                    ELSE '' END AS page_group,
               eo.entity_key, eo.canonical_data ->> 'hostname',
               eo.canonical_data ->> 'is_online', eo.last_seen_at,
               eo.canonical_data ->> 'serial_number'
          FROM operations.entity_observation_current eo
          JOIN operations.devices d ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
         WHERE eo.tenant_id = %s AND eo.active AND d.deleted_at IS NULL
           AND eo.entity_key NOT LIKE 'device-health:%%'
           AND (eo.entity_type LIKE 'agent.%%' OR eo.entity_type LIKE 'vm.%%'
                OR (eo.entity_type = 'cmdb.asset'
                    AND coalesce((eo.canonical_data ->> 'archived')::boolean, false) = false
                    AND coalesce(eo.canonical_data ->> 'hostname', '') <> ''))
        """,
        (tenant_id,),
    )
    groups: dict[tuple, list[dict]] = {}
    for (
        device_id,
        client_id,
        computer_name,
        platform,
        entity_type,
        page_group,
        entity_key,
        hostname,
        is_online,
        last_seen,
        serial,
    ) in cur.fetchall():
        groups.setdefault(
            (device_id, client_id, computer_name, platform, entity_type, page_group), []
        ).append(
            {
                "entity_key": entity_key,
                "hostname": hostname,
                "is_online": is_online,
                "last_seen_at": last_seen.isoformat() if last_seen else None,
                "serial_number": serial,
            }
        )

    count = 0
    present_keys: list[str] = []
    for (device_id, client_id, computer_name, platform, entity_type, page_group), records in (
        groups.items()
    ):
        if len(records) < 2:
            continue
        serials = {
            r["serial_number"].strip().lower()
            for r in records
            if is_usable_serial(r["serial_number"])
        }
        if len(serials) > 1:
            continue
        ckey = f"duplicate_platform_record:{device_id}:{platform}:{entity_type}:{page_group}"
        present_keys.append(ckey)
        severity = "high" if entity_type.startswith("agent.") else "low"
        records.sort(key=lambda r: r["last_seen_at"] or "", reverse=True)
        _upsert_admin_finding(
            cur,
            tenant_id,
            ft_id,
            ckey,
            severity,
            now,
            {
                "device_id": str(device_id),
                "platform": platform,
                "entity_type": entity_type,
                "hostname": computer_name,
                "client_id": str(client_id),
            },
            {
                "record_count": len(records),
                "entity_keys": [r["entity_key"] for r in records],
                "records": records,
                "offline_count": sum(1 for r in records if r["is_online"] in ("false", "False")),
            },
            measured=True,
        )
        count += 1
    cur.execute(
        """
        UPDATE operations.admin_findings
        SET status = 'resolved', resolved_at = %s
        WHERE tenant_id = %s AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
          AND EXISTS (
              SELECT 1 FROM operations.condition_assessments a
               WHERE a.tenant_id = operations.admin_findings.tenant_id
                 AND a.row_kind = 'admin'
                 AND a.finding_id = operations.admin_findings.id
                 AND (a.response->>'may_clear')::boolean IS TRUE
                 AND a.policy_version = (SELECT version FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
                 AND a.assessed_at >= now() - (SELECT (policy->>'freshness_hours')::integer * interval '1 hour' FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
          )
        """,
        (now, tenant_id, ft_id, present_keys),
    )
    return count


# --------------------------------------------------------------------------
# 3. Coverage
# --------------------------------------------------------------------------


def _load_corroborated_devices(cur: Any, tenant_id: int) -> set[uuid.UUID]:
    """Devices some source saw online recently — allows 'confirmed' gaps."""
    cur.execute(
        """
        SELECT DISTINCT device_id
        FROM operations.entity_observation_history
        WHERE tenant_id = %s AND device_id IS NOT NULL
          AND effective_from <= now()
          AND (effective_to IS NULL OR effective_to > now() - %s::interval)
          AND material_data ->> 'is_online' = 'true'
        """,
        (tenant_id, f"{_CORROBORATION_WINDOW_HOURS} hours"),
    )
    return {row[0] for row in cur.fetchall()}


def _evaluate_coverage(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
    source_problems: list[SourceCollectionProblem],
    corroborated: set[uuid.UUID],
) -> int:
    """Emit coverage findings from baseline requirements plus client overrides.

    A client-scoped ``coverage_requirements`` row is a sparse override:
    enabled adds/replaces a service requirement and disabled explicitly removes
    it.  With no override, the client inherits its profile; clients without a
    profile inherit tenant-global requirements.  This keeps profiles reusable
    while allowing a client to require or exempt one service independently.
    """
    # Agent reference: id → (name, entity_type, supported_os_groups)
    cur.execute(
        """
        SELECT id, name, entity_type, supported_os_groups
        FROM operations.agents
        """
    )
    agents_by_id: dict[int, tuple] = {
        row[0]: (row[1], row[2], row[3] or []) for row in cur.fetchall()
    }

    # Global rows (fallback for clients without a profile). Tuple shape:
    #   (id, client_id, agent_id, entity_type, platform, scope, applicable_os_groups,
    #    severity, gap, prob, conf)
    cur.execute(
        """
        SELECT id, client_id, agent_id, entity_type, platform, device_scope,
               applicable_os_groups,
               severity, gap_after_hours, confidence_probable, confidence_confirmed
        FROM operations.coverage_requirements
        WHERE tenant_id = %s AND enabled = TRUE AND client_id IS NULL
        """,
        (tenant_id,),
    )
    global_rows = cur.fetchall()

    # Client rows deliberately include disabled entries: a disabled row is an
    # explicit "not required" override, not an inactive row to discard.
    cur.execute(
        """
        SELECT id, client_id, agent_id, entity_type, platform, device_scope,
               applicable_os_groups,
               severity, gap_after_hours, confidence_probable, confidence_confirmed,
               enabled
        FROM operations.coverage_requirements
        WHERE tenant_id = %s AND client_id IS NOT NULL
        """,
        (tenant_id,),
    )
    client_override_rows = cur.fetchall()

    # Profile-based tiers.
    cur.execute(
        """
        SELECT rpi.profile_id, NULL::uuid AS id, NULL AS client_id,
               rpi.agent_id, rpi.entity_type, rpi.platform, rpi.device_scope,
               rpi.applicable_os_groups,
               rpi.severity, rpi.gap_after_hours,
               rpi.confidence_probable, rpi.confidence_confirmed
        FROM operations.requirement_profile_items rpi
        WHERE rpi.tenant_id = %s
        """,
        (tenant_id,),
    )
    profile_rows = cur.fetchall()

    # profile_id → scope → list of item tuples
    profile_tiers: dict[Any, dict[str, list[tuple]]] = {}
    for pid, _id, _cid, agent_id, entity_type, platform, scope, aog, *rest in profile_rows:
        profile_tiers.setdefault(pid, {}).setdefault(scope, []).append(
            (None, None, agent_id, entity_type, platform, scope, aog, *rest)
        )

    global_tiers: dict[str, list[tuple]] = {}
    for row in global_rows:
        scope = row[5]
        global_tiers.setdefault(scope, []).append(row)

    client_override_tiers: dict[Any, dict[str, list[tuple]]] = {}
    for row in client_override_rows:
        client_override_tiers.setdefault(row[1], {}).setdefault(row[5], []).append(row)

    # client_id → profile_id
    cur.execute(
        """
        SELECT id, requirement_profile_id
        FROM operations.clients
        WHERE tenant_id = %s AND deleted_at IS NULL
        """,
        (tenant_id,),
    )
    client_profile: dict[Any, Any] = {row[0]: row[1] for row in cur.fetchall()}

    if not global_rows and not profile_rows and not client_override_rows:
        return 0

    def resolve_tier(dev_client_id, dev_role: str) -> list[tuple]:
        profile_id = client_profile.get(dev_client_id)
        if profile_id is not None:
            scopes = profile_tiers.get(profile_id, {})
            baseline = scopes.get(dev_role) or scopes.get("all") or []
        else:
            baseline = global_tiers.get(dev_role) or global_tiers.get("all") or []

        # Apply broad overrides before role-specific overrides, so a scoped
        # decision can intentionally refine a client-wide decision.
        overrides = client_override_tiers.get(dev_client_id, {})
        override_rows = list(overrides.get("all", []))
        if dev_role != "all":
            override_rows.extend(overrides.get(dev_role, []))
        return _apply_requirement_overrides(baseline, override_rows)

    missing_ft = _get_finding_type_id(cur, "missing_required_platform")
    stale_ft = _get_finding_type_id(cur, "stale_required_platform")
    if missing_ft is None:
        log.warning("evaluator: finding_type 'missing_required_platform' not found")
        return 0
    offline_after_days, _retire_review_days = device_status_settings.load(cur, tenant_id)
    client_days = device_status_settings.override_expression(cur, "c")
    identity_blocked = _identity_blocked_devices(cur, tenant_id)

    # Pre-compute devices that are fully offline (last contact across
    # ALL agents older than the device_offline threshold). Per
    # BLUEPRINT §1.8, `stale_required_platform` should NOT fire on
    # such devices — the device-level `device_offline` finding covers
    # them, and per-agent stale is redundant noise when the whole
    # device is silent. `missing_required_platform` STILL fires on
    # offline devices (the agent was never installed, that's a real
    # gap regardless of current online state).
    cur.execute(
        f"""
        SELECT apc.device_id
        FROM operations.device_agent_presence_current apc
        JOIN operations.devices dv
          ON dv.id = apc.device_id AND dv.tenant_id = apc.tenant_id
        LEFT JOIN operations.clients c ON c.id = dv.client_id
        WHERE apc.tenant_id = %s
          AND apc.entity_type LIKE 'agent.%%'
        GROUP BY apc.device_id, {client_days}
        HAVING MAX(COALESCE(apc.last_contact_at, apc.last_observed_at))
             < NOW() - make_interval(days => COALESCE({client_days}, %s))
        """,
        (tenant_id, offline_after_days),
    )
    fully_offline_devices = {r[0] for r in cur.fetchall()}

    # Pull every device + agent-universe flag once. Exemptions come from
    # device_operator_decisions (Track O batch O3 — polymorphic operator
    # decisions storage). Empty {} if no row.
    cur.execute(
        """
        SELECT d.id, d.client_id, d.canonical_hostname, d.device_role,
               COALESCE(op.value, '{}'::jsonb) AS exemptions,
               d.os_group,
               (EXISTS(SELECT 1 FROM operations.device_agent_presence_current apc
                       WHERE apc.tenant_id = d.tenant_id AND apc.device_id = d.id
                         AND apc.entity_type LIKE 'agent.%%')
                -- ADR-0032: an operator confirmed it in use although no agent
                -- is left, so every required agent is reported missing.
                OR EXISTS(SELECT 1 FROM operations.device_operator_decisions dec
                          WHERE dec.tenant_id = d.tenant_id AND dec.device_id = d.id
                            AND dec.dimension = 'in_use_confirmed'
                            AND dec.value = 'true'::jsonb)) AS in_agent_universe
        FROM operations.devices d
        LEFT JOIN operations.device_operator_decisions op
          ON op.tenant_id = d.tenant_id
         AND op.device_id = d.id
         AND op.dimension = 'exemptions'
        WHERE d.tenant_id = %s
          AND d.deleted_at IS NULL
          AND d.lifecycle_status != 'retired'
          AND (%s::uuid IS NULL OR d.id = %s)
        """,
        (tenant_id, device_id, device_id),
    )
    devices = cur.fetchall()

    count = 0
    for dev_id, dev_client_id, hostname, dev_role, exemptions, os_group, in_universe in devices:
        exemptions = exemptions or {}
        # BLUEPRINT E.6: coverage evaluates against entity types. A device
        # with zero agent.* observations is not in the coverage universe —
        # it's a hypervisor / NMS tracking record. Skipped here; picked up
        # by _evaluate_unenrolled instead.
        if not in_universe:
            continue
        tier_rows = resolve_tier(dev_client_id, dev_role or "all")
        for (
            _rid,
            _rclient,
            agent_id,
            entity_type,
            platform,
            _rscope,
            aog,
            severity,
            gap_hours,
            prob_hours,
            conf_hours,
        ) in tier_rows:
            if entity_type in exemptions:
                continue
            # Agent physics: skip if device's os_group isn't in the
            # supported set (LMI on Linux etc). applicable_os_groups on
            # the item narrows further if set; else falls to the Agent's
            # supported_os_groups.
            allowed_groups = None
            if aog:
                allowed_groups = set(aog)
            elif agent_id and agent_id in agents_by_id:
                allowed_groups = set(agents_by_id[agent_id][2])
            if allowed_groups is not None and os_group not in allowed_groups:
                continue

            # Per-device presence for this (entity_type, platform), 'any'
            # honored (BLUEPRINT C.6 wildcard).
            # BLUEPRINT E.6: staleness uses platform LAST CONTACT, not our
            # fetch time. `last_observed_at` is when WE polled the source
            # API — always recent; `last_contact_at` is when the source
            # last heard from the DEVICE. Fall back only when contact is
            # unpopulated (some sources don't distinguish).
            cur.execute(
                """
                SELECT MAX(COALESCE(apc.last_contact_at, apc.last_observed_at))
                FROM operations.device_agent_presence_current apc
                WHERE apc.tenant_id = %s AND apc.device_id = %s
                  AND apc.entity_type = %s
                  AND (%s = 'any' OR apc.platform = %s)
                """,
                (tenant_id, dev_id, entity_type, platform, platform),
            )
            (last_observed,) = cur.fetchone()
            collection_blockers = blockers_for_platform(
                source_problems, platform, dev_client_id
            )

            # BLUEPRINT 1.4 split:
            #   MISSING (last_observed IS NULL) → emit immediately.
            #   STALE (present but past gap_hours) → confidence ladder.
            offline_downgrade = dev_id in fully_offline_devices
            if last_observed is None:
                confidence = "confirmed" if dev_id in corroborated else "probable"
                ftype, ft_name, sev = missing_ft, "missing_required_platform", severity
            else:
                if last_observed.tzinfo is None:
                    last_observed = last_observed.replace(tzinfo=timezone.utc)
                gap_age_hours = (now - last_observed).total_seconds() / 3600
                if gap_age_hours < gap_hours:
                    continue
                if gap_age_hours >= conf_hours:
                    confidence = "confirmed"
                elif gap_age_hours >= prob_hours:
                    confidence = "probable"
                else:
                    confidence = "possible"
                if confidence == "confirmed" and dev_id not in corroborated:
                    confidence = "probable"
                if stale_ft is None:
                    continue
                ftype, ft_name, sev = stale_ft, "stale_required_platform", "medium"

            # If the whole device is offline (all agents silent past
            # the device_offline threshold), the device-level
            # `device_offline` finding is the actionable signal. Keep
            # the per-agent missing / stale finding VISIBLE — operators
            # still want to see which agent is missing on an offline
            # device — but demote severity to `info` and mark
            # `finding_details.reason_suppressed='device_offline'` so
            # the queue can filter it out and the label can hint at
            # the offline context. Previously suppressed entirely
            # (BLUEPRINT §1.8 pre-2026-07-21).
            details = {"entity_type": entity_type, "platform": platform, "hostname": hostname}
            if offline_downgrade:
                sev = "info"
                details["reason_suppressed"] = "device_offline"

            ckey = _condition_key(tenant_id, dev_client_id, dev_id, ft_name, platform)
            count += _upsert_finding(
                cur,
                tenant_id,
                ftype,
                dev_client_id,
                dev_id,
                ckey,
                sev,
                confidence,
                now,
                details,
                assessment=(
                    _device_condition_signals(
                        tenant_id,
                        dev_id,
                        identity_blocked,
                        offline=offline_downgrade,
                        collection_skipped=bool(collection_blockers),
                        collection_blockers=collection_blockers,
                    ),
                    EvaluationCoverage(
                        not collection_blockers,
                        not collection_blockers,
                        not collection_blockers,
                        not collection_blockers,
                    ),
                ),
            )

    return count


# --------------------------------------------------------------------------
# 3b. Unenrolled devices (outside agent universe)
# --------------------------------------------------------------------------


def _evaluate_unenrolled(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Emit `device_unenrolled` for devices tracked by hypervisor / NMS /
    monitor sources but never observed as an agent target.

    finding_details pulls power_state, hypervisor host, last_boot_time,
    last observation timestamp from the latest vm.guest / vm.host /
    network.device / monitor.target observation, so the operator has
    triage data (running vs powered off, hypervisor host name, when it
    was last seen).
    """
    ft_id = _get_finding_type_id(cur, "device_unenrolled")
    if ft_id is None:
        return 0

    cur.execute(
        """
        WITH latest_tracking AS (
            SELECT DISTINCT ON (eo.device_id)
                   eo.device_id, eo.entity_type, eo.observed_at,
                   eo.canonical_data
            FROM operations.entity_observation_current eo
            WHERE eo.tenant_id = %s
              AND eo.device_id IS NOT NULL
              AND eo.active = TRUE
              AND eo.entity_type IN ('vm.guest', 'vm.host', 'network.device',
                                     'monitor.target')
            ORDER BY eo.device_id, eo.observed_at DESC
        )
        SELECT d.id, d.client_id, d.canonical_hostname, d.device_type,
               lt.entity_type, lt.observed_at, lt.canonical_data
        FROM operations.devices d
        JOIN latest_tracking lt ON lt.device_id = d.id
        WHERE d.tenant_id = %s
          AND d.deleted_at IS NULL
          AND d.lifecycle_status != 'retired'
          AND (%s::uuid IS NULL OR d.id = %s)
          AND NOT EXISTS(
              SELECT 1 FROM operations.device_agent_presence_current apc
              WHERE apc.tenant_id = d.tenant_id AND apc.device_id = d.id
                AND apc.entity_type LIKE 'agent.%%'
          )
        """,
        (tenant_id, tenant_id, device_id, device_id),
    )
    unenrolled = cur.fetchall()

    count = 0
    identity_blocked = _identity_blocked_devices(cur, tenant_id)
    for dev_id, dev_client_id, hostname, device_type, entity_type, obs_at, cd in unenrolled:
        cd = cd or {}
        if obs_at and obs_at.tzinfo is None:
            obs_at = obs_at.replace(tzinfo=timezone.utc)
        days = int((now - obs_at).total_seconds() // 86400) if obs_at else None
        details = {
            "hostname": hostname,
            "device_type": device_type,
            "observed_via": entity_type,
            "power_state": cd.get("power_state"),
            "parent_ninja_id": cd.get("parent_ninja_id"),
            "last_boot_time_at": cd.get("last_boot_time_at"),
            "last_observed_at": obs_at.isoformat() if obs_at else None,
            "days_since_last_seen": days,
        }
        ckey = _condition_key(
            tenant_id,
            dev_client_id,
            dev_id,
            "device_unenrolled",
            "",
        )
        count += _upsert_finding(
            cur,
            tenant_id,
            ft_id,
            dev_client_id,
            dev_id,
            ckey,
            "medium",
            "confirmed",
            now,
            details,
            assessment=(
                _device_condition_signals(
                    tenant_id,
                    dev_id,
                    identity_blocked,
                    offline=False,
                    collection_skipped=obs_at is None,
                ),
                EvaluationCoverage(
                    obs_at is not None,
                    obs_at is not None,
                    obs_at is not None,
                    obs_at is not None,
                ),
            ),
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
    source_problems: list[SourceCollectionProblem],
) -> int:
    """Withdrawal review, offline, and stale-data findings."""
    count = 0

    source_withdrawn_type_id = _get_finding_type_id(
        cur, "device_source_record_withdrawn"
    )
    source_withdrawn_keys: set[str] = set()
    if source_withdrawn_type_id:
        threshold = now - timedelta(hours=_DEVICE_MISSING_MIN_AGE_HOURS)
        cur.execute(
            """
            SELECT d.id, d.client_id, source.name, link.external_id, link.missing_since
              FROM operations.devices d
              JOIN operations.v_device_source_link link
                ON link.device_id = d.id AND link.tenant_id = d.tenant_id
              JOIN operations.sources source ON source.id = link.source_id
             WHERE d.tenant_id = %s
               AND d.deleted_at IS NULL
               AND link.missing_since IS NOT NULL
               AND link.missing_since <= %s
               AND (%s::uuid IS NULL OR d.id = %s)
            """,
            (tenant_id, threshold, device_id, device_id),
        )
        for dev_id, dev_client_id, source_name, external_id, withdrawn_at in cur.fetchall():
            ckey = _condition_key(
                tenant_id,
                dev_client_id,
                dev_id,
                "device_source_record_withdrawn",
                f"{source_name}:{external_id}",
            )
            source_withdrawn_keys.add(ckey)
            count += _upsert_lifecycle_finding(
                cur,
                tenant_id,
                source_withdrawn_type_id,
                dev_client_id,
                dev_id,
                ckey,
                "medium",
                "confirmed",
                now,
                {
                    "source": source_name,
                    "external_id": external_id,
                    "withdrawn_at": withdrawn_at.isoformat() if withdrawn_at else None,
                },
            )

    # ADR-0032: what still lists a Computer that nothing reports for. One
    # finding per Computer; its reason follows the state (each change is
    # recorded in the finding's history).
    missing_type_id = _get_finding_type_id(cur, "device_missing_from_source")
    archived_type_id = _get_finding_type_id(cur, "archived_but_reporting")
    no_current_evidence_keys: set[str] = set()
    archived_keys: set[str] = set()
    if missing_type_id or archived_type_id:
        _offline_days, review_days = device_status_settings.load(cur, tenant_id)
        for item in computer_listing.load(cur, tenant_id, now, device_id):
            state = item.state(now, review_days)
            details = {
                "last_source": item.last_source,
                "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
            }
            if missing_type_id and state in computer_listing.CLEANUP_STATES:
                ckey = _condition_key(
                    tenant_id, item.client_id, item.device_id, "device_missing_from_source", ""
                )
                no_current_evidence_keys.add(ckey)
                count += _upsert_lifecycle_finding(
                    cur, tenant_id, missing_type_id, item.client_id, item.device_id, ckey,
                    "high", "confirmed", now,
                    {"reason": computer_listing.CLEANUP_REASONS[state], **details},
                )
            elif archived_type_id and state == "archived_but_reporting":
                ckey = _condition_key(
                    tenant_id, item.client_id, item.device_id, "archived_but_reporting", ""
                )
                archived_keys.add(ckey)
                count += _upsert_lifecycle_finding(
                    cur, tenant_id, archived_type_id, item.client_id, item.device_id, ckey,
                    "medium", "confirmed", now, details,
                )

    if source_withdrawn_type_id:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, source_withdrawn_type_id, source_withdrawn_keys, now, device_id
        )
    if missing_type_id:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, missing_type_id, no_current_evidence_keys, now, device_id
        )
    if archived_type_id:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, archived_type_id, archived_keys, now, device_id
        )

    if device_id is None:
        count += _evaluate_device_offline(cur, tenant_id, now)
        count += _evaluate_stale_data(cur, tenant_id, now, source_problems)
    return count


def _evaluate_device_offline(cur: Any, tenant_id: int, now: datetime) -> int:
    """Device is unreachable via EVERY agent source (BLUEPRINT §1.8).

    Fires when a device has agent presence rows but the most recent
    platform last-contact across ALL agents is older than the threshold
    — i.e., no source is hearing the device.

    This is device-level truth. A device where one agent (say Ninja)
    stopped talking while others (S1/LMI) are still in contact is NOT
    "offline" — it's a per-source staleness case handled by
    `stale_required_platform` with `platform=<source>` in details.
    """
    ft_id = _get_finding_type_id(cur, "device_offline")
    if ft_id is None:
        return 0
    offline_after_days, _retire_review_days = device_status_settings.load(cur, tenant_id)
    client_days = device_status_settings.override_expression(cur, "c")
    identity_blocked = _identity_blocked_devices(cur, tenant_id)
    # Per-platform last-seen is preserved as evidence on the finding
    # so operators triaging a fully-offline device can see the exact
    # timeline ("went dark on Ninja 7/10 → SentinelOne 7/12 →
    # ScreenConnect 7/14 → fully offline since 7/14") without
    # having to click through to the device detail Sources tab.
    cur.execute(
        f"""
        WITH per_platform AS (
            SELECT tenant_id, device_id, platform,
                   MAX(COALESCE(last_contact_at, last_observed_at)) AS last_seen
            FROM operations.device_agent_presence_current
            WHERE tenant_id = %s
              AND entity_type LIKE 'agent.%%'
            GROUP BY tenant_id, device_id, platform
        )
        SELECT pp.device_id, d.client_id, d.canonical_hostname,
               MAX(pp.last_seen) AS overall_last,
               jsonb_object_agg(pp.platform, pp.last_seen) AS per_source
        FROM per_platform pp
        JOIN operations.devices d
             ON d.id = pp.device_id AND d.tenant_id = pp.tenant_id
        LEFT JOIN operations.clients c ON c.id = d.client_id
        WHERE d.deleted_at IS NULL
          AND d.lifecycle_status <> 'retired'
        GROUP BY pp.device_id, d.client_id, d.canonical_hostname, {client_days}
        HAVING MAX(pp.last_seen) < NOW() - make_interval(days => COALESCE({client_days}, %s))
        """,
        (tenant_id, offline_after_days),
    )
    count = 0
    offenders: list[uuid.UUID] = []
    for dev_id, client_id, hostname, overall_last, per_source in cur.fetchall():
        offenders.append(dev_id)
        # per_source is a dict {platform: iso_ts_string}; identify the
        # source that held on longest (== overall_last).
        last_seen_source = None
        if isinstance(per_source, dict) and per_source:
            last_seen_source = max(per_source, key=lambda k: per_source[k] or "")
        ckey = _condition_key(tenant_id, client_id, dev_id, "device_offline", "")
        count += _upsert_finding(
            cur,
            tenant_id,
            ft_id,
            client_id,
            dev_id,
            ckey,
            "medium",
            "confirmed",
            now,
            {
                "hostname": hostname,
                "last_contact_at": overall_last.isoformat() if overall_last else None,
                "fully_offline_since": overall_last.isoformat() if overall_last else None,
                "source_last_seen": per_source or {},
                "last_seen_source": last_seen_source,
            },
            assessment=(
                (
                    Signal(
                        "identity",
                        Participant("device", str(dev_id), "affected", tenant_id),
                        Readiness.BLOCKED if dev_id in identity_blocked else Readiness.UNKNOWN,
                        "identity:unsettled_group"
                        if dev_id in identity_blocked
                        else "identity:readiness_not_established",
                    ),
                    Signal(
                        "offline",
                        Participant("device", str(dev_id), "affected", tenant_id),
                        Readiness.BLOCKED,
                        "offline:extended_absence",
                    ),
                ),
                EvaluationCoverage(True, True, True, True),
            ),
        )
    _resolve_findings_absent(
        cur, tenant_id, ft_id, offenders, now, assessment_required=True
    )
    return count


def _identity_blocked_devices(cur: Any, tenant_id: int) -> set[uuid.UUID]:
    cur.execute(
        """
        SELECT CASE
                   WHEN member.value ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                   THEN member.value::uuid
               END
        FROM operations.findings f
        JOIN operations.finding_types ft ON ft.id = f.finding_type_id
        CROSS JOIN LATERAL jsonb_array_elements_text(
            f.finding_details -> 'candidate_device_ids'
        ) AS member(value)
        WHERE f.tenant_id = %s
          AND ft.name = 'identity_conflict'
          AND f.status IN ('open', 'acknowledged', 'investigating')
        """,
        (tenant_id,),
    )
    return {row[0] for row in cur.fetchall() if row[0] is not None}


def _device_condition_signals(
    tenant_id: int,
    device_id: uuid.UUID,
    identity_blocked: set[uuid.UUID],
    *,
    offline: bool,
    collection_skipped: bool,
    collection_blockers: tuple[str, ...] = (),
) -> tuple[Signal, ...]:
    participant = Participant("device", str(device_id), "affected", tenant_id)
    return (
        Signal(
            "identity",
            participant,
            Readiness.BLOCKED if device_id in identity_blocked else Readiness.READY,
            "identity:unsettled_group"
            if device_id in identity_blocked
            else "identity:readiness_established",
        ),
        Signal(
            "collection",
            participant,
            Readiness.BLOCKED if collection_skipped else Readiness.READY,
            "collection:incomplete_or_stale"
            if collection_skipped
            else "collection:complete_snapshot",
            collection_blockers,
        ),
        Signal(
            "offline",
            participant,
            Readiness.BLOCKED if offline else Readiness.READY,
            "offline:extended_absence" if offline else "offline:contact_current",
        ),
    )


def _evaluate_stale_data(
    cur: Any,
    tenant_id: int,
    now: datetime,
    source_problems: list[SourceCollectionProblem],
) -> int:
    """Devices no source has observed at all in the stale window."""
    ft_id = _get_finding_type_id(cur, "device_stale_data")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT apc.device_id, d.client_id, d.canonical_hostname,
               MAX(apc.last_observed_at), ARRAY_AGG(DISTINCT apc.platform)
        FROM operations.device_agent_presence_current apc
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
    identity_blocked = _identity_blocked_devices(cur, tenant_id)
    for dev_id, client_id, hostname, last_observed, platforms in cur.fetchall():
        offenders.append(dev_id)
        collection_blockers = tuple(
            dict.fromkeys(
                blocker
                for platform in platforms or []
                for blocker in blockers_for_platform(source_problems, platform, client_id)
            )
        )
        ckey = _condition_key(tenant_id, client_id, dev_id, "device_stale_data", "")
        count += _upsert_finding(
            cur,
            tenant_id,
            ft_id,
            client_id,
            dev_id,
            ckey,
            "low",
            "confirmed",
            now,
            {
                "hostname": hostname,
                "last_observed_at": last_observed.isoformat() if last_observed else None,
            },
            assessment=(
                _device_condition_signals(
                    tenant_id,
                    dev_id,
                    identity_blocked,
                    offline=False,
                    collection_skipped=bool(collection_blockers),
                    collection_blockers=collection_blockers,
                ),
                EvaluationCoverage(
                    not collection_blockers,
                    not collection_blockers,
                    not collection_blockers,
                    not collection_blockers,
                ),
            ),
        )
    _resolve_findings_absent(
        cur, tenant_id, ft_id, offenders, now, assessment_required=True
    )
    return count


# cross_client_conflict emitter removed 2026-07-14.
# The finding was a legacy-AC port: "hostname X exists under multiple
# clients → possible identity issue." In the operations resolver the
# only way two devices can end up with the same hostname across clients
# is if they have DIFFERENT hardware (else the resolver would have
# merged them into ONE canonical device at resolve time). So this
# finding could ONLY fire on naming coincidence — 100% false positives
# on this fleet (0 of 1,685 pairs had hardware corroboration).
# BLUEPRINT §1.7 updated to reflect the removal.


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
    clear_assessment = """
              AND EXISTS (
                  SELECT 1
                    FROM operations.condition_assessments assessment
                    JOIN operations.condition_policy_versions policy
                      ON policy.version = assessment.policy_version
                     AND policy.active
                   WHERE assessment.tenant_id = f.tenant_id
                     AND assessment.row_kind = 'entity'
                     AND assessment.finding_id = f.id
                     AND (assessment.response->>'may_clear')::boolean IS TRUE
                     AND assessment.assessed_at >= now() -
                         (policy.policy->>'freshness_hours')::integer * interval '1 hour'
              )"""

    # Resolve coverage findings whose (entity_type, platform) is no longer
    # required. Client-scoped rows are sparse overrides: disabled suppresses
    # the inherited service and enabled adds it. This mirrors the evaluator's
    # profile → global fallback precedence.
    for ft_name in ("missing_required_platform", "stale_required_platform"):
        ft_id = _get_finding_type_id(cur, ft_name)
        if not ft_id:
            continue
        cur.execute(
            f"""
            WITH required_for_device AS (
                -- Profile-bound clients inherit profile items unless a
                -- client-specific disabled override removes the same agent.
                SELECT d.id AS device_id, rpi.entity_type, rpi.platform
                FROM operations.devices d
                JOIN operations.clients c ON c.id = d.client_id
                JOIN operations.requirement_profile_items rpi
                  ON rpi.tenant_id = c.tenant_id
                 AND rpi.profile_id = c.requirement_profile_id
                 AND (rpi.device_scope = 'all' OR rpi.device_scope = d.device_role)
                WHERE d.tenant_id = %s AND d.deleted_at IS NULL
                  AND c.requirement_profile_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM operations.coverage_requirements o
                      WHERE o.tenant_id = d.tenant_id
                        AND o.client_id = d.client_id
                        AND o.enabled = FALSE
                        AND (o.device_scope = 'all' OR o.device_scope = d.device_role)
                        AND (
                            (o.agent_id IS NOT NULL AND o.agent_id = rpi.agent_id)
                            OR (o.agent_id IS NULL
                                AND o.entity_type = rpi.entity_type
                                AND o.platform = rpi.platform)
                        )
                  )

                UNION

                -- Clients without a profile inherit global rows unless a
                -- disabled client override removes the same service.
                SELECT d.id AS device_id, cr.entity_type, cr.platform
                FROM operations.devices d
                JOIN operations.clients c ON c.id = d.client_id
                JOIN operations.coverage_requirements cr
                  ON cr.tenant_id = c.tenant_id
                 AND cr.client_id IS NULL AND cr.enabled
                 AND (cr.device_scope = 'all' OR cr.device_scope = d.device_role)
                WHERE d.tenant_id = %s AND d.deleted_at IS NULL
                  AND c.requirement_profile_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM operations.coverage_requirements o
                      WHERE o.tenant_id = d.tenant_id
                        AND o.client_id = d.client_id
                        AND o.enabled = FALSE
                        AND (o.device_scope = 'all' OR o.device_scope = d.device_role)
                        AND (
                            (o.agent_id IS NOT NULL AND o.agent_id = cr.agent_id)
                            OR (o.agent_id IS NULL
                                AND o.entity_type = cr.entity_type
                                AND o.platform = cr.platform)
                        )
                  )

                UNION

                -- Explicit required rows add a client-specific service.
                SELECT d.id AS device_id, o.entity_type, o.platform
                FROM operations.devices d
                JOIN operations.coverage_requirements o
                  ON o.tenant_id = d.tenant_id
                 AND o.client_id = d.client_id
                 AND o.enabled = TRUE
                 AND (o.device_scope = 'all' OR o.device_scope = d.device_role)
                WHERE d.tenant_id = %s AND d.deleted_at IS NULL
            )
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM required_for_device r
                  WHERE r.device_id = f.subject_id
                    AND r.entity_type = (f.finding_details->>'entity_type')
                    AND r.platform    = (f.finding_details->>'platform')
              )
            {clear_assessment}
            """,
            (tenant_id, tenant_id, tenant_id, now, tenant_id, ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve missing/stale_required_platform when the platform has
    # observed the device again recently.
    for ft_name in ("missing_required_platform", "stale_required_platform"):
        ft_id = _get_finding_type_id(cur, ft_name)
        if not ft_id:
            continue
        cur.execute(
            f"""
            UPDATE operations.findings f
            SET status = 'resolved',
                last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND EXISTS (
                  SELECT 1 FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = f.tenant_id
                    AND apc.device_id = f.subject_id
                    AND apc.entity_type = (f.finding_details->>'entity_type')
                    AND apc.platform = (f.finding_details->>'platform')
                    AND COALESCE(apc.last_contact_at, apc.last_observed_at) > now() - INTERVAL '48 hours'
              )
            {clear_assessment}
            """,
            (now, tenant_id, ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve stale_required_platform on devices that are now fully
    # offline (BLUEPRINT §1.8): device_offline covers the whole
    # device, per-agent stale becomes noise. Reciprocal of the
    # suppression in _evaluate_coverage — closes legacy rows so they
    # don't linger after the emission gate kicks in.
    stale_ft_id = _get_finding_type_id(cur, "stale_required_platform")
    if stale_ft_id:
        # Non-correlated subquery — Postgres computes the
        # offline-device set once. Tenant is always the same for
        # the outer scope so it's safe to bind directly.
        cur.execute(
            f"""
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND f.subject_id IN (
                  SELECT apc.device_id
                  FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = %s
                    AND apc.entity_type LIKE 'agent.%%'
                  GROUP BY apc.device_id
                  HAVING MAX(COALESCE(apc.last_contact_at, apc.last_observed_at))
                       < NOW() - INTERVAL '{_LONG_OFFLINE_DAYS} days'
              )
              {clear_assessment}
            """,
            (now, tenant_id, stale_ft_id, device_id, device_id, tenant_id),
        )
        count += cur.rowcount or 0

    # Close any missing/stale_required_platform finding whose device left
    # the agent universe (no agent.* observation exists anymore). New
    # emission is already gated by the universe filter in
    # _evaluate_coverage; this closes legacy rows so they don't linger.
    for ft_name in ("missing_required_platform", "stale_required_platform"):
        ft_id = _get_finding_type_id(cur, ft_name)
        if not ft_id:
            continue
        cur.execute(
            f"""
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = f.tenant_id
                    AND apc.device_id = f.subject_id
                    AND apc.entity_type LIKE 'agent.%%'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM operations.device_operator_decisions dec
                  WHERE dec.tenant_id = f.tenant_id AND dec.device_id = f.subject_id
                    AND dec.dimension = 'in_use_confirmed' AND dec.value = 'true'::jsonb
              )
            {clear_assessment}
            """,
            (now, tenant_id, ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve device_unenrolled when the device joins the agent universe
    # (any agent.* observation appears).
    unenrolled_ft_id = _get_finding_type_id(cur, "device_unenrolled")
    if unenrolled_ft_id:
        cur.execute(
            f"""
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND EXISTS (
                  SELECT 1 FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = f.tenant_id
                    AND apc.device_id = f.subject_id
                    AND apc.entity_type LIKE 'agent.%%'
              )
            {clear_assessment}
            """,
            (now, tenant_id, unenrolled_ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # device_missing_from_source and archived_but_reporting are cleared by
    # their producer (_evaluate_device_lifecycle) when the Computer's listing
    # state changes (ADR-0032); a single evidence record is not enough, since
    # archived documentation beside silent agents is still a cleanup state.
    return count


def _resolve_findings_absent(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    current_subject_ids: list[uuid.UUID],
    now: datetime,
    assessment_required: bool = True,
    empty_result_verified: bool = False,
) -> None:
    """Resolve absent findings only after a complete result is established."""
    if not current_subject_ids and not empty_result_verified:
        return
    # Absence from the current result is not recovery evidence. A source can
    # disappear, a collection can be incomplete, or a device can be omitted
    # by an unhealthy evaluator run. Only a producer-specific positive
    # assessment may authorize clearing; this generic absent-row path never
    # manufactures one.
    assessment_clause = """
          AND EXISTS (
              SELECT 1
              FROM operations.condition_assessments assessment
              WHERE assessment.tenant_id = findings.tenant_id
                AND assessment.row_kind = 'entity'
                AND assessment.finding_id = findings.id
                AND (assessment.response ->> 'may_clear')::boolean IS TRUE
                AND assessment.policy_version = (
                    SELECT version FROM operations.condition_policy_versions
                    WHERE active ORDER BY version DESC LIMIT 1
                )
                AND assessment.assessed_at >= now() - (
                    SELECT (policy->>'freshness_hours')::integer * interval '1 hour'
                    FROM operations.condition_policy_versions
                    WHERE active ORDER BY version DESC LIMIT 1
                )
          )""" if assessment_required else ""
    cur.execute(
        f"""
        UPDATE operations.findings
        SET status = 'resolved', last_seen_at = %s
        WHERE tenant_id = %s
          AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (subject_id = ANY(%s::uuid[]))
        {assessment_clause}
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


def _finding_type_name(cur: Any, finding_type_id: int) -> str:
    cur.execute(
        "SELECT name FROM operations.finding_types WHERE id = %s LIMIT 1",
        (finding_type_id,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Finding type {finding_type_id} is not registered")
    return row[0]


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
    assessment: tuple[tuple[Signal, ...], EvaluationCoverage] | None = None,
) -> int:
    """UPSERT a finding. Severity is immutable; confidence and timestamps update."""
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, subject_layer, finding_details,
            condition_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s,
            'device', %s, '', %s::jsonb,
            %s, %s, %s, 'open',
            %s, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            confidence      = EXCLUDED.confidence,
            last_seen_at    = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            status          = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        RETURNING id
        """,
        (
            tenant_id,
            finding_type_id,
            client_id,
            device_id,
            json.dumps(details),
            condition_key,
            severity,
            confidence,
            now,
            now,
            now,
        ),
    )
    finding_id = cur.fetchone()[0]
    if assessment is not None:
        signals, coverage = assessment
        participant = Participant("device", str(device_id), "affected", tenant_id)
        condition = Condition(
            tenant_id,
            "entity",
            str(finding_id),
            _finding_type_name(cur, finding_type_id),
            condition_key,
            "open",
            (participant,),
        )
        record_assessment(
            cur,
            condition,
            signals,
            coverage,
            now=now,
            reevaluation_key=f"evaluator:{condition_key}:{now.isoformat()}",
            participant=participant,
        )
    return 1
