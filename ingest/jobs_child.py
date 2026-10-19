"""One isolated execution child for a fenced Jobs run.

stdout carries exactly one JSON result line for the supervisor
(``ingest/jobs_worker.py``); logging goes to stderr, redacted, so job progress
is visible in the worker's container log. A failure is logged sanitized and
reported in the result; the child exits nonzero without a raw traceback.
"""

from __future__ import annotations
import json
import logging
import sys
import uuid
from ingest import db, operator_job_queue
from ingest.config import settings
from ingest.logging_utils import LOG_FORMAT, install_log_safety, redact

log = logging.getLogger("ingest.jobs_child")


def _configure_logging() -> None:
    # force: the child owns its logging even if an import configured some.
    logging.basicConfig(
        level=settings.INGEST_LOG_LEVEL,
        format=LOG_FORMAT,
        stream=sys.stderr,
        force=True,
    )
    install_log_safety()


def main() -> int:
    job_key, run_id, claim_token = sys.argv[1:4]
    _configure_logging()
    try:
        db.init(settings.postgres_dsn)
        result = operator_job_queue._execute(
            job_key,
            operator_job_queue.V1JobProgress(uuid.UUID(run_id), uuid.UUID(claim_token)),
        )
        if isinstance(result, operator_job_queue.JobExecutionResult):
            rows, signals, result_detail = result.rows, result.signals, result.result
        else:
            rows, signals, result_detail = result, (), None
        print(
            json.dumps(
                {
                    "ok": True,
                    "rows": rows,
                    "signals": signals,
                    "result": result_detail or {},
                }
            )
        )
        return 0
    except operator_job_queue.JobCancellationRequested as exc:
        print(json.dumps({"ok": False, "cancelled": True, "error": redact(str(exc))}))
        return 0
    except Exception as exc:
        log.exception("Job %s failed: run=%s", job_key, run_id)
        print(json.dumps({"ok": False, "error": redact(str(exc))[:2000]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
