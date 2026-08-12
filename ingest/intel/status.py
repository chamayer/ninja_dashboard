"""Track per-connector run status in operations.intel_ingest_status.

Every connector wraps its ``run_once`` with ``record_run`` so operators
can see when the feed last succeeded, last failed, and what happened.
Matches the "nothing hidden" rule — no silent drops.

Duration is recorded here rather than per connector (migration 090). The
table recorded outcome but not cost, so a connector could get an order of
magnitude more expensive without anything showing it — which is what happened
to the matcher after the CPE dictionary grew 164,860 → 1,799,966 while its
docstring still called a full rebuild "cheap". Instrumenting the shared
wrapper covers all eleven connectors and any future one for free.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic
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
    # Monotonic, so a clock adjustment mid-run cannot produce a negative or
    # wildly wrong duration. `now` stays wall-clock because it is a timestamp
    # an operator reads, not an interval.
    started = monotonic()
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
        # Recorded for failures too: a connector that fails slowly is a
        # different problem from one that fails fast, and the old table could
        # not tell them apart.
        duration = monotonic() - started
        log.info(
            "Intel connector %s finished: status=%s duration=%.1fs rows=%s",
            connector, status, duration, state.get("rows_touched", 0),
        )
        try:
            with db.transaction() as cur:
                cur.execute(
                    """
                    INSERT INTO operations.intel_ingest_status (
                        connector, last_run_at, last_success_at,
                        last_status, last_error, rows_touched, notes,
                        last_duration_seconds
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                        notes            = EXCLUDED.notes,
                        last_duration_seconds = EXCLUDED.last_duration_seconds
                    """,
                    (
                        connector,
                        now,
                        now if status == "ok" else None,
                        status,
                        error,
                        int(state.get("rows_touched", 0)),
                        str(state.get("notes", ""))[:1000],
                        duration,
                    ),
                )
        except Exception:
            log.exception("Failed to record intel_ingest_status for %s", connector)
