"""Track per-connector run status in operations.intel_ingest_status.

Every connector wraps its ``run_once`` with ``record_run`` so operators
can see when the feed last succeeded, last failed, and what happened.
Matches the "nothing hidden" rule — no silent drops.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from ingest import db

log = logging.getLogger(__name__)


@contextmanager
def record_run(connector: str) -> Iterator[dict]:
    """Context manager that upserts intel_ingest_status.

    Usage::

        with record_run("nvd") as state:
            rows = _pull_and_upsert(...)
            state["rows_touched"] = rows
            state["notes"] = f"{rows} CVEs upserted"
    """
    state: dict = {"rows_touched": 0, "notes": ""}
    now = datetime.now(timezone.utc)
    status = "ok"
    error = ""
    try:
        yield state
    except Exception as exc:
        status = "failed"
        error = str(exc)[:2000]
        log.exception("Intel connector %s failed", connector)
        raise
    finally:
        try:
            with db.transaction() as cur:
                cur.execute(
                    """
                    INSERT INTO operations.intel_ingest_status (
                        connector, last_run_at, last_success_at,
                        last_status, last_error, rows_touched, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (connector) DO UPDATE SET
                        last_run_at      = EXCLUDED.last_run_at,
                        last_success_at  = CASE
                            WHEN EXCLUDED.last_status = 'ok'
                                THEN EXCLUDED.last_success_at
                            ELSE operations.intel_ingest_status.last_success_at
                        END,
                        last_status      = EXCLUDED.last_status,
                        last_error       = EXCLUDED.last_error,
                        rows_touched     = EXCLUDED.rows_touched,
                        notes            = EXCLUDED.notes
                    """,
                    (
                        connector,
                        now,
                        now if status == "ok" else None,
                        status,
                        error,
                        int(state.get("rows_touched", 0)),
                        str(state.get("notes", ""))[:1000],
                    ),
                )
        except Exception:
            log.exception("Failed to record intel_ingest_status for %s", connector)
