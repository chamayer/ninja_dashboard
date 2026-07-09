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

from psycopg.types.json import Json

from ingest import db
from ingest.normalize import normalize_hostname

log = logging.getLogger(__name__)

TENANT_ID = 1


def drain_resolution(batch_size: int = 200) -> int:
    """Resolve up to batch_size unresolved entity_observations.

    Returns the count of observations that were resolved (device_id set).
    Refreshes agent_presence_current if any observations were resolved.
    """
    resolved_count = 0
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")

        cur.execute(
            """
            SELECT observation_id, entity_key, platform, canonical_data
            FROM operations.entity_observations
            WHERE tenant_id = %s AND device_id IS NULL
              AND entity_type LIKE 'agent.%%'
            ORDER BY observed_at DESC
            LIMIT %s
            """,
            (TENANT_ID, batch_size),
        )
        rows = cur.fetchall()

        for obs_id, entity_key, platform, canonical_data in rows:
            cd = canonical_data or {}

            # Try serial number first (high confidence, unique hardware ID)
            serial = cd.get("serial_number")
            if serial:
                device_id = _resolve_by_serial(cur, serial)
                if device_id is not None:
                    cur.execute(
                        "UPDATE operations.entity_observations SET device_id = %s WHERE observation_id = %s",
                        (device_id, obs_id),
                    )
                    resolved_count += 1
                    log.debug("resolver: serial match %s → device %s", entity_key, device_id)
                    continue

            # Fall back to normalised hostname
            hostname_raw = cd.get("hostname") or cd.get("guest_name")
            if not hostname_raw:
                continue
            norm = normalize_hostname(hostname_raw)
            if not norm:
                continue

            device_id = _resolve_by_hostname(cur, norm)
            if device_id is not None:
                cur.execute(
                    "UPDATE operations.entity_observations SET device_id = %s WHERE observation_id = %s",
                    (device_id, obs_id),
                )
                resolved_count += 1
                log.debug("resolver: hostname match %s → device %s", entity_key, device_id)
            else:
                _maybe_create_candidate(cur, obs_id, entity_key, norm)

    log.info("resolver: resolved %d / %d observations", resolved_count, len(rows) if rows else 0)

    if resolved_count:
        try:
            with db.transaction() as cur:
                cur.execute("SELECT operations.refresh_agent_presence_current()")
            log.info("resolver: refreshed agent_presence_current after %d resolutions", resolved_count)
        except Exception:
            log.exception("resolver: agent_presence_current refresh failed — continuing")

    return resolved_count


def _resolve_by_serial(cur, serial: str) -> uuid.UUID | None:
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_serial = %s AND deleted_at IS NULL
        """,
        (TENANT_ID, serial),
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    return None


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
    """If multiple devices match the hostname, record an identity_candidate for review."""
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
        LIMIT 3
        """,
        (TENANT_ID, norm),
    )
    rows = cur.fetchall()
    if len(rows) < 2:
        return
    device_id_a = rows[0][0]
    device_id_b = rows[1][0]
    cur.execute(
        """
        INSERT INTO operations.identity_candidates
            (tenant_id, observation_id, device_id_a, device_id_b, confidence, signals, status)
        VALUES (%s, %s, %s, %s, 'low', %s, 'pending')
        ON CONFLICT (observation_id) DO NOTHING
        """,
        (
            TENANT_ID, obs_id, device_id_a, device_id_b,
            Json({"hostname": norm, "candidate_count": len(rows)}),
        ),
    )
    if cur.rowcount:
        log.info(
            "resolver: identity_candidate created obs=%s hostname=%s device_count=%d",
            obs_id, norm, len(rows),
        )
