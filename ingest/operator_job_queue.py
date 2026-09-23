"""Single-worker durable queue for operator-requested Jobs runs.

The queue is deliberately separate from source demand and external-action
queues: its entries represent registered platform work, not a source mutation.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from psycopg_pool import PoolTimeout

from ingest import db

log = logging.getLogger(__name__)

_TABLE = "operations.operator_job_runs"
_LEASE_MINUTES = 90
_HEARTBEAT_SECONDS = 30
_WORKER_CAPACITY = threading.BoundedSemaphore(2)

_JOB_LANES = {
    "patches": "collection",
    "agent-observations": "collection",
    "documentation-observations": "collection",
    "notifications-dispatch": "service",
    "notifications-digest": "service",
    "retention-history": "service",
    "software-enqueue-orgs": "service",
    "software-queue-drain": "collection",
}


def lane_for(job_key: str) -> str:
    """Return the registered worker lane for a durable Jobs definition."""
    if job_key.startswith("intel-"):
        return "intelligence"
    return _JOB_LANES.get(job_key, "evaluation")


WORKER_LANES = ("collection", "evaluation", "intelligence", "service")


class JobProgress:
    """Persist a factual current stage for one active Jobs run."""

    def __init__(self, job_id: Any) -> None:
        self.job_id = job_id

    def update(self, stage: str, detail: str = "") -> None:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""UPDATE {_TABLE}
                       SET stage = %s, stage_detail = %s, stage_updated_at = NOW(), heartbeat_at = NOW(),
                           lease_expires_at = NOW() + INTERVAL '{_LEASE_MINUTES} minutes'
                     WHERE tenant_id = 1 AND id = %s AND status = 'running'""",
                (stage, detail, self.job_id),
            )
            cur.execute(
                """INSERT INTO operations.operator_job_events
                       (tenant_id, job_id, event_type, stage, detail)
                    VALUES (1, %s, 'stage', %s, %s)""",
                (self.job_id, stage, detail),
            )

    def heartbeat(self) -> None:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""UPDATE {_TABLE}
                       SET heartbeat_at = NOW(),
                           lease_expires_at = NOW() + INTERVAL '{_LEASE_MINUTES} minutes'
                     WHERE tenant_id = 1 AND id = %s AND status = 'running'""",
                (self.job_id,),
            )


def enqueue_automatic(job_key: str) -> bool:
    """Queue scheduled work through the same durable path as Jobs.

    A null requester means the scheduler initiated it.  The active-row index
    coalesces an overdue cadence with work already queued or running, which is
    preferable to accumulating duplicate automatic runs while the worker is
    busy.
    """
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (id, tenant_id, job_key, lane, requested_by_id)
                VALUES (%s, 1, %s, %s, NULL)
                ON CONFLICT (tenant_id, job_key) WHERE status IN ('queued', 'running')
                DO NOTHING
                RETURNING id
                """,
                (uuid.uuid4(), job_key, lane_for(job_key)),
            )
            return cur.fetchone() is not None
    except PoolTimeout:
        log.warning("automatic job %s waiting for database capacity", job_key)
        return False


def process_next(lane: str = "evaluation") -> dict[str, int]:
    """Recover expired work, then execute one queued job from its lane."""
    if lane not in WORKER_LANES:
        raise ValueError(f"Unknown Jobs worker lane: {lane}")
    if not _WORKER_CAPACITY.acquire(blocking=False):
        return {"completed": 0, "failed": 0}
    try:
        return _process_next_in_lane(lane)
    finally:
        _WORKER_CAPACITY.release()


def _process_next_in_lane(lane: str) -> dict[str, int]:
    recover_stale()
    try:
        row = _claim_next(lane)
    except PoolTimeout:
        log.warning("operator jobs waiting for database capacity")
        return {"completed": 0, "failed": 0}
    if row is None:
        return {"completed": 0, "failed": 0}
    progress = JobProgress(row["id"])
    stopped = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(progress, stopped), daemon=True
    )
    heartbeat.start()
    try:
        rows = _execute(row["job_key"], progress)
    except Exception as exc:
        log.exception("operator job %s failed", row["job_key"])
        _finish(row["id"], "failed", error=str(exc)[:2000])
        return {"completed": 0, "failed": 1}
    finally:
        stopped.set()
        heartbeat.join(timeout=1)
    _finish(row["id"], "completed", rows=rows)
    return {"completed": 1, "failed": 0}


def recover_stale() -> int:
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET status = 'stalled', stage = 'Needs attention',
                       stage_detail = 'No progress update before the safety deadline.',
                       stage_updated_at = NOW(), completed_at = NOW(), lease_expires_at = NULL,
                       error = 'Run stopped responding. Review and retry when ready.'
                 WHERE tenant_id = 1 AND status = 'running'
                   AND heartbeat_at < NOW() - INTERVAL '{_LEASE_MINUTES} minutes'
                """
            )
            return cur.rowcount
    except PoolTimeout:
        # Capacity is temporarily unavailable (for example, during startup
        # bootstrap). Leave work visibly queued and try again next cadence.
        log.warning("operator jobs waiting for database capacity")
        return 0


def recover_interrupted() -> int:
    """Close runs left behind by this process being replaced or restarted."""
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""UPDATE {_TABLE}
                   SET status = 'stalled', stage = 'Interrupted by service restart',
                       stage_detail = 'The worker was replaced before this run finished.',
                       stage_updated_at = NOW(), heartbeat_at = NOW(), completed_at = NOW(),
                       lease_expires_at = NULL,
                       error = 'Interrupted by service restart. Retry when ready.'
                 WHERE tenant_id = 1 AND status = 'running'
             RETURNING id"""
        )
        interrupted_ids = [row[0] for row in cur.fetchall()]
        interrupted = len(interrupted_ids)
        if interrupted_ids:
            cur.execute(
                """INSERT INTO operations.operator_job_events
                       (tenant_id, job_id, event_type, stage, detail)
                    SELECT tenant_id, id, 'interrupted', stage, stage_detail
                      FROM operations.operator_job_runs
                     WHERE tenant_id = 1 AND id = ANY(%s)""",
                (interrupted_ids,),
            )
    if interrupted:
        log.warning("operator jobs: marked %d run(s) interrupted by service restart", interrupted)
    return interrupted


def _heartbeat_loop(progress: JobProgress, stopped: threading.Event) -> None:
    while not stopped.wait(_HEARTBEAT_SECONDS):
        try:
            progress.heartbeat()
        except Exception:
            log.exception("operator job heartbeat failed")


def _claim_next(lane: str) -> dict[str, Any] | None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            WITH candidate AS (
                SELECT id FROM {_TABLE}
                 WHERE tenant_id = 1 AND lane = %s AND status = 'queued'
                 ORDER BY priority DESC, requested_at, id
                 FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE {_TABLE} job
               SET status = 'running', stage = 'Starting', stage_detail = '',
                   stage_updated_at = NOW(), started_at = NOW(),
                   lease_expires_at = NOW() + INTERVAL '{_LEASE_MINUTES} minutes',
                   attempts = attempts + 1
              FROM candidate
             WHERE job.id = candidate.id
            RETURNING job.id, job.job_key
            """,
            (lane,),
        )
        row = cur.fetchone()
    return {"id": row[0], "job_key": row[1]} if row else None


def _finish(job_id: Any, status: str, *, rows: int | None = None, error: str = "") -> None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""UPDATE {_TABLE}
                 SET status = %s, stage = %s, stage_detail = %s,
                       stage_updated_at = NOW(), completed_at = NOW(), lease_expires_at = NULL,
                       rows_touched = %s, error = %s
                 WHERE id = %s AND status = 'running'""",
            (
                status,
                "Completed" if status == "completed" else "Failed",
                "Finished" if status == "completed" else "Review the recorded error.",
                rows,
                error,
                job_id,
            ),
        )


def _execute(job_key: str, progress: JobProgress) -> int | None:
    """Run a catalog job synchronously in the bounded queue worker.

    Importing main here avoids its startup import cycle. The direct lower-level
    functions intentionally raise, allowing the durable record to show failure.
    """
    from ingest import main
    from ingest.intel import (
        abusech,
        capability_match,
        chocolatey,
        cisa_kev,
        cpe_dict,
        category_match,
        epss,
        lolrmm,
        matcher,
        nvd,
        otx,
        winget,
    )

    jobs = {
        "patch-classify": ("Classifying patch state", lambda: main.patch_classify(tenant_id=1)),
        "platform-evaluate": ("Evaluating platform conditions", lambda: main.platform_evaluate(tenant_id=1)),
        "parity-check": ("Checking operational parity", lambda: main.parity_check_run(tenant_id=1)),
        "software-classify-only": ("Classifying installed software", lambda: main.software_classify(tenant_id=1)),
        "resolver": ("Resolving computer identity", lambda: main.run_identity_resolver_once()),
        "patches": ("Collecting Ninja information", lambda: main.run_patching_once()),
        "agent-observations": ("Collecting agent observations", lambda: main.run_agent_observations_once()),
        "documentation-observations": ("Collecting documentation observations", lambda: main.run_documentation_observations_once()),
        "agent-compliance": ("Refreshing agent compliance", lambda: main.run_agent_compliance_once()),
        "agent-compliance-evaluate": ("Reviewing agent compliance", lambda: main.run_agent_compliance_evaluate_once()),
        "retention-history": ("Cleaning closed history", lambda: main.run_observation_history_prune_once()),
        "software-enqueue-orgs": ("Scheduling software inventory", lambda: main.enqueue_all_orgs_once()),
        "software-queue-drain": ("Collecting software inventory", lambda: main.run_software_queue_once()),
        "notifications-dispatch": ("Sending notifications", lambda: main.notify_dispatch(tenant_id=1)),
        "notifications-digest": ("Preparing notification digest", lambda: main.notify_send_digest(tenant_id=1)),
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
        "intel-endoflife": ("Refreshing end-of-life intelligence", lambda: main.run_intel_endoflife_once()),
        "intel-category": ("Refreshing software categories", category_match.run_once),
    }
    if job_key == "software-classify":
        return _software_classify_with_intel(progress, matcher, winget, chocolatey, main)
    if job_key not in jobs:
        raise ValueError(f"Unknown registered job: {job_key}")
    stage, job = jobs[job_key]
    progress.update(stage, "This job does not publish a measurable work total.")
    result = job()
    return int(result) if isinstance(result, int) else None


def _software_classify_with_intel(
    progress: JobProgress, matcher: Any, winget: Any, chocolatey: Any, main: Any
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
    progress.update("Classifying installed software", "This stage does not publish a measurable work total.")
    result = main.software_classify(tenant_id=1)
    progress.update("Refreshing software views", "Making the completed classification available to operators.")
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW operations.v_software_safety")
    return int(result) if isinstance(result, int) else None
