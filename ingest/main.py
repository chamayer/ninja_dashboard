"""Ingest entry point.

Boot sequence:
  1. Load settings, configure logging.
  2. Initialise DB pool.
  3. Apply pending migrations.
  4. Start APScheduler (interval = INGEST_SCHEDULE_HOURS).
  5. Start a tiny HTTP server for /healthz and /run (manual trigger).
  6. Decide whether to run immediately based on run_log:
       - If the last successful run was more than INGEST_SCHEDULE_HOURS
         ago, treat as a missed schedule and run once now (catch-up).
       - Otherwise, do NOT run on startup. Wait for the next scheduled
         tick. This avoids hammering the Ninja API on container
         restarts / redeploys.
       - On a fresh install (empty run_log) we also wait for the first
         scheduled tick. Operator can hit POST /run for immediate data.
"""

import logging
from datetime import datetime, timedelta, timezone

from ingest.config import settings


def run_once() -> None:
    """Execute one full ingest cycle: core lookups → patches → ...
    Each module writes its own run_log row."""
    raise NotImplementedError


def last_successful_run_at() -> datetime | None:
    """Most recent `finished_at` from ninja_core.run_log where
    status='ok' and domain='core' (the orchestrator row). None if no
    successful run has ever completed."""
    raise NotImplementedError


def should_catch_up(now: datetime | None = None) -> bool:
    """True if a scheduled run was missed while we were down."""
    now = now or datetime.now(timezone.utc)
    last = last_successful_run_at()
    if last is None:
        return False  # fresh install — wait for next scheduled tick
    return (now - last) > timedelta(hours=settings.INGEST_SCHEDULE_HOURS)


def main() -> None:
    logging.basicConfig(
        level=settings.INGEST_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    raise NotImplementedError


if __name__ == "__main__":
    main()
