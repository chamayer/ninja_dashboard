"""Platform-health findings: ingest and durable Jobs control-plane health.

Two conditions were registered as `finding_class='admin'` finding types but
nothing ever emitted them. Meanwhile `activities` failed 20 times in 7 days,
`agent_compliance` 11 times, and `software.activity` sat at 4x its configured
`max_depth` — all silent. This module closes that gap.

  - `source_failure`         — an ingest domain whose most recent run failed.
  - `software_queue_stalled` — a registered queue over its own `max_depth`
                               or `max_pending_age_m` threshold.
  - `jobs_*` — measured health conditions for durable schedules, executions,
                dependencies, and the registry/runtime control plane.

Both surface on the Operations admin health page (`findings_admin_health`),
which lists `FindingType.objects.filter(finding_class="admin")` — no UI work
is required for them to appear.

Subject convention follows the existing admin-finding precedent in
`ingest/identity/resolver.py`: `subject_type='source_binding'` with a
deterministic UUID and the real context in `finding_details`. Assessment
participants use the non-owned `platform_signal` kind because these UUIDs are
synthetic and are not rows in `source_bindings`.

Default is dry-run: nothing is written unless `dry_run=False` is passed.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from ingest import db
from ingest.cmdb_findings import (
    TENANT_ID,
    _finding_type_id,
)
from ingest.condition_evidence import preserve_operator_episode
from ingest.conditions import record_assessment
from shared.conditions.contracts import Condition, EvaluationCoverage, Participant
from shared.jobs_registry import (
    INITIAL_EXECUTION_CAPACITY,
    INITIAL_LANE_CAPACITIES,
    definition,
    definitions,
    registry_digest,
    schedule_definitions,
)

log = logging.getLogger(__name__)

# Deterministic subject IDs — same domain/queue always yields the same UUID,
# so a finding reopens rather than duplicating.
_NS = uuid.UUID("6f6d1f9c-0d2c-4a1e-9a6b-2f0f5f2a1c77")

# Queue tables share one schema (id, df, reason, queued_at, status, ...).
# A registry row whose table lacks it is skipped and logged rather than
# silently ignored.
_QUEUE_COLUMNS = ("status", "queued_at")


def _subject(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{kind}:{key}")


def _upsert_admin_finding(
    cur: Any,
    *,
    finding_type_id: int,
    condition_key: str,
    severity: str,
    now: datetime,
    subject_ref: dict[str, Any],
    details: dict[str, Any],
) -> uuid.UUID:
    """Upsert a platform condition in the admin-only findings ledger."""
    preserved = preserve_operator_episode(
        cur, "admin_findings", TENANT_ID, condition_key, now, details
    )
    if preserved is not None:
        return uuid.UUID(preserved)
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
            details = EXCLUDED.details
        RETURNING id
        """,
        (
            TENANT_ID,
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
        raise RuntimeError("Admin finding upsert did not return a finding ID")
    return row[0]


def evaluate(*, dry_run: bool = True) -> dict[str, int]:
    """Emit platform-health findings. Returns per-condition counts."""
    now = datetime.now(UTC)
    counts = {
        "source_failure": 0,
        "software_queue_stalled": 0,
        "queues_skipped": 0,
        "jobs_schedule_failure": 0,
        "jobs_required_disabled": 0,
        "jobs_queue_backlog": 0,
        "jobs_repeated_failure": 0,
        "jobs_timeout": 0,
        "jobs_registry_mismatch": 0,
        "jobs_unmet_dependency": 0,
    }

    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = %s", (TENANT_ID,))
        ft_failure = _finding_type_id(cur, "source_failure")
        ft_queue = _finding_type_id(cur, "software_queue_stalled")
        jobs_types = {
            name: _finding_type_id(cur, name)
            for name in (
                "jobs_schedule_failure",
                "jobs_required_disabled",
                "jobs_queue_backlog",
                "jobs_repeated_failure",
                "jobs_timeout",
                "jobs_registry_mismatch",
                "jobs_unmet_dependency",
            )
        }

        failure_keys = _eval_source_failures(cur, ft_failure, now, counts, dry_run)
        queue_keys = _eval_stalled_queues(cur, ft_queue, now, counts, dry_run)
        jobs_keys = _eval_jobs_health(cur, jobs_types, now, counts, dry_run)

        if not dry_run:
            _resolve_admin_absent(
                cur, ft_failure, failure_keys, now, assessment_required=True
            )
            _resolve_admin_absent(
                cur, ft_queue, queue_keys, now, assessment_required=True
            )
            for name, finding_type_id in jobs_types.items():
                _resolve_admin_absent(
                    cur, finding_type_id, jobs_keys[name], now, assessment_required=True
                )

    log.info("platform findings: %s (dry_run=%s)", counts, dry_run)
    return counts


def _resolve_admin_absent(
    cur: Any,
    finding_type_id: int | None,
    keys: list[str],
    now: datetime,
    *,
    assessment_required: bool = True,
) -> None:
    """Resolve absent platform findings only with a current admin assessment."""
    if finding_type_id is None or not assessment_required:
        return
    cur.execute("SELECT to_regclass('operations.condition_assessments') IS NOT NULL")
    if not cur.fetchone()[0]:
        return
    cur.execute(
        """
        UPDATE operations.admin_findings finding
           SET status = 'resolved', resolved_at = %s
         WHERE finding.tenant_id = %s
           AND finding.finding_type_id = %s
           AND finding.status IN ('open', 'acknowledged')
           AND NOT (finding.condition_key = ANY(%s::text[]))
           AND EXISTS (
               SELECT 1
                 FROM operations.condition_assessments assessment
                 JOIN operations.condition_policy_versions policy
                   ON policy.version = assessment.policy_version
                  AND policy.active
                WHERE assessment.tenant_id = finding.tenant_id
                  AND assessment.row_kind = 'admin'
                  AND assessment.finding_id = finding.id
                  AND (assessment.response ->> 'may_clear')::boolean IS TRUE
                  AND assessment.assessed_at >= now() -
                      (policy.policy ->> 'freshness_hours')::integer * interval '1 hour'
           )
        """,
        (now, TENANT_ID, finding_type_id, keys),
    )


def _eval_source_failures(
    cur: Any, finding_type_id: int, now: datetime, counts: dict[str, int], dry_run: bool
) -> list[str]:
    """One finding per domain whose LATEST run failed.

    Keyed on the latest run rather than any recent failure, so a transient
    blip that has since recovered does not hold a finding open.
    """
    cur.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (domain)
                   domain, status, error_text, started_at, finished_at
              FROM ninja_core.run_log
             WHERE status <> 'running'
             ORDER BY domain, started_at DESC
        ),
        recent AS (
            SELECT domain,
                   count(*) FILTER (WHERE status = 'failed') AS failures_24h,
                   max(started_at) FILTER (WHERE status = 'ok') AS last_ok
              FROM ninja_core.run_log
             WHERE started_at > now() - interval '24 hours'
             GROUP BY domain
        )
        SELECT l.domain, l.error_text, l.started_at,
               COALESCE(r.failures_24h, 0), r.last_ok
          FROM latest l
          LEFT JOIN recent r ON r.domain = l.domain
         WHERE l.status = 'failed'
         ORDER BY l.domain
        """
    )
    keys: list[str] = []
    for domain, error_text, started_at, failures_24h, last_ok in cur.fetchall():
        key = f"source_failure:{domain}"
        keys.append(key)
        counts["source_failure"] += 1
        if dry_run:
            continue
        subject_id = _subject("domain", domain)
        finding_id = _upsert_admin_finding(
            cur,
            finding_type_id=finding_type_id,
            condition_key=key,
            # A domain with no success in 24h is broken, not flaky.
            severity="high" if last_ok is None else "medium",
            now=now,
            subject_ref={"signal_kind": "domain", "signal_id": str(subject_id)},
            details={
                "domain": domain,
                "last_failure_at": started_at.isoformat() if started_at else None,
                "failures_24h": failures_24h,
                "last_success_at": last_ok.isoformat() if last_ok else None,
                "error": (error_text or "")[:500],
            },
        )
        _record_platform_assessment(
            cur, finding_id, key, "source_failure", subject_id, now
        )
    return keys


def _eval_stalled_queues(
    cur: Any, finding_type_id: int, now: datetime, counts: dict[str, int], dry_run: bool
) -> list[str]:
    """One finding per enabled queue breaching its registered thresholds."""
    cur.execute(
        """
        SELECT queue_key, table_name, max_pending_age_m, max_depth
          FROM operations.queue_registry
         WHERE enabled
         ORDER BY queue_key
        """
    )
    registry = cur.fetchall()

    keys: list[str] = []
    for queue_key, table_name, max_age_m, max_depth in registry:
        if table_name == "operations.operator_job_runs":
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE status = 'queued'),
                       EXTRACT(EPOCH FROM (now() - min(requested_at)
                         FILTER (WHERE status = 'queued'))) / 60,
                       count(*) FILTER (WHERE status IN ('failed', 'stalled'))
                  FROM operations.operator_job_runs
                 WHERE tenant_id = %s
                """,
                (TENANT_ID,),
            )
            depth, oldest_age_m, failed_count = cur.fetchone()
            depth = depth or 0
            oldest_age_m = float(oldest_age_m or 0)
            over_depth = bool(max_depth) and depth > max_depth
            over_age = bool(max_age_m) and oldest_age_m > max_age_m
            if not (over_depth or over_age or failed_count):
                continue
            key = f"software_queue_stalled:{queue_key}"
            keys.append(key)
            counts["software_queue_stalled"] += 1
            if dry_run:
                continue
            finding_id = _upsert_admin_finding(
                cur,
                finding_type_id=finding_type_id,
                condition_key=key,
                severity="high"
                if failed_count or (over_depth and over_age)
                else "medium",
                now=now,
                subject_ref={
                    "signal_kind": "queue",
                    "signal_id": str(_subject("queue", queue_key)),
                },
                details={
                    "queue_key": queue_key,
                    "pending_depth": depth,
                    "oldest_pending_minutes": round(oldest_age_m, 1),
                    "failed_or_stalled": failed_count,
                    "max_pending_age_m": max_age_m,
                    "max_depth": max_depth,
                },
            )
            _record_platform_assessment(
                cur,
                finding_id,
                key,
                "software_queue_stalled",
                _subject("queue", queue_key),
                now,
                measured=True,
            )
            continue
        if not _queue_is_measurable(cur, table_name):
            counts["queues_skipped"] += 1
            log.warning(
                "platform findings: queue %s (%s) not measurable — skipped",
                queue_key,
                table_name,
            )
            continue

        schema, _, table = table_name.partition(".")
        cur.execute(
            sql.SQL(
                """
                SELECT count(*) FILTER (WHERE status = 'pending'),
                       EXTRACT(EPOCH FROM (
                           now() - min(queued_at) FILTER (WHERE status = 'pending')
                       )) / 60
                  FROM {}
                """
            ).format(sql.Identifier(schema, table))
        )
        depth, oldest_age_m = cur.fetchone()
        depth = depth or 0
        oldest_age_m = float(oldest_age_m or 0)

        # A threshold of 0 means "unset", not "zero tolerance" — treat as off.
        over_depth = bool(max_depth) and depth > max_depth
        over_age = bool(max_age_m) and oldest_age_m > max_age_m
        if not (over_depth or over_age):
            continue

        key = f"software_queue_stalled:{queue_key}"
        keys.append(key)
        counts["software_queue_stalled"] += 1
        if dry_run:
            continue
        finding_id = _upsert_admin_finding(
            cur,
            finding_type_id=finding_type_id,
            condition_key=key,
            severity="high" if (over_depth and over_age) else "medium",
            now=now,
            subject_ref={
                "signal_kind": "queue",
                "signal_id": str(_subject("queue", queue_key)),
            },
            details={
                "queue_key": queue_key,
                "table_name": table_name,
                "pending_depth": depth,
                "max_depth": max_depth,
                "oldest_pending_minutes": round(oldest_age_m, 1),
                "max_pending_age_m": max_age_m,
                "breached": [
                    b for b, hit in (("depth", over_depth), ("age", over_age)) if hit
                ],
            },
        )
        _record_platform_assessment(
            cur,
            finding_id,
            key,
            "software_queue_stalled",
            _subject("queue", queue_key),
            now,
            measured=True,
        )
    return keys


def _eval_jobs_health(
    cur: Any,
    finding_types: dict[str, int | None],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
) -> dict[str, list[str]]:
    """Evaluate durable Jobs health through its restricted measurement API.

    The evaluator deliberately has no table privileges for the Jobs control
    relations.  The security-definer API returns only the bounded operational
    evidence needed to explain and link an Admin Finding.
    """
    cur.execute(
        "SELECT kind, payload FROM operations.jobs_health_measurements_v1(%s)",
        (TENANT_ID,),
    )
    measurements: dict[str, list[dict[str, Any]]] = {}
    for kind, payload in cur.fetchall():
        measurements.setdefault(kind, []).append(payload or {})

    keys = {name: [] for name in finding_types}
    _eval_jobs_schedule_failures(
        cur,
        finding_types["jobs_schedule_failure"],
        measurements.get("schedule_failure", []),
        now,
        counts,
        dry_run,
        keys["jobs_schedule_failure"],
    )
    _eval_jobs_required_disabled(
        cur,
        finding_types["jobs_required_disabled"],
        measurements.get("required_disabled", []),
        now,
        counts,
        dry_run,
        keys["jobs_required_disabled"],
    )
    _eval_jobs_queue_backlog(
        cur,
        finding_types["jobs_queue_backlog"],
        measurements.get("queue_backlog", []),
        now,
        counts,
        dry_run,
        keys["jobs_queue_backlog"],
    )
    _eval_jobs_repeated_failures(
        cur,
        finding_types["jobs_repeated_failure"],
        measurements.get("repeated_failure", []),
        now,
        counts,
        dry_run,
        keys["jobs_repeated_failure"],
    )
    _eval_jobs_timeouts(
        cur,
        finding_types["jobs_timeout"],
        measurements.get("timeout", []),
        now,
        counts,
        dry_run,
        keys["jobs_timeout"],
    )
    _eval_jobs_unmet_dependencies(
        cur,
        finding_types["jobs_unmet_dependency"],
        measurements.get("unmet_dependency", []),
        now,
        counts,
        dry_run,
        keys["jobs_unmet_dependency"],
    )
    _eval_jobs_registry_mismatch(
        cur,
        finding_types["jobs_registry_mismatch"],
        measurements.get("control_snapshot", []),
        now,
        counts,
        dry_run,
        keys["jobs_registry_mismatch"],
    )
    return keys


def _emit_jobs_finding(
    cur: Any,
    *,
    finding_type_id: int | None,
    type_name: str,
    condition_key: str,
    severity: str,
    subject_key: str,
    details: dict[str, Any],
    now: datetime,
    dry_run: bool,
) -> None:
    if finding_type_id is None:
        raise RuntimeError(f"Jobs finding type is missing: {type_name}")
    if dry_run:
        return
    subject_id = _subject("jobs", subject_key)
    finding_id = _upsert_admin_finding(
        cur,
        finding_type_id=finding_type_id,
        condition_key=condition_key,
        severity=severity,
        now=now,
        subject_ref={"signal_kind": "jobs", "signal_id": str(subject_id)},
        details=details,
    )
    _record_platform_assessment(
        cur, finding_id, condition_key, type_name, subject_id, now, measured=True
    )


def _eval_jobs_schedule_failures(
    cur: Any,
    finding_type_id: int | None,
    rows: list[dict[str, Any]],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
    keys: list[str],
) -> None:
    for row in rows:
        schedule_id = str(row["schedule_id"])
        key = f"jobs_schedule_failure:{schedule_id}"
        keys.append(key)
        counts["jobs_schedule_failure"] += 1
        outcome = str(row.get("last_outcome") or "")
        _emit_jobs_finding(
            cur,
            finding_type_id=finding_type_id,
            type_name="jobs_schedule_failure",
            condition_key=key,
            severity="high" if outcome in {"failed", "stalled"} else "medium",
            subject_key=schedule_id,
            details={
                **row,
                "control_section": "schedules",
                "job_key": row.get("job_key"),
            },
            now=now,
            dry_run=dry_run,
        )


def _eval_jobs_required_disabled(
    cur: Any,
    finding_type_id: int | None,
    rows: list[dict[str, Any]],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
    keys: list[str],
) -> None:
    for row in rows:
        schedule_id = str(row["schedule_id"])
        key = f"jobs_required_disabled:{schedule_id}"
        keys.append(key)
        counts["jobs_required_disabled"] += 1
        _emit_jobs_finding(
            cur,
            finding_type_id=finding_type_id,
            type_name="jobs_required_disabled",
            condition_key=key,
            severity="high",
            subject_key=schedule_id,
            details={
                **row,
                "control_section": "schedules",
                "job_key": row.get("job_key"),
            },
            now=now,
            dry_run=dry_run,
        )


def _eval_jobs_queue_backlog(
    cur: Any,
    finding_type_id: int | None,
    rows: list[dict[str, Any]],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
    keys: list[str],
) -> None:
    for row in rows:
        if not row.get("breached"):
            continue
        queue_key = str(row["queue_key"])
        key = f"jobs_queue_backlog:{queue_key}"
        keys.append(key)
        counts["jobs_queue_backlog"] += 1
        _emit_jobs_finding(
            cur,
            finding_type_id=finding_type_id,
            type_name="jobs_queue_backlog",
            condition_key=key,
            severity="high" if set(row["breached"]) == {"depth", "age"} else "medium",
            subject_key=queue_key,
            details={
                **row,
                "control_section": "runs",
            },
            now=now,
            dry_run=dry_run,
        )


def _eval_jobs_repeated_failures(
    cur: Any,
    finding_type_id: int | None,
    rows: list[dict[str, Any]],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
    keys: list[str],
) -> None:
    for row in rows:
        job_key = str(row["job_key"])
        key = f"jobs_repeated_failure:{job_key}"
        keys.append(key)
        counts["jobs_repeated_failure"] += 1
        _emit_jobs_finding(
            cur,
            finding_type_id=finding_type_id,
            type_name="jobs_repeated_failure",
            condition_key=key,
            severity="high",
            subject_key=job_key,
            details={**row, "control_section": "runs", "job_key": job_key},
            now=now,
            dry_run=dry_run,
        )


def _eval_jobs_timeouts(
    cur: Any,
    finding_type_id: int | None,
    rows: list[dict[str, Any]],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
    keys: list[str],
) -> None:
    for row in rows:
        run_id = str(row["job_run_id"])
        key = f"jobs_timeout:{run_id}"
        keys.append(key)
        counts["jobs_timeout"] += 1
        _emit_jobs_finding(
            cur,
            finding_type_id=finding_type_id,
            type_name="jobs_timeout",
            condition_key=key,
            severity="high",
            subject_key=run_id,
            details={**row, "control_section": "runs"},
            now=now,
            dry_run=dry_run,
        )


def _eval_jobs_unmet_dependencies(
    cur: Any,
    finding_type_id: int | None,
    rows: list[dict[str, Any]],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
    keys: list[str],
) -> None:
    for row in rows:
        dependency_id = str(row["dependency_id"])
        key = f"jobs_unmet_dependency:{dependency_id}"
        keys.append(key)
        counts["jobs_unmet_dependency"] += 1
        _emit_jobs_finding(
            cur,
            finding_type_id=finding_type_id,
            type_name="jobs_unmet_dependency",
            condition_key=key,
            severity="high" if row.get("state") == "blocked" else "medium",
            subject_key=dependency_id,
            details={**row, "control_section": "dependencies"},
            now=now,
            dry_run=dry_run,
        )


def _eval_jobs_registry_mismatch(
    cur: Any,
    finding_type_id: int | None,
    rows: list[dict[str, Any]],
    now: datetime,
    counts: dict[str, int],
    dry_run: bool,
    keys: list[str],
) -> None:
    if not rows:
        return
    snapshot = rows[0]
    stored_versions = {
        (row.get("definition_key"), row.get("definition_digest"))
        for row in snapshot.get("definition_versions", [])
    }
    expected_versions = {(item.key, item.snapshot_digest()) for item in definitions()}
    missing_versions = sorted(
        key for key, digest in expected_versions if (key, digest) not in stored_versions
    )
    schedules = {
        row.get("definition_key"): row for row in snapshot.get("schedules", [])
    }
    missing_schedules = sorted(
        {item.job_key for item in schedule_definitions()} - schedules.keys()
    )
    stale_schedules = sorted(
        key
        for key, row in schedules.items()
        if key in {item.key for item in definitions()}
        and row.get("definition_digest") != definition(key).snapshot_digest()
    )
    expected_lanes = dict(INITIAL_LANE_CAPACITIES)
    actual_lanes = {
        row.get("lane"): row.get("capacity") for row in snapshot.get("lane_limits", [])
    }
    expected_resources = {"execution:deployment": INITIAL_EXECUTION_CAPACITY}
    for item in definitions():
        for resource in item.resource_keys:
            expected_resources.setdefault(resource, 1)
    actual_resources = {
        row.get("resource_template"): row.get("capacity")
        for row in snapshot.get("resource_limits", [])
    }
    expected_digest = registry_digest()
    live = [
        row
        for row in snapshot.get("runtimes", [])
        if not row.get("stopped_at") and row.get("fresh")
    ]
    live_kinds = {str(row.get("runtime_kind")) for row in live}
    runtime_mismatch = sorted(
        {
            str(row.get("runtime_kind"))
            for row in live
            if row.get("registry_digest") != expected_digest
        }
    )
    missing_runtimes = sorted({"scheduler", "worker"} - live_kinds)
    issues: dict[str, Any] = {}
    if missing_versions:
        issues["missing_definition_versions"] = missing_versions
    if missing_schedules:
        issues["missing_schedules"] = missing_schedules
    if stale_schedules:
        issues["stale_schedules"] = stale_schedules
    if actual_lanes != expected_lanes:
        issues["lane_policy_mismatch"] = True
    if actual_resources != expected_resources:
        issues["resource_policy_mismatch"] = True
    if runtime_mismatch:
        issues["runtime_digest_mismatch"] = runtime_mismatch
    if missing_runtimes:
        issues["missing_runtime_heartbeats"] = missing_runtimes
    if not issues:
        return
    key = "jobs_registry_mismatch:control-plane"
    keys.append(key)
    counts["jobs_registry_mismatch"] += 1
    _emit_jobs_finding(
        cur,
        finding_type_id=finding_type_id,
        type_name="jobs_registry_mismatch",
        condition_key=key,
        severity="high",
        subject_key="control-plane",
        details={
            "job_key": "platform-health-evaluate",
            "control_section": "definition_versions",
            **issues,
        },
        now=now,
        dry_run=dry_run,
    )


def _record_platform_assessment(
    cur: Any,
    finding_id: uuid.UUID,
    condition_key: str,
    type_name: str,
    subject_id: uuid.UUID,
    now: datetime,
    *,
    measured: bool = False,
) -> None:
    participant = Participant("platform_signal", str(subject_id), "affected", TENANT_ID)
    condition = Condition(
        TENANT_ID,
        "admin",
        str(finding_id),
        type_name,
        condition_key,
        "open",
        (participant,),
    )
    record_assessment(
        cur,
        condition,
        (),
        EvaluationCoverage(measured, measured, measured, measured),
        now=now,
        reevaluation_key=f"platform:{condition_key}",
        participant=participant,
    )


def _queue_is_measurable(cur: Any, table_name: str | None) -> bool:
    """True when the registry's table exists and carries the expected columns."""
    if not table_name or "." not in table_name:
        return False
    schema, _, table = table_name.partition(".")
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table_name,))
    if not cur.fetchone()[0]:
        return False
    cur.execute(
        """
        SELECT count(*) FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s AND column_name = ANY(%s)
        """,
        (schema, table, list(_QUEUE_COLUMNS)),
    )
    return cur.fetchone()[0] == len(_QUEUE_COLUMNS)
