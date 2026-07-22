"""Fast-path identity resolution.

Tries to match a source observation to an operations.devices row using
increasingly loose signals. Called inline during ingest — must be fast.
Returns None on miss; the polling resolver picks up unresolved observations.

When a match is made via serial or hostname (steps 2 or 3), the function
**also upserts** the corresponding `device_link` so operator-facing UI
and later resolver passes see a consistent identity picture. Previously
only the observation's `device_id` was set, which left presence tables
populated but the `device_links` row missing — a real bug affecting
21 SentinelOne devices in prod at time of fix (2026-07-21).
"""

from __future__ import annotations

import logging
import uuid

from ingest.normalize import is_usable_serial

log = logging.getLogger(__name__)

# Entity types whose (source, external_id) is a per-device identity
# signal — a device_link is meaningful. Software observations (and
# other per-installation records) share entity_key across devices;
# they must never produce a device_link even when fast_path resolves
# their device_id via serial or hostname.
_IDENTITY_ENTITY_TYPES = {
    "vm.host", "vm.guest", "network.device", "monitor.target",
}


def _is_identity_signal(entity_type: str) -> bool:
    return (
        entity_type.startswith("agent.")
        or entity_type in _IDENTITY_ENTITY_TYPES
    )


def _upsert_link_for_fast_match(
    cur,
    tenant_id: int,
    source_name: str,
    external_id: str,
    device_id: uuid.UUID,
    hostname: str | None,
    match_method: str,
    match_confidence: float,
) -> None:
    """Create the durable device_link row for a fast-path match.

    Idempotent via ON CONFLICT — repeat calls just refresh
    last_seen_at. Same-source-external_id already present with a
    different device_id is a same-stream duplicate (handled by the
    ON CONFLICT DO UPDATE — the incoming match wins, matching the
    behavior of the polling resolver's `_attach_observation`).
    """
    cur.execute(
        """
        INSERT INTO operations.device_links
            (id, version, tenant_id, device_id, source_id,
             external_id, external_name, first_seen_at, last_seen_at,
             match_method, match_confidence)
        SELECT gen_random_uuid(), 1, %s, %s, s.id, %s, %s, NOW(), NOW(),
               %s, %s
        FROM operations.sources s WHERE s.name = %s
        ON CONFLICT (tenant_id, source_id, external_id)
        DO UPDATE SET
            device_id     = EXCLUDED.device_id,
            last_seen_at  = NOW(),
            external_name = COALESCE(
                NULLIF(EXCLUDED.external_name, ''),
                operations.device_links.external_name
            )
        """,
        (
            tenant_id, device_id, external_id,
            hostname or external_id,
            match_method, match_confidence,
            source_name,
        ),
    )


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

    # Whether to persist a device_link on a successful step-2/3 match.
    # Only per-device-identity entity types produce meaningful links;
    # software (and any other per-installation records) share
    # entity_key across devices and must never generate a device_link.
    upsert_link = _is_identity_signal(entity_type)

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
            device_id = rows[0][0]
            if upsert_link:
                _upsert_link_for_fast_match(
                    cur, tenant_id, source_name, external_id, device_id,
                    hostname, "serial", 0.980,
                )
            return device_id

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
                  SELECT 1 FROM operations.entity_observation_current eo
                  WHERE eo.tenant_id = d.tenant_id AND eo.device_id = d.id
                    AND eo.active = TRUE
                    AND eo.platform = %s AND eo.entity_type = %s
                    AND eo.entity_key <> %s
              )
            """,
            (tenant_id, hostname, client_id, client_id,
             source_name, entity_type, external_id),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            device_id = rows[0][0]
            if upsert_link:
                _upsert_link_for_fast_match(
                    cur, tenant_id, source_name, external_id, device_id,
                    hostname, "hostname_strict", 0.900,
                )
            return device_id

    log.debug(
        "fast_path miss: source=%s external_id=%s hostname=%s",
        source_name, external_id, hostname,
    )
    return None
