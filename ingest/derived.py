"""Refresh Operations current/derived state at collection boundaries."""

from __future__ import annotations

import logging
import time

from ingest import attribute_claims, db, effective_attributes

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
    try:
        claim_sync = attribute_claims.project_all()
    except Exception:
        # E2 is an additive shadow path. Its failure is visible but cannot
        # block the still-authoritative typed consumers before E3 promotion.
        claim_sync = {"status": "failed"}
        log.exception("Operations attribute claim projection failed — continuing")
    try:
        effective_sync = effective_attributes.project_all()
    except Exception:
        # E3 remains a shadow projection until typed consumers pass E5 parity.
        effective_sync = {"status": "failed"}
        log.exception("Operations effective attribute projection failed — continuing")
    with db.transaction() as cur:
        cur.execute("SELECT operations.refresh_derived()")
    log.info(
        "Operations entity links synced (%s), attribute claims synced (%s), "
        "effective attributes synced (%s), and derived state refreshed after "
        "%s in %.2fs",
        entity_link_sync,
        claim_sync,
        effective_sync,
        reason,
        time.monotonic() - started,
    )
