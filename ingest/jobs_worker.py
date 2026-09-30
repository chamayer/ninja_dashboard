"""Dedicated process for converted v1 Jobs execution.

The worker deliberately has no HTTP server, scheduler, migrations, or dashboard
bootstrap responsibilities. It uses the restricted Jobs APIs exclusively for
claim, progress, finish, and claim release through the finish transition.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ingest import db, operator_job_queue
from ingest.config import settings
from ingest.logging_utils import install_log_safety

log = logging.getLogger(__name__)

_READY_PATH = Path("/tmp/ninja-jobs-worker-ready")
_POLL_SECONDS = 1.0
_stopping = False


@dataclass
class _Child:
    run_id: uuid.UUID
    claim_token: uuid.UUID
    job_key: str
    process: subprocess.Popen[str]
    progress: operator_job_queue.V1JobProgress


def _request_stop(_signum: int, _frame: object) -> None:
    global _stopping
    _stopping = True


def healthcheck() -> int:
    """Return success only after the running worker completed initialization."""
    return 0 if _READY_PATH.is_file() else 1


def _start_child(lane: str, incarnation: uuid.UUID) -> _Child | None:
    row = operator_job_queue._claim_next_v1(lane, incarnation)
    if row is None:
        return None
    process = subprocess.Popen(
        [sys.executable, "-m", "ingest.jobs_child", row["job_key"], str(row["id"]), str(row["claim_token"])],
        stdout=subprocess.PIPE, text=True,
    )
    return _Child(row["id"], row["claim_token"], row["job_key"], process,
                  operator_job_queue.V1JobProgress(row["id"], row["claim_token"]))


def _finish_child(child: _Child) -> None:
    output, _ = child.process.communicate()
    try:
        result = json.loads(output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        result = {"ok": False, "error": "Jobs child exited without a valid result."}
    if result.get("cancelled"):
        operator_job_queue._finish_cancelled_v1(child.run_id, child.claim_token)
    elif result.get("ok"):
        operator_job_queue._finish_v1(child.run_id, child.claim_token, "completed", rows=result.get("rows"))
    else:
        operator_job_queue._finish_v1(child.run_id, child.claim_token, "failed", error=str(result.get("error", "Jobs child failed."))[:2000])


def run() -> int:
    """Supervise one isolated child per lane without blocking other lanes."""
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
    children: dict[str, _Child] = {}
    _READY_PATH.touch()
    log.info("Jobs worker ready: incarnation=%s", worker_incarnation)
    try:
        while not _stopping:
            for lane in operator_job_queue.WORKER_LANES:
                child = children.get(lane)
                if child is not None:
                    try:
                        child.progress.heartbeat()
                    except Exception:
                        # The control plane reaper will contain an expired
                        # claim; do not abandon every other lane on one
                        # transient heartbeat failure.
                        log.exception("Jobs child heartbeat failed: run=%s", child.run_id)
                    if child.process.poll() is not None:
                        try:
                            _finish_child(child)
                            del children[lane]
                        except Exception:
                            log.exception("Jobs child finish transition failed: run=%s", child.run_id)
                    continue
                child = _start_child(lane, worker_incarnation)
                if child is not None:
                    children[lane] = child
                if _stopping:
                    break
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
