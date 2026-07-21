"""Refresh Operations current/derived state at collection boundaries."""

from __future__ import annotations

import logging
import time

from ingest import db

log = logging.getLogger(__name__)


def refresh_after_collection(reason: str) -> None:
    """Refresh all shared Operations derived state before collection completes.

    Exceptions intentionally propagate. A caller must not report a scheduled or
    on-demand collection as complete when its dependent current state is stale.
    """
    started = time.monotonic()
    with db.transaction() as cur:
        cur.execute("SELECT operations.refresh_derived()")
    log.info(
        "Operations derived state refreshed after %s in %.2fs",
        reason,
        time.monotonic() - started,
    )
