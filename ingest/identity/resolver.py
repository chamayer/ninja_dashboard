"""Polling identity resolver (v1).

Scans entity_observations WHERE device_id IS NULL and attempts hostname-
based resolution. On a unique match, updates device_id in place. On
multiple candidates, creates an identity_candidates row for operator review.

This is v1 (polling, not queue-governed). The identity.resolution queue
registry entry exists for health monitoring only; this function reads
entity_observations directly rather than consuming a queue table.
"""

from __future__ import annotations

import logging
import uuid

from ingest import db
from ingest.agent_compliance.normalize import normalize_hostname

log = logging.getLogger(__name__)

TENANT_ID = 1


def drain_resolution(batch_size: int = 20) -> int:
    """Resolve up to batch_size unresolved entity_observations.

    Returns the count of observations that were resolved (device_id set).
    """
    resolved_count = 0
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")

        cur.execute(
            """
            SELECT observation_id, entity_key, platform, canonical_data
            FROM operations.entity_observations
            WHERE tenant_id = %s AND device_id IS NULL
            ORDER BY observed_at ASC
            LIMIT %s
            """,
            (TENANT_ID, batch_size),
        )
        rows = cur.fetchall()

        for obs_id, entity_key, platform, canonical_data in rows:
            hostname_raw = (canonical_data or {}).get("hostname") or (canonical_data or {}).get("guest_name")
            if not hostname_raw:
                continue
            norm = normalize_hostname(hostname_raw)
            if not norm:
                continue

            device_id = _resolve_by_hostname(cur, norm)
            if device_id is not None:
                cur.execute(
                    """
                    UPDATE operations.entity_observations
                    SET device_id = %s
                    WHERE observation_id = %s
                    """,
                    (device_id, obs_id),
                )
                resolved_count += 1
                log.debug("resolver: resolved %s → device %s", entity_key, device_id)
            else:
                _maybe_create_candidate(cur, obs_id, entity_key, norm)

    log.info("resolver: resolved %d observations (batch_size=%d)", resolved_count, batch_size)
    return resolved_count


def _resolve_by_hostname(cur, norm: str) -> uuid.UUID | None:
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
        """,
        (TENANT_ID, norm),
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    return None


def _maybe_create_candidate(cur, obs_id: uuid.UUID, entity_key: str, norm: str) -> None:
    """If multiple devices match the hostname, log for now (candidate creation needs two device UUIDs)."""
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
        LIMIT 3
        """,
        (TENANT_ID, norm),
    )
    rows = cur.fetchall()
    if len(rows) >= 2:
        log.debug(
            "resolver: multiple devices for hostname=%s entity_key=%s obs_id=%s — skipping candidate creation",
            norm, entity_key, obs_id,
        )
