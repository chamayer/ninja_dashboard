"""Fast-path identity resolution.

Tries to match a source observation to an operations.devices row using
increasingly loose signals. Called inline during ingest — must be fast.
Returns None on miss; the polling resolver picks up unresolved observations.

Attachment is recorded on the observation, not on a link table. The caller
persists the returned `device_id` onto `entity_observation_current`, and
`operations.sync_entity_source_links_from_observations()` derives
`entity_source_links` from that evidence later in the cycle. Step 1 below
therefore resolves against the observation as well, so a match made earlier in
the *same* transaction is visible immediately.

This function used to upsert `operations.device_links` directly on a step-2 or
step-3 match. That write is gone with the rest of the competing attachment
authority (migration 0121), which retired the table in favour of
`operations.v_device_source_link` over `entity_source_links`.
"""

from __future__ import annotations

import logging
import uuid

from ingest.normalize import is_usable_serial

log = logging.getLogger(__name__)

# `_is_identity_signal` lived here to decide whether a step-2/3 match should
# also write a device_link. With that write retired there is no second
# decision to make: the sole caller in `source_observations` already gates
# entry to this function on `identity_entity_types`, so the local copy is gone
# rather than left as a third definition of the same rule.


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
    calling this function (required for RLS on the observation and device
    tables).

    Resolution order:
      1. Exact source + external_id match on an existing observation (certain).
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
    # Step 1 — exact source identity already attached to a device.
    #
    # This reads the observation rather than a link table on purpose. The
    # caller writes the resolved device_id back onto
    # `entity_observation_current` in this same transaction, and
    # `entity_source_links` is only derived from those observations later in
    # the cycle by sync_entity_source_links_from_observations(). Resolving
    # against the derived table would therefore miss anything attached earlier
    # in the current run and re-resolve it from scratch.
    #
    # `active` is deliberately not filtered: a device that stopped reporting
    # and came back must resolve to the same device rather than mint a new one.
    #
    # `entity_type` is filtered, which the retired table could not do. Its
    # unique key was (tenant, source, external_id) with no entity_type, so one
    # source's `agent.rmm` key and its `vm.guest` key would have collided onto
    # a single row had they ever coincided. Observations are keyed per type,
    # so this is both narrower and correct.
    cur.execute(
        """
        SELECT eo.device_id
        FROM operations.entity_observation_current eo
        WHERE eo.tenant_id = %s AND eo.platform = %s AND eo.entity_key = %s
          AND eo.entity_type = %s
          AND eo.device_id IS NOT NULL
        LIMIT 1
        """,
        (tenant_id, source_name, external_id, entity_type),
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
            return rows[0][0]

    log.debug(
        "fast_path miss: source=%s external_id=%s hostname=%s",
        source_name, external_id, hostname,
    )
    return None
