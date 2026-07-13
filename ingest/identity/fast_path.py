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
    entity_type: str,
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

    A usable serial match (step 2) is proof of the same machine, so it may
    attach even alongside another record of the same (platform, entity_type)
    stream — a duplicate agent on one box gets its own link and a
    duplicate_platform_record finding. Hostname (step 3) stays cross-stream
    only: same name with no hardware proof could be two real machines, so a
    device already carrying a different record of that stream is never a
    hostname match.
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
            SELECT d.id FROM operations.devices d
            WHERE d.tenant_id = %s AND d.canonical_serial = %s AND d.deleted_at IS NULL
              AND (%s::uuid IS NULL OR d.client_id = %s)
            """,
            (tenant_id, serial, client_id, client_id),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]

    # Step 3 — hostname match (only when unique and the device carries no
    # other record of this same stream — same-stream dups never merge)
    if hostname:
        cur.execute(
            """
            SELECT d.id
            FROM operations.devices d
            WHERE d.tenant_id = %s AND d.canonical_hostname = %s AND d.deleted_at IS NULL
              AND (%s::uuid IS NULL OR d.client_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM operations.entity_observations eo
                  WHERE eo.tenant_id = d.tenant_id AND eo.device_id = d.id
                    AND eo.platform = %s AND eo.entity_type = %s
                    AND eo.entity_key <> %s
              )
            """,
            (tenant_id, hostname, client_id, client_id,
             source_name, entity_type, external_id),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]

    log.debug(
        "fast_path miss: source=%s external_id=%s hostname=%s",
        source_name, external_id, hostname,
    )
    return None
