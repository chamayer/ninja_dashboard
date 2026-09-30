"""Single-worker durable queue for operator-requested Jobs runs.

The queue is deliberately separate from source demand and external-action
queues: its entries represent registered platform work, not a source mutation.
"""

from __future__ import annotations

import json
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.errors import UndefinedFunction
from psycopg_pool import PoolTimeout

from ingest import db
from ingest.config import settings
from shared.jobs_registry import (
    definition,
    definitions,
    schedule_definitions,
    validate_registry,
    workflow_edges,
)

log = logging.getLogger(__name__)


class JobCancellationRequested(RuntimeError):
    """Raised only at a reviewed worker stage boundary."""

# Keep this independent from the registry so an omitted or extra dispatcher
# handler prevents readiness instead of becoming an unreviewed live path.
EXECUTABLE_JOB_KEYS = frozenset(
    {
        "patch-classify", "platform-evaluate", "parity-check", "software-classify-only",
        "software-classify-full", "resolver", "patches", "agent-observations",
        "documentation-observations", "agent-compliance", "agent-compliance-evaluate",
        "retention-history", "software-enqueue-orgs", "software-queue-drain",
        "notifications-dispatch", "notifications-digest", "intel-nvd", "intel-cpe-dict",
        "intel-kev", "intel-epss", "intel-matcher", "intel-winget", "intel-chocolatey",
        "intel-capability", "intel-lolrmm", "intel-otx", "intel-abusech",
        "intel-endoflife", "intel-category", "software-classify",
        "source-actions",
        "source-demand",
        "agent-compliance-review-digest",
        "source-demand-recovery",
        "run-log-recovery",
        "platform-health-evaluate",
    }
)
validate_registry(executable_keys=EXECUTABLE_JOB_KEYS)


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


def _schedule_enabled(job_key: str) -> tuple[bool, str]:
    """Apply the existing capability gates before automatic admission."""
    job = definition(job_key)
    if job_key in {"source-demand", "source-actions"}:
        table = (
            "operations.source_run_queue"
            if job_key == "source-demand"
            else "operations.source_action_requests"
        )
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE status = 'pending')")
            pending = cur.fetchone()[0]
        label = "source demand" if job_key == "source-demand" else "source actions"
        return pending, "Available" if pending else f"Waiting for {label}."
    enabled = {
        "always": True,
        "intel": settings.INTEL_ENABLED,
        "notifications": settings.NOTIFY_ENABLED,
        "notification_digest": settings.NOTIFY_DIGEST_ENABLED,
        "software_queue": settings.SOFTWARE_QUEUE_ENABLED,
        "legacy_agent_compliance": settings.AGENT_COMPLIANCE_ENABLED,
    }.get(job.capability, False)
    return enabled, "Available" if enabled else f"Disabled — {job.capability} is not enabled."


def reconcile_schedule_catalog() -> bool:
    """Reconcile every declared cadence before the durable producer runs."""
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            for schedule in schedule_definitions():
                job = definition(schedule.job_key)
                cadence = _schedule_cadence(schedule)
                enabled, capability_reason = _schedule_enabled(job.key)
                revision = hashlib.sha256(
                    json.dumps(
                        {"cadence": cadence, "enabled": enabled},
                        sort_keys=True, separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                cur.execute(
                    "SELECT operations.jobs_reconcile_schedule_v2(%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (1, job.key, job.snapshot_digest(), "tenant:1", revision, json.dumps(cadence), enabled, capability_reason),
                )
    except UndefinedFunction:
        # Operations owns Django migrations and can become ready after ingest.
        # The producer retries this idempotent registration before admission.
        log.info("durable Jobs schedule migration is not available yet")
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


def _admit_workflow(cur: Any, root_key: str, root_run_id: uuid.UUID) -> None:
    """Create declared successor runs and completion edges atomically."""
    runs = {root_key: root_run_id}
    for prerequisite_key, dependent_key in workflow_edges(root_key):
        prerequisite_id = runs[prerequisite_key]
        dependent = definition(dependent_key)
        request_api = (
            "operations.jobs_request_software_v1"
            if dependent.supersession_family == "software-classifier"
            else "operations.jobs_request"
        )
        request_identity = hashlib.sha256(
            f"workflow:{root_run_id}:{dependent_key}".encode()
        ).hexdigest()
        cur.execute(
            f"SELECT {request_api}(%s, %s, %s, %s, %s, %s, NULL, %s::jsonb, %s::jsonb, %s)",
            (
                1, dependent.key, dependent.snapshot_digest(), "tenant:1",
                request_identity, "dependency", "{}", "{}", root_run_id,
            ),
        )
        dependent_id = cur.fetchone()[0]
        runs[dependent_key] = dependent_id
        cur.execute(
            "SELECT operations.jobs_add_completion_dependency_v1(%s, %s, %s)",
            (1, dependent_id, prerequisite_id),
        )


def produce_due_schedules() -> int:
    """Elect a short-lived leader and atomically admit each due durable schedule."""
    admitted = 0
    if not reconcile_schedule_catalog():
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
                                    "SELECT definition_key FROM operations.job_schedules "
                                    "WHERE tenant_id = 1 AND id = %s",
                                    (schedule_id,),
                                )
                                _admit_workflow(cur, cur.fetchone()[0], run_id)
                                admitted += 1
                    except Exception:
                        log.exception("durable Jobs schedule %s was deferred", schedule_id)
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


WORKER_LANES = ("collection", "evaluation", "software", "intelligence", "service")


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

    def cancel_requested(self) -> bool:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT operations.jobs_should_cancel_v1(%s, %s, %s)",
                (1, self.job_id, self.claim_token),
            )
            return bool(cur.fetchone()[0])

    def _record(self, stage: str | None, detail: str | None) -> None:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT operations.jobs_record_v1_progress(%s, %s, %s, %s, %s)",
                (1, self.job_id, self.claim_token, stage, detail),
            )


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
            (1, job.key, job.snapshot_digest(), "tenant:1", request_identity,
             "automatic", "{}", "{}"),
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


def _claim_next_v1(lane: str, worker_incarnation: uuid.UUID) -> dict[str, Any] | None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT run_id, claim_token, job_key FROM operations.jobs_claim_next_v3(%s, %s, %s)",
            (1, lane, worker_incarnation),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "claim_token": row[1], "job_key": row[2]}


def _finish_v1(
    job_id: Any,
    claim_token: uuid.UUID,
    status: str,
    *,
    rows: int | None = None,
    error: str = "",
) -> None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            "SELECT operations.jobs_finish_v1(%s, %s, %s, %s, %s, %s, %s::jsonb)",
            (1, job_id, claim_token, status, rows, error, "{}"),
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


def _execute(job_key: str, progress: V1JobProgress) -> int | None:
    """Run a catalog job synchronously in the bounded queue worker.

    Importing main here avoids its startup import cycle. The direct lower-level
    functions intentionally raise, allowing the durable record to show failure.
    """
    from ingest import main
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
    from ingest.software_findings import incremental_pending_count
    from ingest import source_actions
    from ingest import source_run_queue
    from ingest import platform_findings, runlog

    jobs = {
        "patch-classify": ("Classifying patch state", lambda: main.patch_classify(tenant_id=1)),
        "platform-evaluate": (
            "Evaluating platform conditions",
            lambda: main.platform_evaluate(tenant_id=1),
        ),
        "parity-check": ("Checking operational parity", lambda: main.parity_check_run(tenant_id=1)),
        "software-classify-only": (
            "Classifying changed software",
            lambda: main.software_classify(tenant_id=1, incremental=True),
        ),
        "software-classify-full": (
            "Rebuilding all software findings",
            lambda: main.software_classify(tenant_id=1, incremental=False),
        ),
        "resolver": ("Resolving computer identity", lambda: main.run_identity_resolver_once()),
        "patches": ("Collecting Ninja information", lambda: main.run_patching_once()),
        "agent-observations": (
            "Collecting agent observations",
            lambda: main.run_agent_observations_once(),
        ),
        "documentation-observations": (
            "Collecting documentation observations",
            lambda: main.run_documentation_observations_once(),
        ),
        "agent-compliance": (
            "Refreshing agent compliance",
            lambda: main.run_agent_compliance_once(),
        ),
        "agent-compliance-evaluate": (
            "Reviewing agent compliance",
            lambda: main.run_agent_compliance_evaluate_once(),
        ),
        "agent-compliance-review-digest": (
            "Preparing agent compliance review digest",
            lambda: main.run_review_digest_once(),
        ),
        "retention-history": (
            "Cleaning closed history",
            lambda: main.run_observation_history_prune_once(),
        ),
        "software-enqueue-orgs": (
            "Scheduling software inventory",
            lambda: main.enqueue_all_orgs_once(),
        ),
        "software-queue-drain": (
            "Collecting software inventory",
            lambda: main.run_software_queue_once(progress.job_id),
        ),
        "source-actions": (
            "Processing approved source actions",
            lambda: sum(source_actions.process_pending(job_run_id=progress.job_id).values()),
        ),
        "source-demand": (
            "Processing queued source demand",
            lambda: source_run_queue.process_next(progress.job_id),
        ),
        "source-demand-recovery": (
            "Recovering expired source demand",
            source_run_queue.recover_stale,
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
        "intel-kev": ("Refreshing exploited-vulnerability intelligence", cisa_kev.run_once),
        "intel-epss": ("Refreshing exploit-likelihood scores", epss.run_once),
        "intel-matcher": ("Matching software to vulnerabilities", matcher.run_once),
        "intel-winget": ("Refreshing Windows package intelligence", winget.run_once),
        "intel-chocolatey": ("Refreshing Chocolatey intelligence", chocolatey.run_once),
        "intel-capability": ("Projecting software capabilities", capability_match.run_once),
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
        return _software_classify_with_intel(progress, matcher, winget, chocolatey, main)
    if job_key == "software-classify-only":
        pending = incremental_pending_count(tenant_id=1)
        detail = (
            "Evaluating changed software installations only."
            if pending is None
            else f"Evaluating {pending} changed software installation(s)."
        )
        progress.update("Classifying changed software", detail)
        return int(jobs[job_key][1]())
    if job_key not in jobs:
        raise ValueError(f"Unknown registered job: {job_key}")
    stage, job = jobs[job_key]
    progress.update(stage, "This job does not publish a measurable work total.")
    result = job()
    if job_key == "patches" and result is False:
        raise RuntimeError("Patch collection could not acquire its database execution lock")
    return int(result) if isinstance(result, int) else None


def _software_classify_with_intel(
    progress: V1JobProgress, matcher: Any, winget: Any, chocolatey: Any, main: Any
) -> int | None:
    """Run the advertised auto-intel sequence with each real stage recorded."""
    if main.settings.INTEL_ENABLED:
        for stage, job in (
            ("Matching software to vulnerabilities", matcher.run_once),
            ("Refreshing Windows package intelligence", winget.run_once),
            ("Refreshing Chocolatey intelligence", chocolatey.run_once),
        ):
            progress.update(stage, "This stage does not publish a measurable work total.")
            job()
    progress.update(
        "Classifying installed software", "This stage does not publish a measurable work total."
    )
    result = main.software_classify(tenant_id=1, incremental=False)
    progress.update(
        "Refreshing software views", "Making the completed classification available to operators."
    )
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW operations.v_software_safety")
    return int(result) if isinstance(result, int) else None
