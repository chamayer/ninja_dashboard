"""Single-worker durable queue for operator-requested Jobs runs.

The queue is deliberately separate from source demand and external-action
queues: its entries represent registered platform work, not a source mutation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.errors import RaiseException, UndefinedFunction
from psycopg_pool import PoolTimeout

from ingest import db
from ingest.config import settings
from shared.jobs_registry import (
    REPLAY_SAFE_RECOVERY_EVIDENCE,
    RegistryValidationError,
    definition,
    definition_keys,
    definitions,
    registry_digest,
    schedule_definitions,
    validate_registry,
    workflow_edges,
)

log = logging.getLogger(__name__)
SCHEDULER_RUNTIME_ID = uuid.uuid4()


class JobCancellationRequested(RuntimeError):
    """Raised only at a reviewed worker stage boundary."""


class JobProgressRejected(RuntimeError):
    """The durable Jobs ledger no longer accepts a child heartbeat."""


@dataclass(frozen=True)
class JobExecutionResult:
    """Sanitized child result used for conditional dependency admission."""

    rows: int | None = None
    signals: tuple[str, ...] = ()
    result: dict[str, object] | None = None


# The registry is the executable catalog. `_execute` below is the one handler
# resolver, and focused tests verify that every registry definition has one.
validate_registry(executable_keys=definition_keys())


def register_definition_snapshots() -> None:
    """Register immutable, credential-free definitions before v1 admission."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        for job in definitions():
            cur.execute(
                """SELECT operations.jobs_register_definition(%s, %s, %s, %s::jsonb)""",
                (
                    job.key,
                    job.snapshot_digest(),
                    job.handler_version,
                    json.dumps(job.snapshot_metadata()),
                ),
            )


def register_recovery_policies() -> None:
    """Persist reviewed replay-safe policy for the current immutable revision."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            for job_key, evidence_summary in REPLAY_SAFE_RECOVERY_EVIDENCE.items():
                # A definition digest also captures scheduling and resource
                # metadata.  Those may legitimately change while a handler's
                # replay behavior does not.  Register every stored snapshot
                # made by this exact reviewed handler version, not just the
                # current metadata digest; a handler-version change still
                # deliberately requires a new recovery review.
                cur.execute(
                    """SELECT definition_digest
                         FROM operations.job_definition_versions
                        WHERE definition_key = %s AND handler_version = %s""",
                    (job_key, definition(job_key).handler_version),
                )
                for (definition_digest,) in cur.fetchall():
                    try:
                        cur.execute(
                            "SELECT operations.jobs_register_recovery_policy_v1(%s, %s, %s, %s)",
                            (1, job_key, definition_digest, evidence_summary),
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            f"Jobs recovery policy registration failed for {job_key}"
                        ) from exc
    except UndefinedFunction:
        return


def record_runtime_heartbeat(
    runtime_kind: str,
    runtime_identity: uuid.UUID,
    metadata: dict[str, object],
) -> bool:
    """Publish sanitized liveness without granting runtime table access."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT operations.jobs_runtime_heartbeat_v1(%s, %s, %s, %s, %s::jsonb)",
                (
                    1,
                    runtime_kind,
                    runtime_identity,
                    registry_digest(),
                    json.dumps(metadata),
                ),
            )
    except UndefinedFunction:
        log.info("Jobs runtime heartbeat migration is not available yet")
        return False
    except Exception:
        log.exception("Jobs %s heartbeat failed", runtime_kind)
        return False
    return True


def stop_runtime(runtime_kind: str, runtime_identity: uuid.UUID) -> bool:
    """Record a graceful runtime stop when the diagnostics API is available."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT operations.jobs_runtime_stop_v1(%s, %s, %s)",
                (1, runtime_kind, runtime_identity),
            )
    except UndefinedFunction:
        return False
    except Exception:
        log.exception("Jobs %s stop heartbeat failed", runtime_kind)
        return False
    return True


def reconcile_replay_safe_containment() -> int:
    """Release only holds backed by a durable, reviewed replay-safety policy."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT operations.jobs_reconcile_replay_safe_containment_v1(%s)",
                (1,),
            )
            released = int(cur.fetchone()[0])
    except UndefinedFunction:
        return 0
    except Exception:
        log.exception("Jobs replay-safe containment reconciliation failed")
        return 0
    if released:
        log.warning("Jobs reconciled %d replay-safe contained run(s)", released)
    return released


_REPLAY_WINDOW_HOURS = 6

_INTERRUPTED_REPLAY_SAFE_SQL = """
SELECT run.id, run.job_key, run.scope_identity, run.request_payload
  FROM operations.operator_job_runs run
  JOIN operations.job_recovery_assessments assessment
    ON assessment.tenant_id = run.tenant_id AND assessment.run_id = run.id
   AND assessment.recovery_mode = 'replay_safe'
 WHERE run.tenant_id = %s
   AND run.status = 'stalled' AND run.terminal_reason = 'worker_interrupted'
   AND run.completed_at > now() - %s * interval '1 hour'
   -- Once only: a replay that is interrupted again waits for an administrator.
   AND run.trigger_kind <> 'recovery'
   AND NOT EXISTS (SELECT 1 FROM operations.operator_job_runs retry
                    WHERE retry.tenant_id = run.tenant_id AND retry.retry_of_run_id = run.id)
   -- A later run of the same work (the next schedule) already covers it.
   AND NOT EXISTS (SELECT 1 FROM operations.operator_job_runs later
                    WHERE later.tenant_id = run.tenant_id AND later.job_key = run.job_key
                      AND later.scope_identity = run.scope_identity
                      AND later.requested_at > run.requested_at
                      AND later.status IN ('queued', 'running', 'completed'))
 ORDER BY run.requested_at
"""


def replay_interrupted_runs() -> int:
    """Request again the replay-safe runs a worker restart interrupted.

    ``reconcile_replay_safe_containment`` releases their claims; without a new
    request the work and everything it would admit (a source refresh admits
    the resolver and evaluators) waits for the next schedule. Only reviewed
    replay-safe definitions qualify (``REPLAY_SAFE_RECOVERY_EVIDENCE``,
    ADR-0024), each run is replayed at most once, and the request identity is
    derived from the interrupted run so a repeated call is idempotent.
    """
    replayed = 0
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(_INTERRUPTED_REPLAY_SAFE_SQL, (1, _REPLAY_WINDOW_HOURS))
            for run_id, job_key, scope_identity, payload in cur.fetchall():
                try:
                    job = definition(job_key)
                except RegistryValidationError:
                    continue
                cur.execute("SAVEPOINT replay_run")
                request_api = (
                    "operations.jobs_request_software_v1"
                    if job.supersession_family == "software-classifier"
                    else "operations.jobs_request"
                )
                try:
                    cur.execute(
                        f"SELECT {request_api}(%s, %s, %s, %s, %s, %s, NULL, %s::jsonb,"
                        " %s::jsonb, NULL)",
                        (
                            1,
                            job.key,
                            job.snapshot_digest(),
                            scope_identity,
                            hashlib.sha256(f"recovery:{run_id}".encode()).hexdigest(),
                            "recovery",
                            json.dumps(payload or {}),
                            "{}",
                        ),
                    )
                    new_run_id = cur.fetchone()[0]
                    cur.execute(
                        "SELECT operations.jobs_link_retry_v1(%s, %s, %s)",
                        (1, new_run_id, run_id),
                    )
                    _admit_workflow(cur, job.key, new_run_id, scope_identity)
                except RaiseException:
                    # Refused by the Jobs API (e.g. an equivalent run is queued).
                    cur.execute("ROLLBACK TO SAVEPOINT replay_run")
                    continue
                cur.execute("RELEASE SAVEPOINT replay_run")
                replayed += 1
    except UndefinedFunction:
        return 0
    except Exception:
        log.exception("Jobs replay of interrupted runs failed")
        return 0
    if replayed:
        log.warning("Jobs requested %d interrupted replay-safe run(s) again", replayed)
    return replayed


def _schedule_cadence(schedule: Any) -> dict[str, int | str]:
    """Resolve one registry cadence into bounded, persisted UTC metadata."""
    if schedule.cadence_setting == "PATCH_INGEST_SCHEDULE_HOURS":
        value = settings.patch_ingest_schedule_hours
    elif schedule.cadence_setting == "OBSERVATION_HISTORY_RETENTION_HOUR":
        value = getattr(settings, schedule.cadence_setting, 3)
    elif schedule.cadence_setting.startswith("constant:"):
        value = int(schedule.cadence_setting.partition(":")[2])
    else:
        value = int(getattr(settings, schedule.cadence_setting))
    if schedule.cadence_unit == "hours":
        return {"kind": "interval", "minutes": value * 60}
    if schedule.cadence_unit == "minutes":
        return {"kind": "interval", "minutes": value}
    if schedule.cadence_unit == "cron-hour":
        return {"kind": "daily", "hour": value}
    raise ValueError(f"Unsupported Jobs cadence unit: {schedule.cadence_unit}")


# Jobs with capability "pending_work" and the query that says work is waiting.
_PENDING_WORK_QUERIES = {
    "source-actions": (
        "SELECT EXISTS (SELECT 1 FROM operations.source_action_requests WHERE status = 'pending')"
    ),
}


def _schedule_enabled(job_key: str) -> tuple[bool, str]:
    """Apply the existing capability gates before automatic admission."""
    job = definition(job_key)
    if job.capability == "pending_work":
        # The schedule runs only while the Job has pending work.
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(_PENDING_WORK_QUERIES[job_key])
            pending = cur.fetchone()[0]
        return pending, "Available" if pending else "Waiting for pending work."
    enabled = {
        "always": True,
        "intel": settings.INTEL_ENABLED,
        "notifications": settings.NOTIFY_ENABLED,
        "notification_digest": settings.NOTIFY_DIGEST_ENABLED,
        "software_queue": settings.SOFTWARE_QUEUE_ENABLED,
    }.get(job.capability, False)
    return (
        enabled,
        "Available" if enabled else f"Disabled — {job.capability} is not enabled.",
    )


def reconcile_schedule_catalog() -> bool:
    """Make durable tenant schedules exactly match the catalog declaration."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            schedules = schedule_definitions()
            for schedule in schedules:
                job = definition(schedule.job_key)
                cadence = _schedule_cadence(schedule)
                enabled, capability_reason = _schedule_enabled(job.key)
                revision = hashlib.sha256(
                    json.dumps(
                        {"cadence": cadence, "enabled": enabled},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                cur.execute(
                    "SELECT operations.jobs_reconcile_schedule_v2(%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        1,
                        job.key,
                        job.snapshot_digest(),
                        "tenant:1",
                        revision,
                        json.dumps(cadence),
                        enabled,
                        capability_reason,
                    ),
                )
            # A Job that now starts only after its prerequisite must not retain
            # an old independent tenant schedule. The registry owns this
            # lifecycle too; otherwise an obsolete schedule can both mislead
            # health and create duplicate work.
            cur.execute(
                "SELECT operations.jobs_disable_retired_tenant_schedules_v1(%s, %s::text[])",
                (1, [schedule.job_key for schedule in schedules]),
            )
    except UndefinedFunction:
        # Operations owns Django migrations and can become ready after ingest.
        # The producer retries this idempotent registration before admission.
        log.info("durable Jobs schedule migration is not available yet")
        return False
    return True


def _source_cadence(schedule: str) -> dict[str, int] | None:
    """Parse the deliberately small, data-owned source schedule contract."""
    prefix, separator, minutes_text = (schedule or "").partition(":")
    if prefix != "interval" or not separator:
        return None
    try:
        minutes = int(minutes_text)
    except ValueError:
        return None
    if not 1 <= minutes <= 10080:
        return None
    return {"kind": "interval", "minutes": minutes}


def reconcile_source_refresh_schedules() -> bool:
    """Reconcile one generic source-refresh schedule for every source binding.

    Schedule data remains on ``source_bindings``.  Jobs owns execution only;
    it receives a normal durable schedule whose scope is that exact binding.
    """
    job = definition("source-refresh")
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT binding.id, binding.enabled, instance.enabled, binding.schedule
                 FROM operations.source_bindings binding
                  JOIN operations.source_instances instance
                    ON instance.id = binding.source_instance_id
                 WHERE binding.tenant_id = 1 AND instance.tenant_id = 1
                """
            )
            for binding_id, enabled, instance_enabled, schedule in cur.fetchall():
                cadence = _source_cadence(schedule or "")
                scheduled = bool(enabled and instance_enabled and cadence)
                reason = (
                    "Configured source schedule."
                    if scheduled
                    else "Disabled — set a valid source refresh schedule."
                )
                revision = hashlib.sha256(
                    json.dumps(
                        {
                            "binding_id": str(binding_id),
                            "enabled": scheduled,
                            "cadence": cadence or {},
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                cur.execute(
                    "SELECT operations.jobs_reconcile_schedule_v2(%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        1,
                        job.key,
                        job.snapshot_digest(),
                        f"source-binding:{binding_id}",
                        revision,
                        json.dumps(cadence or {"kind": "interval", "minutes": 60}),
                        scheduled,
                        reason,
                    ),
                )
    except UndefinedFunction:
        log.info("source refresh schedule API is not available yet")
        return False
    except Exception:
        log.exception("source refresh schedule reconciliation failed")
        return False
    return True


def _next_due_at(due_at: datetime, cadence: dict[str, Any], now: datetime) -> datetime:
    """Coalesce missed ticks into one request and advance beyond the present."""
    interval = timedelta(
        days=1 if cadence["kind"] == "daily" else 0,
        minutes=0 if cadence["kind"] == "daily" else int(cadence["minutes"]),
    )
    candidate = due_at + interval
    while candidate <= now:
        candidate += interval
    return candidate


def _admit_workflow(
    cur: Any,
    root_key: str,
    root_run_id: uuid.UUID,
    root_scope_identity: str = "tenant:1",
    conditions: frozenset[str] = frozenset({"always"}),
) -> None:
    """Create matching successor runs and revision edges atomically."""
    runs = {root_key: root_run_id}
    # The scope each run in this workflow holds. The database requires an
    # "inherit" dependent to share its PREREQUISITE's scope, not the root's:
    # below a tenant-scoped edge (source-refresh -> resolver) the prerequisite is
    # "tenant:1" even though the root is bound to one source. Sending the
    # root's scope there made admission raise and failed the whole refresh.
    scopes = {root_key: root_scope_identity}
    for edge in workflow_edges(root_key, conditions):
        prerequisite_id = runs[edge.prerequisite]
        dependent = definition(edge.dependent)
        request_api = (
            "operations.jobs_request_software_v1"
            if dependent.supersession_family == "software-classifier"
            else "operations.jobs_request"
        )
        request_identity = hashlib.sha256(
            f"workflow:{root_run_id}:{edge.dependent}:{edge.revision_name}".encode()
        ).hexdigest()
        dependent_scope = (
            scopes[edge.prerequisite] if edge.scope_mode == "inherit" else "tenant:1"
        )
        scopes[edge.dependent] = dependent_scope
        cur.execute(
            f"SELECT {request_api}(%s, %s, %s, %s, %s, %s, NULL, %s::jsonb, %s::jsonb, %s)",
            (
                1,
                dependent.key,
                dependent.snapshot_digest(),
                dependent_scope,
                request_identity,
                "dependency",
                "{}",
                "{}",
                root_run_id,
            ),
        )
        dependent_id = cur.fetchone()[0]
        runs[edge.dependent] = dependent_id
        required_revision = hashlib.sha256(
            f"{prerequisite_id}:{edge.revision_name}:{dependent_scope}".encode()
        ).hexdigest()
        cur.execute(
            "SELECT operations.jobs_add_revision_dependency_v1(%s, %s, %s, %s, %s, %s)",
            (
                1,
                dependent_id,
                prerequisite_id,
                edge.revision_name,
                dependent_scope,
                required_revision,
            ),
        )


def admit_result_workflow(
    root_key: str,
    root_run_id: uuid.UUID,
    signals: tuple[str, ...],
    root_scope_identity: str = "tenant:1",
) -> None:
    """Admit only registry-approved conditional edges from a fenced result."""
    approved = frozenset(signals) - {"always"}
    if not approved:
        return
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        _admit_workflow(cur, root_key, root_run_id, root_scope_identity, approved)


def _run_source_actions(job_run_id: object) -> JobExecutionResult:
    from ingest import source_actions

    outcome = source_actions.process_pending(job_run_id=job_run_id)
    signals = ("documentation_source",) if outcome["completed"] else ()
    return JobExecutionResult(rows=sum(outcome.values()), signals=signals)


def _source_refresh_binding(job_run_id: object, claim_token: uuid.UUID) -> uuid.UUID:
    """Read the fenced source scope for a running generic refresh."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT operations.jobs_source_refresh_context_v1(%s, %s, %s)",
            (1, job_run_id, claim_token),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("Source refresh run has no configured source scope")
    return row[0] if isinstance(row[0], uuid.UUID) else uuid.UUID(str(row[0]))


def _run_source_refresh(progress: "V1JobProgress") -> JobExecutionResult:
    """Refresh exactly one configured source binding through the shared contract."""
    from ingest import main
    from ingest.source_observations import is_identity_source, run_source_observations
    from ingest.sources import load_source_binding

    binding_id = _source_refresh_binding(progress.job_id, progress.claim_token)
    source = load_source_binding(binding_id)
    source_label = source.source_name or source.platform
    progress.update(f"Collecting {source_label} information", "")
    observed_at = datetime.now(timezone.utc)
    if source.platform == "Ninja":
        if main.run_ninja_devices_once() is False:
            raise RuntimeError("Ninja collection could not acquire its execution lock")
        rows = None
        signals = ("identity_source",)
    elif source.source_key.startswith("reference."):
        from ingest.intel import (
            abusech,
            chocolatey,
            cisa_kev,
            cpe_dict,
            epss,
            lolrmm,
            nvd,
            otx,
            winget,
        )

        handlers = {
            "reference.nvd": nvd.run_once,
            "reference.cpe": cpe_dict.run_once,
            "reference.kev": cisa_kev.run_once,
            "reference.epss": epss.run_once,
            "reference.otx": otx.run_once,
            "reference.abusech": abusech.run_once,
            "reference.winget": winget.run_once,
            "reference.chocolatey": chocolatey.run_once,
            "reference.remote-access": lolrmm.run_once,
            "reference.end-of-life": main.run_intel_endoflife_once,
        }
        try:
            handler = handlers[source.source_key]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported reference source: {source.source_key}"
            ) from exc
        result = handler()
        rows = int(result) if isinstance(result, int) else None
        if not bool(getattr(result, "material_changed", False)):
            signals = ()
        elif source.source_key in {
            "reference.nvd",
            "reference.cpe",
            "reference.kev",
            "reference.epss",
        }:
            signals = ("reference_match_data",)
        else:
            signals = ("reference_software_data",)
            # Reference software data cannot name the titles it affects.
            _request_whole_fleet_findings(f"source-refresh:{source.source_key}")
    else:
        counts = run_source_observations([source], observed_at)
        rows = sum(counts.values())
        main.refresh_after_collection(f"{source_label} source refresh")
        signals = (
            ("identity_source",)
            if is_identity_source(source)
            else ("documentation_source",)
        )
    return JobExecutionResult(
        rows=rows,
        signals=signals,
        result={"source_refresh": {"binding_id": str(binding_id)}},
    )


def produce_due_schedules() -> int:
    """Elect a short-lived leader and atomically admit each due durable schedule."""
    admitted = 0
    record_runtime_heartbeat(
        "scheduler",
        SCHEDULER_RUNTIME_ID,
        {
            "definition_count": len(definitions()),
            "leader_mode": "short_lived_advisory",
            "poll_seconds": 60,
        },
    )
    if not reconcile_schedule_catalog() or not reconcile_source_refresh_schedules():
        return admitted
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SET operations.tenant_id = 1")
            cur.execute("SELECT operations.jobs_try_schedule_leader()")
            if not cur.fetchone()[0]:
                return 0
            try:
                cur.execute(
                    "SELECT schedule_id, due_at, cadence "
                    "FROM operations.jobs_list_due_schedules_v1(%s)",
                    (1,),
                )
                due_schedules = cur.fetchall()
                now = datetime.now(timezone.utc)
                for schedule_id, due_at, cadence in due_schedules:
                    try:
                        # A legacy row can still be draining for one family.
                        # Keep that rejection isolated so another due schedule
                        # is not rolled back with it.
                        with conn.transaction():
                            next_due_at = _next_due_at(due_at, cadence, now)
                            request_identity = hashlib.sha256(
                                f"schedule:{schedule_id}:{due_at.isoformat()}".encode()
                            ).hexdigest()
                            cur.execute(
                                "SELECT operations.jobs_claim_due_schedule(%s, %s, %s, %s, %s)",
                                (1, schedule_id, due_at, next_due_at, request_identity),
                            )
                            run_id = cur.fetchone()[0]
                            if run_id is not None:
                                cur.execute(
                                    "SELECT definition_key, scope_identity FROM operations.job_schedules "
                                    "WHERE tenant_id = 1 AND id = %s",
                                    (schedule_id,),
                                )
                                definition_key, scope_identity = cur.fetchone()
                                _admit_workflow(
                                    cur, definition_key, run_id, scope_identity
                                )
                                admitted += 1
                    except Exception:
                        log.exception(
                            "durable Jobs schedule %s was deferred", schedule_id
                        )
            finally:
                cur.execute("SELECT operations.jobs_release_schedule_leader()")
    except PoolTimeout:
        log.warning("durable Jobs schedules waiting for database capacity")
        return 0
    except Exception:
        log.exception("durable Jobs schedule producer failed")
        return 0
    if admitted:
        log.info("durable Jobs schedule producer admitted %d run(s)", admitted)
    return admitted


def lane_for(job_key: str) -> str:
    """Return the registered worker lane for a durable Jobs definition."""
    return definition(job_key).lane


class V1JobProgress:
    """Record v1 progress exclusively through the fenced Jobs API."""

    def __init__(self, job_id: Any, claim_token: uuid.UUID) -> None:
        self.job_id = job_id
        self.claim_token = claim_token

    def update(self, stage: str, detail: str = "") -> None:
        if self.cancel_requested():
            raise JobCancellationRequested("Cancellation requested by an operator.")
        self._record(stage, detail)

    def heartbeat(self) -> None:
        self._record(None, None)

    def count(self, done: int, total: int | None, unit: str) -> None:
        """Record how far the run is (done of total, in ``unit``) for the Jobs pages.

        Also renews the heartbeat. Before Operations migration 0287 exists (a
        deploy that starts ingest first) the count is skipped, not fatal.
        """
        if self.cancel_requested():
            raise JobCancellationRequested("Cancellation requested by an operator.")
        try:
            with db.transaction() as cur:
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute(
                    "SELECT operations.jobs_record_v1_count(%s, %s, %s, %s, %s, %s)",
                    (
                        1,
                        self.job_id,
                        self.claim_token,
                        max(0, int(done)),
                        None if total is None else max(0, int(total)),
                        unit[:40],
                    ),
                )
        except UndefinedFunction:
            self.heartbeat()
        except RaiseException as exc:
            raise JobProgressRejected(
                "Jobs ledger rejected the progress count."
            ) from exc

    def cancel_requested(self) -> bool:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT operations.jobs_should_cancel_v1(%s, %s, %s)",
                (1, self.job_id, self.claim_token),
            )
            return bool(cur.fetchone()[0])

    def _record(self, stage: str | None, detail: str | None) -> None:
        try:
            with db.transaction() as cur:
                cur.execute("SET LOCAL operations.tenant_id = 1")
                cur.execute(
                    "SELECT operations.jobs_record_v1_progress(%s, %s, %s, %s, %s)",
                    (1, self.job_id, self.claim_token, stage, detail),
                )
        except RaiseException as exc:
            raise JobProgressRejected("Jobs ledger rejected child progress.") from exc


def request_system_job(job_key: str, request_source: str) -> uuid.UUID:
    """Admit an explicit internal HTTP request through the governed v1 API."""
    job = definition(job_key)
    request_identity = hashlib.sha256(
        f"system:{request_source}:{job_key}:{uuid.uuid4()}".encode()
    ).hexdigest()
    request_api = (
        "operations.jobs_request_software_v1"
        if job.supersession_family == "software-classifier"
        else "operations.jobs_request"
    )
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"SELECT {request_api}(%s, %s, %s, %s, %s, %s, NULL, %s::jsonb, %s::jsonb, NULL)",
            (
                1,
                job.key,
                job.snapshot_digest(),
                "tenant:1",
                request_identity,
                "automatic",
                "{}",
                "{}",
            ),
        )
        row = cur.fetchone()
        if row is not None:
            _admit_workflow(cur, job.key, row[0])
    if row is None:
        raise RuntimeError("Jobs request API did not return a run")
    return row[0]


def contain_expired_v1() -> int:
    """Make expired converted work visible without releasing unsafe claims."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute("SELECT operations.jobs_contain_expired_v1(%s)", (1,))
        return cur.fetchone()[0]


def dispatch_ready_v1() -> int:
    """Promote at most the durable Ready window before workers claim it."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute("SELECT operations.jobs_dispatch_ready_v1(%s)", (1,))
            return int(cur.fetchone()[0])
    except UndefinedFunction:
        return 0


def _claim_next_v7(worker_incarnation: uuid.UUID) -> dict[str, Any] | None:
    """Claim one Ready run, including source-binding resource identity."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """SELECT claimed.run_id, claimed.claim_token, claimed.job_key, run.scope_identity
                     FROM operations.jobs_claim_next_v7(%s, %s) AS claimed
                     JOIN operations.operator_job_runs run
                       ON run.tenant_id = 1 AND run.id = claimed.run_id""",
                (1, worker_incarnation),
            )
            row = cur.fetchone()
    except UndefinedFunction:
        return None
    if row is None:
        return None
    return {
        "id": row[0],
        "claim_token": row[1],
        "job_key": row[2],
        "scope_identity": row[3],
    }


def _finish_v1(
    job_id: Any,
    claim_token: uuid.UUID,
    status: str,
    *,
    rows: int | None = None,
    error: str = "",
    result: dict[str, object] | None = None,
) -> None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT operations.jobs_finish_v1(%s, %s, %s, %s, %s, %s, %s::jsonb)",
            (1, job_id, claim_token, status, rows, error, json.dumps(result or {})),
        )


def _finish_cancelled_v1(job_id: Any, claim_token: uuid.UUID) -> None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT operations.jobs_finish_cancelled_v1(%s, %s, %s)",
            (1, job_id, claim_token),
        )


def _interrupt_v1(job_id: Any, claim_token: uuid.UUID, reason: str) -> bool:
    """Fence an interrupted child and retain its claims for manual review."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT operations.jobs_interrupt_v1(%s, %s, %s, %s)",
            (1, job_id, claim_token, reason[:500]),
        )
        return bool(cur.fetchone()[0])


def _execute(job_key: str, progress: V1JobProgress) -> int | JobExecutionResult | None:
    """Run a catalog job synchronously in the bounded queue worker.

    Importing main here avoids its startup import cycle. The direct lower-level
    functions intentionally raise, allowing the durable record to show failure.
    """
    from ingest import cmdb_findings, main, platform_findings, runlog
    from ingest.intel import (
        abusech,
        capability_match,
        category_match,
        chocolatey,
        cisa_kev,
        cpe_dict,
        epss,
        lolrmm,
        matcher,
        nvd,
        otx,
        winget,
    )

    jobs = {
        "source-refresh": (
            "Collecting source information",
            lambda: _run_source_refresh(progress),
        ),
        "patch-classify": (
            "Classifying changed patch state",
            lambda: main.patch_classify(tenant_id=1, incremental=True),
        ),
        "platform-evaluate": (
            "Evaluating platform conditions",
            lambda: _platform_evaluate_and_check(),
        ),
        "cmdb-evaluate": (
            "Evaluating CMDB conditions",
            lambda: sum(cmdb_findings.evaluate(dry_run=False).values()),
        ),
        "software-classify-only": (
            "Reconciling software findings",
            lambda: _software_reconcile(progress),
        ),
        "software-classify-full": (
            "Reconciling software findings",
            lambda: _software_reconcile(progress),
        ),
        "resolver": (
            "Resolving computer identity",
            lambda: main.run_identity_resolver_once(),
        ),
        "patches": (
            "Collecting Ninja patches and activity",
            lambda: main.run_patching_once(),
        ),
        "ninja-enrichment": (
            "Collecting Ninja enrichment",
            lambda: main.run_ninja_enrichment_once(),
        ),
        "agent-observations": (
            "Collecting agent observations",
            lambda: main.run_agent_observations_once(),
        ),
        "documentation-observations": (
            "Collecting Hudu records",
            lambda: main.run_documentation_observations_once(),
        ),
        "retention-history": (
            "Cleaning closed history",
            lambda: main.run_observation_history_prune_once(),
        ),
        "software-enqueue-orgs": (
            "Checking every computer's software list",
            lambda: main.run_software_fleet_check_once(progress.count),
        ),
        "software-queue-drain": (
            "Refreshing changed computers' software lists",
            lambda: main.run_software_queue_once(progress.job_id, progress.count),
        ),
        "source-actions": (
            "Processing approved source actions",
            lambda: _run_source_actions(progress.job_id),
        ),
        "run-log-recovery": ("Recovering stale diagnostics", runlog.reap_stale),
        "platform-health-evaluate": (
            "Evaluating platform health",
            lambda: sum(platform_findings.evaluate(dry_run=False).values()),
        ),
        "notifications-dispatch": (
            "Sending notifications",
            lambda: main.notify_dispatch(tenant_id=1),
        ),
        "notifications-digest": (
            "Preparing notification digest",
            lambda: main.notify_send_digest(tenant_id=1),
        ),
        "intel-nvd": ("Refreshing NVD intelligence", nvd.run_once),
        "intel-cpe-dict": ("Refreshing CPE dictionary", cpe_dict.run_once),
        "intel-kev": (
            "Refreshing exploited-vulnerability intelligence",
            cisa_kev.run_once,
        ),
        "intel-epss": ("Refreshing exploit-likelihood scores", epss.run_once),
        "intel-matcher": ("Matching software to vulnerabilities", matcher.run_once),
        "intel-winget": ("Refreshing Windows package intelligence", winget.run_once),
        "intel-chocolatey": ("Refreshing Chocolatey intelligence", chocolatey.run_once),
        "intel-capability": (
            "Projecting software capabilities",
            capability_match.run_once,
        ),
        "intel-lolrmm": ("Refreshing remote-management intelligence", lolrmm.run_once),
        "intel-otx": ("Refreshing threat intelligence", otx.run_once),
        "intel-abusech": ("Refreshing malware intelligence", abusech.run_once),
        "intel-endoflife": (
            "Refreshing end-of-life intelligence",
            lambda: main.run_intel_endoflife_once(),
        ),
        "intel-category": ("Refreshing software categories", category_match.run_once),
    }
    if job_key == "software-classify":
        return _software_classify_with_intel(
            progress, matcher, winget, chocolatey, main
        )
    if job_key in ("software-classify-only", "software-classify-full"):
        return _software_reconcile(
            progress, whole_fleet=job_key == "software-classify-full"
        )
    if job_key not in jobs:
        raise ValueError(f"Unknown registered job: {job_key}")
    stage, job = jobs[job_key]
    progress.update(stage, "")
    result = job()
    if (
        bool(getattr(result, "material_changed", False))
        and job_key not in _software_title_scoped_producers()
        and any(
            s.successor == "software-classify-only"
            for s in definition(job_key).successors
        )
    ):
        _request_whole_fleet_findings(job_key)
    if job_key in ("patches", "ninja-enrichment") and result is False:
        raise RuntimeError(f"{job_key} could not acquire its database execution lock")
    if isinstance(result, JobExecutionResult):
        return result
    if bool(getattr(result, "material_changed", False)) and any(
        successor.condition == "material_change"
        for successor in definition(job_key).successors
    ):
        return JobExecutionResult(rows=result, signals=("material_change",))
    return int(result) if isinstance(result, int) else None


def _software_title_scoped_producers() -> frozenset[str]:
    # Jobs that record the exact titles they changed in the change feed
    # (inventory apply, vulnerability matching). Every other producer of
    # software findings input asks for a whole-fleet run.
    return frozenset({"software-queue-drain", "software-enqueue-orgs", "intel-matcher"})


def _request_whole_fleet_findings(source: str) -> None:
    from ingest import software_reconcile

    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        software_reconcile.record_whole_fleet(cur, 1, source)


def _platform_evaluate_and_check():
    """Platform evaluation, then the stored-state consistency checks.

    See finding_attention (finding state) and requirement_state (requirement
    verdicts, ADR-0035).
    """
    from ingest import db, finding_attention, main, requirement_state

    affected = main.platform_evaluate(tenant_id=1)
    with db.transaction() as cur:
        finding_attention.check_and_repair_state(cur, 1)
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        requirement_state.check_state(cur, 1)
    return affected


def _software_reconcile(
    progress: V1JobProgress, *, whole_fleet: bool
) -> JobExecutionResult:
    """Reconcile software findings and publish the exposure read model.

    The routine run (``software-classify-only``) covers only the titles the
    change feed names (inventory changes, vulnerability matches); a producer
    that cannot name titles asks for the whole fleet. The full run (daily, and
    after every decision) always covers the whole fleet. Either way the run
    clears the change-feed rows it covered, and only after it succeeded.
    """
    from ingest import software_reconcile
    from ingest.inventory import software as software_inventory

    target_ids, titles = software_reconcile.pending_scope(1, whole_fleet=whole_fleet)
    if titles == []:
        software_reconcile.consume_targets(1, target_ids)
        return JobExecutionResult(
            rows=0, result={"summary": "No changed software titles to reconcile."}
        )
    report = software_reconcile.run(
        1, progress=progress.update, count=progress.count, titles=titles
    )
    progress.update(
        "Publishing software status",
        "Making the reconciled findings available to operators.",
    )
    if titles is None:
        # The safety read model does not read findings; inventory and decision
        # changes refresh it themselves. A whole-fleet run also covers
        # intelligence changes, which it does read.
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW operations.v_software_safety")
    software_inventory.refresh_exposure_read_model()
    software_reconcile.consume_targets(1, target_ids)
    result = report.as_result()
    rows = (
        sum(result["opened"].values())
        + sum(result["refreshed"].values())
        + sum(result["resolved"].values())
    )
    return JobExecutionResult(rows=rows, result=result)


def _software_classify_with_intel(
    progress: V1JobProgress, matcher: Any, winget: Any, chocolatey: Any, main: Any
) -> int | JobExecutionResult | None:
    """Run the advertised auto-intel sequence, then the software reconcile."""
    if main.settings.INTEL_ENABLED:
        for stage, job in (
            ("Matching software to vulnerabilities", matcher.run_once),
            ("Refreshing Windows package intelligence", winget.run_once),
            ("Refreshing Chocolatey intelligence", chocolatey.run_once),
        ):
            progress.update(stage, "")
            job()
    return _software_reconcile(progress, whole_fleet=True)
