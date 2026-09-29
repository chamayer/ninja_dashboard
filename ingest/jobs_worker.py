"""Dedicated process for converted v1 Jobs execution.

The worker deliberately has no HTTP server, scheduler, migrations, or dashboard
bootstrap responsibilities. It uses the restricted Jobs APIs exclusively for
claim, progress, finish, and claim release through the finish transition.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
import uuid
from pathlib import Path

from ingest import db, operator_job_queue
from ingest.config import settings
from ingest.logging_utils import install_log_safety

log = logging.getLogger(__name__)

_READY_PATH = Path("/tmp/ninja-jobs-worker-ready")
_POLL_SECONDS = 1.0
_stopping = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _stopping
    _stopping = True


def healthcheck() -> int:
    """Return success only after the running worker completed initialization."""
    return 0 if _READY_PATH.is_file() else 1


def run() -> int:
    """Claim at most one converted run per lane on each bounded polling pass."""
    global _stopping
    logging.basicConfig(
        level=settings.INGEST_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_log_safety()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    _READY_PATH.unlink(missing_ok=True)

    db.init(settings.postgres_dsn)
    operator_job_queue.register_definition_snapshots()
    worker_incarnation = uuid.uuid4()
    _READY_PATH.touch()
    log.info("Jobs worker ready: incarnation=%s", worker_incarnation)
    try:
        while not _stopping:
            ran_work = False
            for lane in operator_job_queue.WORKER_LANES:
                result = operator_job_queue.process_next_v1(lane, worker_incarnation)
                ran_work = ran_work or bool(result["completed"] or result["failed"])
                if _stopping:
                    break
            if not ran_work:
                time.sleep(_POLL_SECONDS)
    finally:
        _READY_PATH.unlink(missing_ok=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dedicated Jobs worker.")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(healthcheck())
    raise SystemExit(run())


if __name__ == "__main__":
    main()
