"""One isolated execution child for a fenced Jobs run."""
from __future__ import annotations
import json
import sys
import uuid
from ingest import db, operator_job_queue
from ingest.config import settings

def main() -> None:
    job_key, run_id, claim_token = sys.argv[1:4]
    db.init(settings.postgres_dsn)
    try:
        rows = operator_job_queue._execute(job_key, operator_job_queue.V1JobProgress(uuid.UUID(run_id), uuid.UUID(claim_token)))
        print(json.dumps({"ok": True, "rows": rows}))
    except operator_job_queue.JobCancellationRequested as exc:
        print(json.dumps({"ok": False, "cancelled": True, "error": str(exc)}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:2000]}))
        raise

if __name__ == "__main__":
    main()
