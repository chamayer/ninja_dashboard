"""Admit one approved Software publication through existing Jobs; no direct build."""

import hashlib
import json
import logging
import signal
import sys
from pathlib import Path


def main():
    expected = "b307c8a81b8546bb8764a9794ceac8750798a991955e7a5a224ac70338bc8804"
    source = Path("/app/ingest/operator_job_queue.py")
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Publisher source gate failed")
    job_key = sys.argv[1] if len(sys.argv) == 2 else "software-overview"
    if job_key not in ("software-overview", "software-classify-only"):
        raise ValueError("Unapproved Job key")
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    from ingest import db, operator_job_queue
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=1)
    try:
        with db.transaction() as cursor:
            cursor.execute("SET statement_timeout = '10s'")
            cursor.execute("SET lock_timeout = '2s'")
        run_id = operator_job_queue.request_system_job(
            job_key, "plan056-approved-activation"
        )
        print(json.dumps({"job_key": job_key, "run_id": str(run_id)}))
    finally:
        db.pool.close()


if __name__ == "__main__":
    signal.alarm(25)
    try:
        main()
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}))
        raise SystemExit(1) from None
