"""Register the shared Jobs catalog in an initialized Operations database."""

from __future__ import annotations

import logging

from ingest import db, operator_job_queue
from ingest.config import settings


def main() -> None:
    logging.basicConfig(level=settings.INGEST_LOG_LEVEL)
    db.init(settings.postgres_dsn)
    operator_job_queue.register_definition_snapshots()


if __name__ == "__main__":
    main()
