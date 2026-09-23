"""Single-worker durable queue for operator-requested Jobs runs.

The queue is deliberately separate from source demand and external-action
queues: its entries represent registered platform work, not a source mutation.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from psycopg_pool import PoolTimeout

from ingest import db

log = logging.getLogger(__name__)

_TABLE = "operations.operator_job_runs"
_LEASE_MINUTES = 90


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
                INSERT INTO {_TABLE} (id, tenant_id, job_key, requested_by_id)
                VALUES (%s, 1, %s, NULL)
                ON CONFLICT (tenant_id, job_key) WHERE status IN ('queued', 'running')
                DO NOTHING
                RETURNING id
                """,
                (uuid.uuid4(), job_key),
            )
            return cur.fetchone() is not None
    except PoolTimeout:
        log.warning("automatic job %s waiting for database capacity", job_key)
        return False


def process_next() -> dict[str, int]:
    """Recover expired work, then execute at most one requested job."""
    recover_stale()
    try:
        row = _claim_next()
    except PoolTimeout:
        log.warning("operator jobs waiting for database capacity")
        return {"completed": 0, "failed": 0}
    if row is None:
        return {"completed": 0, "failed": 0}
    try:
        rows = _execute(row["job_key"])
    except Exception as exc:
        log.exception("operator job %s failed", row["job_key"])
        _finish(row["id"], "failed", error=str(exc)[:2000])
        return {"completed": 0, "failed": 1}
    _finish(row["id"], "completed", rows=rows)
    return {"completed": 1, "failed": 0}


def recover_stale() -> int:
    try:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                f"""
                UPDATE {_TABLE}
                   SET status = 'stalled', completed_at = NOW(), lease_expires_at = NULL,
                       error = 'Run stopped responding. Review and retry when ready.'
                 WHERE tenant_id = 1 AND status = 'running'
                   AND lease_expires_at < NOW()
                """
            )
            return cur.rowcount
    except PoolTimeout:
        # Capacity is temporarily unavailable (for example, during startup
        # bootstrap). Leave work visibly queued and try again next cadence.
        log.warning("operator jobs waiting for database capacity")
        return 0


def _claim_next() -> dict[str, Any] | None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""
            WITH candidate AS (
                SELECT id FROM {_TABLE}
                 WHERE tenant_id = 1 AND status = 'queued'
                 ORDER BY requested_at, id
                 FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE {_TABLE} job
               SET status = 'running', started_at = NOW(),
                   lease_expires_at = NOW() + INTERVAL '{_LEASE_MINUTES} minutes',
                   attempts = attempts + 1
              FROM candidate
             WHERE job.id = candidate.id
            RETURNING job.id, job.job_key
            """
        )
        row = cur.fetchone()
    return {"id": row[0], "job_key": row[1]} if row else None


def _finish(job_id: Any, status: str, *, rows: int | None = None, error: str = "") -> None:
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            f"""UPDATE {_TABLE}
                 SET status = %s, completed_at = NOW(), lease_expires_at = NULL,
                       rows_touched = %s, error = %s
                 WHERE id = %s AND status = 'running'""",
            (status, rows, error, job_id),
        )


def _execute(job_key: str) -> int | None:
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
        "patch-classify": lambda: main.patch_classify(tenant_id=1),
        "platform-evaluate": lambda: main.platform_evaluate(tenant_id=1),
        "parity-check": lambda: main.parity_check_run(tenant_id=1),
        "software-classify": lambda: main.software_classify(tenant_id=1),
        "software-classify-only": lambda: main.software_classify(tenant_id=1),
        "resolver": lambda: main.run_identity_resolver_once(),
        "patches": lambda: main.run_patching_once(),
        "agent-observations": lambda: main.run_agent_observations_once(),
        "documentation-observations": lambda: main.run_documentation_observations_once(),
        "agent-compliance": lambda: main.run_agent_compliance_once(),
        "agent-compliance-evaluate": lambda: main.run_agent_compliance_evaluate_once(),
        "retention-history": lambda: main.run_observation_history_prune_once(),
        "software-enqueue-orgs": lambda: main.enqueue_all_orgs_once(),
        "software-queue-drain": lambda: main.run_software_queue_once(),
        "notifications-dispatch": lambda: main.notify_dispatch(tenant_id=1),
        "notifications-digest": lambda: main.notify_send_digest(tenant_id=1),
        "intel-nvd": nvd.run_once,
        "intel-cpe-dict": cpe_dict.run_once,
        "intel-kev": cisa_kev.run_once,
        "intel-epss": epss.run_once,
        "intel-matcher": matcher.run_once,
        "intel-winget": winget.run_once,
        "intel-chocolatey": chocolatey.run_once,
        "intel-capability": capability_match.run_once,
        "intel-lolrmm": lolrmm.run_once,
        "intel-otx": otx.run_once,
        "intel-abusech": abusech.run_once,
        "intel-endoflife": lambda: main.run_intel_endoflife_once(),
        "intel-category": category_match.run_once,
    }
    if job_key not in jobs:
        raise ValueError(f"Unknown registered job: {job_key}")
    result = jobs[job_key]()
    return int(result) if isinstance(result, int) else None
