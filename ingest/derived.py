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
        cur.execute(
            "SELECT to_regprocedure("
            "'operations.sync_entity_source_links_from_observations()'"
            ") IS NOT NULL"
        )
        if cur.fetchone()[0]:
            cur.execute("SELECT operations.sync_entity_source_links_from_observations()")
            entity_link_sync = cur.fetchone()[0]
        else:
            entity_link_sync = {"status": "migration_pending"}
        cur.execute("SELECT operations.refresh_derived()")
    log.info(
        "Operations entity links synced (%s) and derived state refreshed after %s in %.2fs",
        entity_link_sync,
        reason,
        time.monotonic() - started,
    )
