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
  4. Lifecycle — device_missing_from_source (with its reason),
     archived_but_reporting, device_offline,
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
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ingest import computer_listing, db, device_status_settings, normalize
from ingest.condition_evidence import (
    ADMIN_FINDING_UPSERT_SQL,
    admin_finding_upsert_params,
    preserve_operator_episode,
)
from ingest.conditions import record_assessment
from ingest.identity import findings as identity_findings
from ingest.intel.windows_servicing import sync as sync_windows_servicing
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
from shared.findings_contract import (
    declare_findings_contract,
    lock_tenant_session,
    unlock_tenant_session,
)

log = logging.getLogger(__name__)

_CORROBORATION_WINDOW_HOURS = 48
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


@contextmanager
def _evaluation_transaction(tenant_id: int):
    """Serialize before taking the repeatable-read evaluation snapshot.

    A session lock survives the short acquisition transaction. Taking a
    transaction lock inside repeatable read would freeze a snapshot *before*
    waiting for the preceding evaluator to finish. Always release the lock
    before returning the connection to the pool, including on rollback.
    """
    lock = int.from_bytes(hashlib.sha256(f"platform-evaluate:{tenant_id}".encode()).digest()[:8],
                          "big", signed=True)
    with db.pool.connection() as conn:
        try:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(%s)", (lock,))
                # The findings tenant guard, held for the session for the same reason.
                lock_tenant_session(cur, tenant_id)
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                declare_findings_contract(cur, tenant_id)
                yield cur
        finally:
            with conn.transaction(), conn.cursor() as cur:
                unlock_tenant_session(cur, tenant_id)
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock,))


@dataclass(frozen=True)
class LifecycleResult:
    listing: computer_listing.Listing
    target: str
    reason: str
    evidence: dict[str, Any] | None
    known: bool
    offline: bool
    offline_since: datetime | None
    blockers: tuple[str, ...]
    evaluated_at: datetime
    offline_after_days: int
    review_after_days: int

    @property
    def excludes_requirements(self) -> bool:
        return self.target == "pending_cleanup" and not self.listing.in_use_confirmed

    @property
    def offline_reason(self) -> str:
        return ("offline:reported_without_duration" if self.offline_since is None
                else "offline:extended_absence")


def _load_lifecycle_results(cur, tenant_id, now, device_id, source_problems):
    offline_days, review_days = device_status_settings.load(cur, tenant_id)
    overrides = device_status_settings.client_overrides(cur, tenant_id)
    listings = computer_listing.load(cur, tenant_id, now, device_id)
    devices = _load_lifecycle_evidence(
        cur, tenant_id, [item.device_id for item in listings], include_retired=True
    )
    results = {}
    for item in listings:
        state = item.state(now, review_days)
        device = devices.get(item.device_id, {"rows": [], "client_id": item.client_id})
        evidence, conflict = _select_lifecycle_evidence(device["rows"])
        platforms = {row["platform"] for row in device["rows"]}
        blockers = tuple(dict.fromkeys(
            key for platform in platforms
            for key in blockers_for_platform(source_problems, platform, item.client_id)
        ))
        if state in computer_listing.REVIEW_STATES or state == "retire":
            # Absence across sources requires all relevant collection to be
            # complete; no presence row is not proof a failed source is empty.
            blockers = tuple(dict.fromkeys((*blockers, *(
                problem.condition_key for problem in source_problems
                if problem.client_id is None or problem.client_id == item.client_id
            ))))
        known = not conflict and not blockers
        if any(
            _reported_lifecycle_state(
                row["last_power_state"], row["has_power_state"],
                row["reported_online"], row["has_reported_online_state"],
            )[1]
            and (evidence is None or row["last_observed_at"] > evidence["at"])
            for row in _reported_lifecycle_rows(device["rows"])
        ):
            known = False
        target = item.lifecycle_status
        reason = state
        offline = False
        offline_since = None
        if item.lifecycle_status == "retired" and not item.reporting:
            reason = "retired"
        elif state == "retire":
            target = "retired" if known else target
        elif state in computer_listing.REVIEW_STATES:
            target = "pending_cleanup" if known else target
        elif evidence is None or conflict:
            known = False
            reason = "conflict" if conflict else "unmeasured"
        else:
            reason = "contact_policy"
            if known:
                target = _device_lifecycle_target(
                    device, evidence, now, offline_days, review_days, overrides
                )
                offline = target in {"offline_aging", "pending_cleanup"}
                threshold = overrides.get(str(item.client_id), offline_days)
                # The time of a fresh negative report is not an invented
                # historical contact. Duration must be independently known.
                positive = [row["last_contact_at"] for row in device["rows"]
                            if row["mode"] in _LIFECYCLE_DIRECT_MODES
                            and row["last_contact_at"] is not None]
                since = max(positive) if positive else evidence["at"]
                if (offline and not evidence.get("duration_unknown", False)
                        and since < now - timedelta(days=threshold)):
                    offline_since = since
        results[item.device_id] = LifecycleResult(
            item, target, reason, evidence, known, offline, offline_since, blockers,
            now, overrides.get(str(item.client_id), offline_days),
            max(review_days, overrides.get(str(item.client_id), offline_days) + 1),
        )
    return results, devices


def _apply_lifecycle_results(cur, tenant_id, now, run_id, results):
    affected = 0
    for result in results.values():
        item = result.listing
        if item.in_use_confirmed and item.reporting and result.known and result.target == "active":
            _clear_in_use_confirmation(cur, tenant_id, item.device_id)
        if result.known and item.lifecycle_status != result.target:
            affected += _transition_lifecycle(
                cur, tenant_id, item, item.lifecycle_status, result.target,
                result.reason, result.evidence, now, run_id,
            )
    return affected


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
        with _evaluation_transaction(tenant_id) as cur:
            now = datetime.now(timezone.utc)
            cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
            source_problems = _source_failure_guard(cur, tenant_id, now)
            lifecycle, lifecycle_devices = _load_lifecycle_results(
                cur, tenant_id, now, device_id, source_problems
            )
            affected += _apply_lifecycle_results(
                cur, tenant_id, now, evaluator_run_id, lifecycle
            )
            affected += _sync_lifecycle_status(
                cur, tenant_id, now, evaluator_run_id, skip=set(lifecycle),
                per_device={subject: item for subject, item in lifecycle_devices.items()
                            if lifecycle[subject].target != "retired"}, device_id=device_id,
            )
            if device_id is None:
                affected += _sync_device_roles(cur, tenant_id, now)
                affected += _evaluate_unknown_entities(cur, tenant_id, now)
                affected += _evaluate_change_history_registry(cur, tenant_id, now)
                affected += _evaluate_source_name_kinds(cur, tenant_id, now)
                affected += _evaluate_duplicate_records(cur, tenant_id, now)
                affected += identity_findings.evaluate(cur, tenant_id, now)
            corroborated = _load_corroborated_devices(cur, tenant_id)
            affected += _evaluate_coverage(
                cur, tenant_id, device_id, now, source_problems, corroborated, lifecycle
            )
            affected += _evaluate_unenrolled(cur, tenant_id, device_id, now)
            affected += _evaluate_device_lifecycle(
                cur, tenant_id, device_id, now, source_problems, lifecycle
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
            UPDATE operations.findings
               SET status = 'resolved', closed_at = %s
             WHERE tenant_id = %s AND condition_namespace = 'admin'
               AND condition_key LIKE 'source_failure:binding:%%'
               AND status IN ('open', 'acknowledged', 'investigating')
               AND NOT (condition_key = ANY(%s::text[]))
               AND EXISTS (
                   SELECT 1 FROM operations.condition_assessments assessment
                   JOIN operations.condition_policy_versions policy
                     ON policy.version = assessment.policy_version AND policy.active
                  WHERE assessment.tenant_id = operations.findings.tenant_id
                    AND assessment.row_kind = 'admin'
                    AND assessment.finding_id = operations.findings.id
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
        cur.execute(ADMIN_FINDING_UPSERT_SQL + " RETURNING id", admin_finding_upsert_params(
            tenant_id, finding_type_id, condition_key, severity, subject_ref, details, now
        ))
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


_LIFECYCLE_POLICY_VERSION = "lifecycle-evidence-v2"
_LIFECYCLE_FALLBACK_MODE = "direct_contact_state_fallback"
_LIFECYCLE_DIRECT_MODES = {
    "direct_contact", "direct_then_reported_state", _LIFECYCLE_FALLBACK_MODE,
}
_LIFECYCLE_REPORTED_MODES = {"reported_state", "direct_then_reported_state"}
_LIFECYCLE_POSITIVE_POWER_STATES = {"poweredon"}
_LIFECYCLE_NEGATIVE_POWER_STATES = {"poweredoff", "suspended"}


def _reported_lifecycle_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback reports cannot outrank qualified direct contact on the Computer."""
    direct = any(row["mode"] in _LIFECYCLE_DIRECT_MODES
                 and row["last_contact_at"] is not None for row in rows)
    return [row for row in rows if row["mode"] in _LIFECYCLE_REPORTED_MODES
            or (row["mode"] == _LIFECYCLE_FALLBACK_MODE and not direct)]


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
    for row in _reported_lifecycle_rows(rows):
        status, _ = _reported_lifecycle_state(
            row["last_power_state"],
            row["has_power_state"],
            row["reported_online"],
            row["has_reported_online_state"],
        )
        if status is not None:
            candidate = {
                "kind": "reported_state",
                "status": status,
                "at": row["last_observed_at"],
                "entity_type": row["entity_type"],
                "platform": row["platform"],
            }
            if row["mode"] == _LIFECYCLE_FALLBACK_MODE and status == "offline_aging":
                candidate["duration_unknown"] = True
            candidates.append(candidate)

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
    if evidence.get("duration_unknown", False):
        return "offline_aging"
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
                  AND current_observation.entity_type = apc.entity_type
                  AND current_observation.platform = apc.platform
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
               AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
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
             WHERE tenant_id = %s AND condition_namespace = 'entity'
               AND finding_type_id = %s
               AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
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
             WHERE tenant_id = %s AND condition_namespace = 'entity'
               AND finding_type_id = %s
               AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
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
         WHERE tenant_id = %s AND condition_namespace = 'entity'
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
            "SELECT id, status FROM operations.findings WHERE tenant_id=%s"
            " AND condition_namespace = 'entity' AND condition_key=%s",
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
            "SELECT id, status FROM operations.findings WHERE tenant_id=%s"
            " AND condition_namespace = 'entity' AND condition_key=%s",
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
    """Compatibility entrypoint using the same scoped lifecycle result/writer."""
    results, _ = _load_lifecycle_results(cur, tenant_id, now, device_id, [])
    if owned is not None:
        owned.update(results)
    return _apply_lifecycle_results(cur, tenant_id, now, evaluator_run_id, results)


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


def _begin_lifecycle_action(cur: Any, tenant_id: int, action: str, reason: str, evidence: dict) -> None:
    cur.execute(
        "SELECT operations.begin_change(%s, %s, %s::jsonb, 'process', NULL::bigint, "
        "'ingest.evaluator', '', %s::bigint, true)",
        (action, reason, json.dumps(evidence), tenant_id),
    )


def _end_lifecycle_action(cur: Any) -> None:
    cur.execute("SELECT set_config('operations.change_action_id', '', true)")


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
    """Apply one lifecycle change as its own explicit change action (ADR-0033)."""
    explicit = "retired" in (previous, target)
    retiring = target == "retired"
    _begin_lifecycle_action(
        cur,
        tenant_id,
        ("computer.retire.automatic" if retiring else "computer.restore.automatic")
        if explicit
        else "lifecycle.transition",
        ("Nothing lists this machine any more." if retiring else "A source reports this machine again.")
        if explicit
        else f"Lifecycle {previous} -> {target}: {state}.",
        {"state": state, "last_source": item.last_source},
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
        # The action covers this Computer only; later evaluator writes are implicit.
        _end_lifecycle_action(cur)


def _sync_lifecycle_status(
    cur: Any,
    tenant_id: int,
    now: datetime,
    evaluator_run_id: uuid.UUID,
    skip: set[uuid.UUID] | None = None,
    per_device: dict | None = None,
    device_id: uuid.UUID | None = None,
) -> int:  # noqa: PLR0912 - policy branches map to explicit approved outcomes.
    """Apply explicit lifecycle policy and append transition audit events.

    The registry supplies the only lifecycle capability. Direct contact never
    falls back to collection time; reported state uses collection time because
    that is the source observation time for the reported state. ``retired`` is
    an operator decision and is never selected for an automatic update.
    """
    offline_after_days, retire_review_days = device_status_settings.load(cur, tenant_id)
    client_offline_days = device_status_settings.client_overrides(cur, tenant_id)
    if per_device is None:
        per_device = _load_lifecycle_evidence(cur, tenant_id, [device_id] if device_id else None)

    affected = 0
    unknown_keys: set[str] = set()
    conflict_keys: set[str] = set()
    unknown_type_id = _get_finding_type_id(cur, "lifecycle_unknown_reported_state")
    conflict_type_id = _get_finding_type_id(cur, "lifecycle_reported_state_conflict")

    for device_id, device in per_device.items():
        for row in _reported_lifecycle_rows(device["rows"]):
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
        _begin_lifecycle_action(
            cur, tenant_id, "lifecycle.transition",
            f"Lifecycle {previous} -> {target}: contact policy.",
            {"evidence_kind": evidence["kind"], "evidence_platform": evidence["platform"]},
        )
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
            _end_lifecycle_action(cur)
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
        _end_lifecycle_action(cur)
        affected += 1

    if unknown_type_id is not None:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, unknown_type_id, unknown_keys, now, device_id
        )
    if conflict_type_id is not None:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, conflict_type_id, conflict_keys, now, device_id
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
        UPDATE operations.findings
        SET status = 'resolved', closed_at = %s
        WHERE tenant_id = %s AND condition_namespace = 'admin' AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
          AND EXISTS (
              SELECT 1 FROM operations.condition_assessments a
               WHERE a.tenant_id = operations.findings.tenant_id
                 AND a.row_kind = 'admin'
                 AND a.finding_id = operations.findings.id
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
        UPDATE operations.findings
        SET status = 'resolved', closed_at = %s
        WHERE tenant_id = %s AND condition_namespace = 'admin' AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
          AND EXISTS (
              SELECT 1 FROM operations.condition_assessments a
               WHERE a.tenant_id = operations.findings.tenant_id
                 AND a.row_kind = 'admin'
                 AND a.finding_id = operations.findings.id
                 AND (a.response->>'may_clear')::boolean IS TRUE
                 AND a.policy_version = (SELECT version FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
                 AND a.assessed_at >= now() - (SELECT (policy->>'freshness_hours')::integer * interval '1 hour' FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
          )
        """,
        (now, tenant_id, ft_id, present_keys),
    )
    return len(tables)


def _evaluate_source_name_kinds(cur: Any, tenant_id: int, now: datetime) -> int:
    """Admin finding per source and record type whose names have no name kind (ADR-0034)."""
    ft_id = _get_finding_type_id(cur, "source_name_kind_unclassified")
    if ft_id is None:
        return 0
    cur.execute(
        "SELECT to_regprocedure('operations.source_name_kind_unclassified(bigint)') IS NOT NULL"
    )
    if not cur.fetchone()[0]:
        return 0
    cur.execute("SELECT * FROM operations.source_name_kind_unclassified(%s)", (tenant_id,))
    rows = cur.fetchall()
    present_keys = []
    for platform, record_type, records in rows:
        ckey = f"source_name_kind_unclassified:{platform}:{record_type}"
        present_keys.append(ckey)
        _upsert_admin_finding(
            cur,
            tenant_id,
            ft_id,
            ckey,
            "medium",
            now,
            {"platform": platform, "record_type": record_type},
            {"platform": platform, "record_type": record_type, "records": records},
            measured=True,
        )
    cur.execute(
        """
        UPDATE operations.findings
        SET status = 'resolved', closed_at = %s
        WHERE tenant_id = %s AND condition_namespace = 'admin' AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
          AND EXISTS (
              SELECT 1 FROM operations.condition_assessments a
               WHERE a.tenant_id = operations.findings.tenant_id
                 AND a.row_kind = 'admin'
                 AND a.finding_id = operations.findings.id
                 AND (a.response->>'may_clear')::boolean IS TRUE
                 AND a.policy_version = (SELECT version FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
                 AND a.assessed_at >= now() - (SELECT (policy->>'freshness_hours')::integer * interval '1 hour' FROM operations.condition_policy_versions WHERE active ORDER BY version DESC LIMIT 1)
          )
        """,
        (now, tenant_id, ft_id, present_keys),
    )
    return len(rows)


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
        UPDATE operations.findings
        SET status = 'resolved', closed_at = %s
        WHERE tenant_id = %s AND condition_namespace = 'admin' AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
          AND EXISTS (
              SELECT 1 FROM operations.condition_assessments a
               WHERE a.tenant_id = operations.findings.tenant_id
                 AND a.row_kind = 'admin'
                 AND a.finding_id = operations.findings.id
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


# A source whose every current record of this Computer is archived, retired or
# decommissioned does not satisfy a requirement (ADR-0032: an archived Hudu
# asset is not documentation). Records the source no longer lists keep the
# existing presence semantics. ``apc`` is the presence row being tested.
_PRESENCE_SATISFIES = """
    AND NOT (
        EXISTS (SELECT 1 FROM operations.v_device_source_record_lifecycle_current rec
                 WHERE rec.tenant_id = apc.tenant_id AND rec.device_id = apc.device_id
                   AND rec.entity_type = apc.entity_type AND rec.platform = apc.platform
                   AND rec.source_record_current
                   AND rec.record_lifecycle IN ('archived', 'retired', 'decommissioned'))
        AND NOT EXISTS (SELECT 1 FROM operations.v_device_source_record_lifecycle_current rec
                 WHERE rec.tenant_id = apc.tenant_id AND rec.device_id = apc.device_id
                   AND rec.entity_type = apc.entity_type AND rec.platform = apc.platform
                   AND rec.source_record_current
                   AND rec.record_lifecycle NOT IN ('archived', 'retired', 'decommissioned'))
    )
"""


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
    lifecycle_results: dict[uuid.UUID, LifecycleResult] | None = None,
) -> int:
    """Emit coverage findings from baseline requirements plus client overrides.

    A client-scoped ``coverage_requirements`` row is a sparse override:
    enabled adds/replaces a service requirement and disabled explicitly removes
    it. With no override, the client inherits its explicit profile or the
    tenant-default profile when no override is assigned. This keeps profiles
    reusable while allowing a client to require or exempt one service
    independently.
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

    client_override_tiers: dict[Any, dict[str, list[tuple]]] = {}
    for row in client_override_rows:
        client_override_tiers.setdefault(row[1], {}).setdefault(row[5], []).append(row)

    # client_id → effective profile_id. A NULL assignment deliberately means
    # inherit the tenant-default profile, not a separate Global baseline.
    cur.execute(
        """
        SELECT c.id, COALESCE(c.requirement_profile_id, default_profile.id)
          FROM operations.clients c
          LEFT JOIN operations.requirement_profiles default_profile
            ON default_profile.tenant_id = c.tenant_id
           AND default_profile.is_tenant_default
         WHERE c.tenant_id = %s AND c.deleted_at IS NULL
        """,
        (tenant_id,),
    )
    client_profile: dict[Any, Any] = {row[0]: row[1] for row in cur.fetchall()}

    def resolve_tier(dev_client_id, dev_role: str) -> list[tuple]:
        profile_id = client_profile.get(dev_client_id)
        scopes = profile_tiers.get(profile_id, {})
        baseline = scopes.get(dev_role) or scopes.get("all") or []

        # Apply broad overrides before role-specific overrides, so a scoped
        # decision can intentionally refine a client-wide decision.
        overrides = client_override_tiers.get(dev_client_id, {})
        override_rows = list(overrides.get("all", []))
        if dev_role != "all":
            override_rows.extend(overrides.get(dev_role, []))
        return _apply_requirement_overrides(baseline, override_rows)

    missing_ft = _get_finding_type_id(cur, "missing_required_platform")
    stale_ft = _get_finding_type_id(cur, "stale_required_platform")
    os_unknown_ft = _get_finding_type_id(cur, "os_unknown_coverage")
    os_unknown_subjects: list[uuid.UUID] = []
    if missing_ft is None:
        log.warning("evaluator: finding_type 'missing_required_platform' not found")
        return 0
    identity_blocked = _identity_blocked_devices(cur, tenant_id)
    if lifecycle_results is None:
        lifecycle_results, _ = _load_lifecycle_results(
            cur, tenant_id, now, device_id, source_problems
        )
    fully_offline_devices = {
        subject for subject, result in lifecycle_results.items() if result.known and result.offline
    }

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
                            AND dec.value = 'true'::jsonb)) AS in_agent_universe,
               d.lifecycle_status,
               EXISTS(SELECT 1 FROM operations.device_operator_decisions confirmed
                       WHERE confirmed.tenant_id = d.tenant_id AND confirmed.device_id = d.id
                         AND confirmed.dimension = 'in_use_confirmed'
                         AND confirmed.value = 'true'::jsonb) AS in_use_confirmed
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

    # ADR-0035: every evaluated requirement's verdict, written below in this
    # transaction, so readers never re-derive the rule.
    verdicts: list[dict[str, Any]] = []

    def record(dev_id, agent_id, entity_type, platform, verdict, last_observed=None, ckey=None):
        verdicts.append(
            {
                "device_id": str(dev_id),
                "entity_type": entity_type,
                "platform": platform,
                "agent_id": agent_id,
                "verdict": verdict,
                "last_observed_at": last_observed.isoformat() if last_observed else None,
                "condition_key": ckey,
            }
        )

    def allowed_os_groups(agent_id, aog) -> set[str] | None:
        # applicable_os_groups on the item narrows the agent's supported set;
        # None means the requirement is not limited by operating system.
        if aog:
            return set(aog)
        if agent_id and agent_id in agents_by_id:
            return set(agents_by_id[agent_id][2])
        return None

    def record_all(dev_id, tier_rows, exemptions, os_group, verdict) -> None:
        """Record every requirement of a Computer the pass does not check."""
        for _rid, _rclient, agent_id, entity_type, platform, _rscope, aog, *_rest in tier_rows:
            if entity_type in exemptions:
                record(dev_id, agent_id, entity_type, platform, "exempt")
                continue
            allowed_groups = allowed_os_groups(agent_id, aog)
            if allowed_groups is not None and os_group not in allowed_groups and os_group != "Unknown":
                continue
            record(dev_id, agent_id, entity_type, platform, verdict)

    count = 0
    for (
        dev_id,
        dev_client_id,
        hostname,
        dev_role,
        exemptions,
        os_group,
        in_universe,
        lifecycle_status,
        in_use_confirmed,
    ) in devices:
        exemptions = exemptions or {}
        not_applied: list[dict[str, str]] = []
        tier_rows = resolve_tier(dev_client_id, dev_role or "all")
        # Cleanup is a lifecycle exclusion, including no-agent Computers.
        # ADR-0047: only an explicit valid decision bypasses that exclusion.
        if lifecycle_status == "pending_cleanup" and not in_use_confirmed:
            record_all(dev_id, tier_rows, exemptions, os_group, "pending_cleanup")
            continue
        if not in_universe:
            record_all(dev_id, tier_rows, exemptions, os_group, "outside_coverage")
            continue
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
                record(dev_id, agent_id, entity_type, platform, "exempt")
                continue
            # ADR-0036: positive on the operating system. An OS-limited
            # requirement applies only when the Computer's OS group is known
            # and supported (LogMeIn is not expected on Linux). An unknown OS
            # applies none of them, even where the agent has been seen; the
            # Computer gets one os_unknown_coverage finding instead.
            allowed_groups = allowed_os_groups(agent_id, aog)
            if allowed_groups is not None and os_group not in allowed_groups:
                if os_group == "Unknown":
                    not_applied.append({"entity_type": entity_type, "platform": platform})
                    record(dev_id, agent_id, entity_type, platform, "os_unknown")
                continue

            # Per-device presence for this (entity_type, platform), 'any'
            # honored (BLUEPRINT C.6 wildcard).
            # BLUEPRINT E.6: staleness uses platform LAST CONTACT, not our
            # fetch time. `last_observed_at` is when WE polled the source
            # API — always recent; `last_contact_at` is when the source
            # last heard from the DEVICE. Fall back only when contact is
            # unpopulated (some sources don't distinguish).
            cur.execute(
                f"""
                SELECT MAX(COALESCE(apc.last_contact_at, apc.last_observed_at))
                FROM operations.device_agent_presence_current apc
                WHERE apc.tenant_id = %s AND apc.device_id = %s
                  AND apc.entity_type = %s
                  AND (%s = 'any' OR apc.platform = %s)
                  {_PRESENCE_SATISFIES}
                """,
                (tenant_id, dev_id, entity_type, platform, platform),
            )
            (last_observed,) = cur.fetchone()
            collection_blockers = _requirement_collection_blockers(
                source_problems, platform, dev_client_id
            )
            result = lifecycle_results.get(dev_id)
            if result is None or not result.known:
                collection_blockers += (("lifecycle:unmeasured",) if result is None
                                        else result.blockers or ("lifecycle:unmeasured",))

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
                    record(dev_id, agent_id, entity_type, platform, "satisfied", last_observed)
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
                    record(dev_id, agent_id, entity_type, platform, "stale", last_observed)
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
            record(
                dev_id,
                agent_id,
                entity_type,
                platform,
                "missing" if last_observed is None else "stale",
                last_observed,
                ckey,
            )
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
                        offline_reason=result.offline_reason if result else "offline:unmeasured",
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

        if os_group == "Unknown" and os_unknown_ft is not None:
            os_unknown_subjects.append(dev_id)
            count += _upsert_finding(
                cur,
                tenant_id,
                os_unknown_ft,
                dev_client_id,
                dev_id,
                _condition_key(tenant_id, dev_client_id, dev_id, "os_unknown_coverage", ""),
                "medium",
                "confirmed",
                now,
                {"hostname": hostname, "requirements_not_applied": not_applied},
                assessment=(
                    _device_condition_signals(
                        tenant_id, dev_id, identity_blocked, offline=False, collection_skipped=False
                    ),
                    EvaluationCoverage(True, True, True, True),
                ),
            )

    _write_requirement_state(cur, tenant_id, device_id, verdicts)
    count += _reconcile_requirement_findings(
        cur, tenant_id, device_id, now, verdicts, os_unknown_subjects,
        source_problems, identity_blocked, fully_offline_devices, lifecycle_results,
    )
    return count


def _requirement_collection_blockers(
    problems: list[SourceCollectionProblem], platform: str, client_id: Any
) -> tuple[str, ...]:
    # An 'any' requirement cannot establish complete absence if a candidate
    # source in its client scope failed. Exact platforms keep their own scope.
    if platform == "any":
        return tuple(
            problem.condition_key for problem in problems
            if problem.client_id is None or problem.client_id == client_id
        )
    return blockers_for_platform(problems, platform, client_id)


def _reconcile_requirement_findings(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
    verdicts: list[dict[str, Any]],
    os_unknown_subjects: list[uuid.UUID],
    source_problems: list[SourceCollectionProblem],
    identity_blocked: set[uuid.UUID],
    fully_offline_devices: set[uuid.UUID],
    lifecycle_results: dict[uuid.UUID, LifecycleResult],
) -> int:
    """Reconcile old episodes from this successful coverage pass, never a second rule.

    Conditions that disappeared need a current assessment too. Failure-only
    assessment writes left satisfied, excluded and superseded findings stuck
    behind their previous blocked response. Unknown-OS/cleanup requirements
    keep their covered history (ADR-0036), even if clearing becomes permitted.
    Other obsolete episodes close only through a newly measured may_clear.
    """
    current = {
        (row["device_id"], row["entity_type"], row["platform"]): row for row in verdicts
    }
    unknown = set(os_unknown_subjects)
    cur.execute(
        """
        SELECT f.id, f.subject_id, f.condition_key, ft.name,
               f.finding_details, f.status,
               d.id, d.client_id, d.lifecycle_status
          FROM operations.findings f
          JOIN operations.finding_types ft ON ft.id = f.finding_type_id
          LEFT JOIN operations.devices d
            ON d.tenant_id = f.tenant_id AND d.id = f.subject_id
         WHERE f.tenant_id = %s AND f.subject_type = 'device'
           AND ft.name IN ('missing_required_platform', 'stale_required_platform',
                           'os_unknown_coverage')
           AND f.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
           AND (%s::uuid IS NULL OR f.subject_id = %s)
         ORDER BY f.id
         FOR UPDATE OF f
        """,
        (tenant_id, device_id, device_id),
    )
    count = 0
    for fid, subject, key, type_name, details, status, existing, client, lifecycle in cur.fetchall():
        if existing is None:
            # A dangling subject cannot establish a valid participant scope.
            # Leave it visible to the audit instead of aborting the whole pass.
            log.warning("requirement reconciliation: missing tenant-owned Computer")
            continue
        platform = details.get("platform", "")
        row = current.get((str(subject), details.get("entity_type", ""), platform))
        if type_name == "os_unknown_coverage":
            if subject in unknown and key == _condition_key(
                tenant_id, client, subject, type_name, ""
            ):
                continue
            # This condition ends when OS becomes known or coverage/lifecycle
            # excludes the Computer; the child requirement episodes stay covered.
            retain = False
        else:
            expected = "missing" if type_name == "missing_required_platform" else "stale"
            if row and row["verdict"] == expected and row.get("condition_key") == key:
                continue
            result = lifecycle_results.get(subject)
            retain = (result is not None and result.excludes_requirements) or (
                row is not None and row["verdict"] in {"os_unknown", "pending_cleanup"}
            )
        blockers = _requirement_collection_blockers(source_problems, platform, client)
        result = lifecycle_results.get(subject)
        if result is None or not result.known:
            blockers += (("lifecycle:unmeasured",) if result is None
                         else result.blockers or ("lifecycle:unmeasured",))
        participant = Participant("device", str(subject), "affected", tenant_id)
        condition = Condition(
            tenant_id, "entity", str(fid), type_name, key, status, (participant,)
        )
        response = record_assessment(
            cur, condition,
            _device_condition_signals(
                tenant_id, subject, identity_blocked,
                offline=subject in fully_offline_devices,
                offline_reason=result.offline_reason if result else "offline:unmeasured",
                collection_skipped=bool(blockers), collection_blockers=blockers,
            ),
            EvaluationCoverage(
                existing is not None, not blockers, not blockers, existing is not None
            ),
            now=now, reevaluation_key=f"requirement-reconcile:{key}:{now.isoformat()}",
            participant=participant,
        )
        if not retain and response["may_clear"]:
            cur.execute(
                """UPDATE operations.findings
                      SET status = 'resolved', last_seen_at = %s
                    WHERE tenant_id = %s AND id = %s
                      AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')""",
                (now, tenant_id, fid),
            )
            count += cur.rowcount
    return count


def _write_requirement_state(
    cur: Any, tenant_id: int, device_id: uuid.UUID | None, verdicts: list[dict[str, Any]]
) -> None:
    """Replace the stored requirement verdicts for this pass (ADR-0035, migration 0332).

    A full pass replaces every Computer's verdicts; a single-Computer pass only
    that Computer's. Runs in the coverage pass's transaction, so the verdicts
    and the findings they produced commit together.
    """
    cur.execute(
        "SELECT to_regprocedure("
        "'operations.write_device_requirement_state(bigint, uuid[], jsonb)') IS NOT NULL"
    )
    if not cur.fetchone()[0]:
        return
    cur.execute(
        "SELECT operations.write_device_requirement_state(%s, %s::uuid[], %s::jsonb)",
        (tenant_id, [str(device_id)] if device_id else None, json.dumps(verdicts)),
    )


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
    lifecycle_results: dict[uuid.UUID, LifecycleResult] | None = None,
) -> int:
    """Cleanup, archived-but-reporting, offline and stale-data findings."""
    count = 0
    if lifecycle_results is None:
        lifecycle_results, _ = _load_lifecycle_results(cur, tenant_id, now, device_id, source_problems)

    # device_source_record_withdrawn was retired (migration 0316): a withdrawn
    # record is History; missing agents, cleanup and retirement have their
    # own findings below and in the coverage check (ADR-0032).

    # ADR-0032: what still lists a Computer that nothing reports for. One
    # finding per Computer; its reason follows the state (each change is
    # recorded in the finding's history).
    missing_type_id = _get_finding_type_id(cur, "device_missing_from_source")
    archived_type_id = _get_finding_type_id(cur, "archived_but_reporting")
    no_current_evidence_keys: set[str] = set()
    archived_keys: set[str] = set()
    if missing_type_id or archived_type_id:
        for result in lifecycle_results.values():
            item = result.listing
            if not result.known:
                no_current_evidence_keys.add(_condition_key(
                    tenant_id, item.client_id, item.device_id, "device_missing_from_source", ""
                ))
                archived_keys.add(_condition_key(
                    tenant_id, item.client_id, item.device_id, "archived_but_reporting", ""
                ))
                continue
            state = result.reason
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

    if missing_type_id:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, missing_type_id, no_current_evidence_keys, now, device_id
        )
    if archived_type_id:
        _resolve_lifecycle_findings_absent(
            cur, tenant_id, archived_type_id, archived_keys, now, device_id
        )

    count += _evaluate_device_offline(cur, tenant_id, now, lifecycle_results, device_id)
    if device_id is None:
        count += _evaluate_stale_data(cur, tenant_id, now, source_problems)
    return count


def _evaluate_device_offline(cur, tenant_id, now, lifecycle_results=None, device_id=None):
    """Project qualified lifecycle absence; never substitute polling for contact."""
    if lifecycle_results is None:
        lifecycle_results, _ = _load_lifecycle_results(cur, tenant_id, now, device_id, [])
    ft_id = _get_finding_type_id(cur, "device_offline")
    if ft_id is None:
        return 0
    identity_blocked = _identity_blocked_devices(cur, tenant_id)
    active_keys = set()
    count = 0
    for subject, result in lifecycle_results.items():
        key = _condition_key(tenant_id, result.listing.client_id, subject, "device_offline", "")
        if not result.known:
            # Preserve the episode until complete evidence can establish recovery.
            active_keys.add(key)
            continue
        if (result.offline and result.offline_since is None) or (
            result.reason == "confirmed_in_use" and result.evidence is None
        ):
            # Neither an unmeasured duration nor an operator's use decision
            # establishes recovery from an already recorded offline episode.
            active_keys.add(key)
            continue
        if result.reason != "contact_policy" or result.offline_since is None:
            continue
        active_keys.add(key)
        count += _upsert_finding(
            cur, tenant_id, ft_id, result.listing.client_id, subject, key,
            "medium", "confirmed", now,
            {"last_contact_at": result.offline_since.isoformat(),
             "fully_offline_since": result.offline_since.isoformat(),
             "evidence_kind": result.evidence["kind"],
             "evidence_platform": result.evidence["platform"],
             "lifecycle_reason": result.reason},
            assessment=(
                _device_condition_signals(tenant_id, subject, identity_blocked,
                                          offline=True, collection_skipped=False),
                EvaluationCoverage(True, True, True, True),
            ),
        )
    _resolve_lifecycle_findings_absent(cur, tenant_id, ft_id, active_keys, now, device_id)
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
    offline_reason: str = "offline:extended_absence",
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
            offline_reason if offline else "offline:contact_current",
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

    # Requirement episodes are reconciled from the coverage pass's verdicts
    # in _reconcile_requirement_findings, with fresh assessments and the
    # same transaction. Do not re-derive profiles or use a fixed age here.

    # Resolve device_unenrolled when the device joins the agent universe
    # (any agent.* observation appears).
    unenrolled_ft_id = _get_finding_type_id(cur, "device_unenrolled")
    if unenrolled_ft_id:
        cur.execute(
            f"""
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s AND f.condition_namespace = 'entity'
              AND f.finding_type_id = %s
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
        WHERE tenant_id = %s AND condition_namespace = 'entity'
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
    """Refresh one finding while preserving its episode and operator state."""
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
        ON CONFLICT (tenant_id, condition_namespace, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            client_id       = EXCLUDED.client_id,
            subject_id      = EXCLUDED.subject_id,
            finding_details = EXCLUDED.finding_details,
            severity        = EXCLUDED.severity,
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
