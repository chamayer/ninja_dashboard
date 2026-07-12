"""Fast-path identity resolution.

Tries to match a source observation to an operations.devices row using
increasingly loose signals. Called inline during ingest — must be fast.
Returns None on miss; the polling resolver picks up unresolved observations.
"""

from __future__ import annotations

import logging
import uuid

from ingest.normalize import is_usable_serial

log = logging.getLogger(__name__)


def resolve_device_fast(
    cur,
    tenant_id: int,
    source_name: str,
    external_id: str,
    serial: str | None = None,
    hostname: str | None = None,
    client_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Return the operations.devices UUID for a source observation, or None.

    The caller must have already issued SET LOCAL operations.tenant_id before
    calling this function (required for RLS on device_links and devices).

    Resolution order:
      1. Exact source + external_id match on device_links (certain).
      2. Unique serial match on devices within client scope (high confidence).
      3. Unique hostname match on devices within client scope (medium-high confidence).
    """
    # Step 1 — exact source link
    cur.execute(
        """
        SELECT dl.device_id
        FROM operations.device_links dl
        JOIN operations.sources s ON s.id = dl.source_id
        WHERE dl.tenant_id = %s AND s.name = %s AND dl.external_id = %s
        LIMIT 1
        """,
        (tenant_id, source_name, external_id),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    if client_id is None:
        log.debug(
            "fast_path clientless miss: source=%s external_id=%s hostname=%s",
            source_name, external_id, hostname,
        )
        return None

    # Step 2 — serial match (only when unique; BIOS placeholder serials
    # like 'None' / 'Default string' are shared junk, never a match)
    if is_usable_serial(serial):
        cur.execute(
            """
            SELECT id FROM operations.devices
            WHERE tenant_id = %s AND canonical_serial = %s AND deleted_at IS NULL
              AND (%s::uuid IS NULL OR client_id = %s)
            """,
            (tenant_id, serial, client_id, client_id),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]

    # Step 3 — hostname match (only when unique and no existing link for this source)
    if hostname:
        cur.execute(
            """
            SELECT d.id
            FROM operations.devices d
            WHERE d.tenant_id = %s AND d.canonical_hostname = %s AND d.deleted_at IS NULL
              AND (%s::uuid IS NULL OR d.client_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM operations.device_links dl2
                  JOIN operations.sources s2 ON s2.id = dl2.source_id
                  WHERE dl2.device_id = d.id AND s2.name = %s AND dl2.external_id = %s
              )
            """,
            (tenant_id, hostname, client_id, client_id, source_name, external_id),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]

    log.debug(
        "fast_path miss: source=%s external_id=%s hostname=%s",
        source_name, external_id, hostname,
    )
    return None
