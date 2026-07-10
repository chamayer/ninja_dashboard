"""Polling identity resolver (v1).

Scans entity_observations WHERE device_id IS NULL and attempts hostname-
based resolution. On a unique match, updates device_id in place. On
multiple candidates, creates an identity_candidates row for operator review.

Observations that stay unresolved get promoted to new operations.devices
rows immediately — every source row comes from an authoritative platform
inventory, so an unmatched hostname is a real device (legacy parity with
the AC engine, which created a device row for every unmatched hostname).

This is v1 (polling, not queue-governed). The identity.resolution queue
registry entry exists for health monitoring only; this function reads
entity_observations directly rather than consuming a queue table.
"""

from __future__ import annotations

import logging
import uuid

from psycopg.types.json import Json

from ingest import db
from ingest.normalize import normalize_hostname, os_family

log = logging.getLogger(__name__)

TENANT_ID = 1
_MIN_IDENTITY_CANDIDATES = 2


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
            SELECT observation_id, entity_type, entity_key, platform, client_id,
                   observed_at, canonical_data
            FROM operations.entity_observations
            WHERE tenant_id = %s AND device_id IS NULL
            ORDER BY observed_at DESC
            LIMIT %s
            """,
            (TENANT_ID, batch_size),
        )
        rows = cur.fetchall()

        source_ids = _load_source_ids(cur)

        for obs_id, _entity_type, entity_key, platform, client_id, observed_at, canonical_data in rows:
            cd = canonical_data or {}

            # Try serial number first (high confidence, unique hardware ID)
            serial = cd.get("serial_number")
            if serial:
                device_id = _resolve_by_serial(cur, serial, client_id)
                if device_id is not None:
                    _attach_observation(
                        cur, source_ids, obs_id, device_id, platform, entity_key,
                        cd, observed_at, "serial", 0.980,
                    )
                    resolved_count += 1
                    log.debug("resolver: serial match %s → device %s", entity_key, device_id)
                    continue

            vm_uuid = cd.get("vm_uuid")
            if vm_uuid:
                device_id = _resolve_by_vm_uuid(cur, vm_uuid, client_id)
                if device_id is not None:
                    _attach_observation(
                        cur, source_ids, obs_id, device_id, platform, entity_key,
                        cd, observed_at, "vm_uuid", 0.950,
                    )
                    resolved_count += 1
                    log.debug("resolver: vm_uuid match %s → device %s", entity_key, device_id)
                    continue

            # Fall back to normalised hostname
            hostname_raw = cd.get("hostname") or cd.get("guest_name")
            if not hostname_raw:
                continue
            norm = normalize_hostname(hostname_raw)
            if not norm:
                continue

            device_id = _resolve_by_hostname(cur, norm, client_id)
            if device_id is not None:
                _attach_observation(
                    cur, source_ids, obs_id, device_id, platform, entity_key,
                    cd, observed_at, "hostname_strict", 0.900,
                )
                resolved_count += 1
                log.debug("resolver: hostname match %s → device %s", entity_key, device_id)
            else:
                _maybe_create_candidate(cur, obs_id, entity_key, norm, client_id)

    log.info("resolver: resolved %d / %d observations", resolved_count, len(rows) if rows else 0)

    promoted_count = 0
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            promoted_count = _promote_unmatched_clusters(cur)
    except Exception:
        log.exception("resolver: device promotion failed — continuing")

    if resolved_count or promoted_count:
        try:
            with db.transaction() as cur:
                cur.execute("SELECT operations.refresh_agent_presence_current()")
            log.info("resolver: refreshed agent_presence_current after %d resolutions", resolved_count)
        except Exception:
            log.exception("resolver: agent_presence_current refresh failed — continuing")

    return resolved_count


def _load_source_ids(cur) -> dict[str, int]:
    cur.execute("SELECT name, id FROM operations.sources")
    return {row[0]: row[1] for row in cur.fetchall()}


def _resolve_by_serial(cur, serial: str, client_id: uuid.UUID | None) -> uuid.UUID | None:
    if client_id is None:
        return None
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_serial = %s AND deleted_at IS NULL
          AND (%s::uuid IS NULL OR client_id = %s)
        """,
        (TENANT_ID, serial, client_id, client_id),
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    return None


def _resolve_by_vm_uuid(cur, vm_uuid: str, client_id: uuid.UUID | None) -> uuid.UUID | None:
    if client_id is None:
        return None
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_vm_uuid = %s AND deleted_at IS NULL
          AND (%s::uuid IS NULL OR client_id = %s)
        """,
        (TENANT_ID, vm_uuid, client_id, client_id),
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    return None


def _resolve_by_hostname(cur, norm: str, client_id: uuid.UUID | None) -> uuid.UUID | None:
    if client_id is None:
        return None
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
          AND (%s::uuid IS NULL OR client_id = %s)
        """,
        (TENANT_ID, norm, client_id, client_id),
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    return None


def _attach_observation(
    cur,
    source_ids: dict[str, int],
    obs_id: uuid.UUID | None,
    device_id: uuid.UUID,
    platform: str,
    entity_key: str,
    canonical_data: dict,
    observed_at,
    match_method: str,
    match_confidence: float,
) -> None:
    display_name = (
        canonical_data.get("hostname")
        or canonical_data.get("guest_name")
        or entity_key
    )
    source_id = source_ids.get(platform)
    if source_id is not None:
        cur.execute(
            """
            INSERT INTO operations.device_links
                (id, version, tenant_id, device_id, source_id, external_id,
                 external_name, first_seen_at, last_seen_at,
                 match_method, match_confidence)
            VALUES (gen_random_uuid(), 1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, source_id, external_id)
            DO UPDATE SET
                device_id = EXCLUDED.device_id,
                external_name = COALESCE(NULLIF(EXCLUDED.external_name, ''),
                                         operations.device_links.external_name),
                last_seen_at = GREATEST(
                    COALESCE(operations.device_links.last_seen_at, EXCLUDED.last_seen_at),
                    EXCLUDED.last_seen_at
                ),
                match_method = EXCLUDED.match_method,
                match_confidence = EXCLUDED.match_confidence
            """,
            (
                TENANT_ID, device_id, source_id, entity_key, display_name,
                observed_at, observed_at, match_method, match_confidence,
            ),
        )
    if obs_id is not None:
        cur.execute(
            "UPDATE operations.entity_observations SET device_id = %s WHERE observation_id = %s",
            (device_id, obs_id),
        )


def _maybe_create_candidate(
    cur, obs_id: uuid.UUID, entity_key: str, norm: str, client_id: uuid.UUID | None
) -> None:
    """If multiple devices match the hostname, record an identity_candidate for review."""
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
          AND (%s::uuid IS NULL OR client_id = %s)
        LIMIT 3
        """,
        (TENANT_ID, norm, client_id, client_id),
    )
    rows = cur.fetchall()
    if len(rows) < _MIN_IDENTITY_CANDIDATES:
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


def _promote_unmatched_clusters(cur) -> int:
    """Create devices for unresolved (client, hostname) clusters.

    An observation cluster qualifies when: it is client-attributed, no
    existing device matched by serial or hostname, and no pending
    identity_candidate covers the hostname. The new device gets a
    device_link per (platform, entity_key) so future observations resolve
    on the fast path, and the cluster's observations are backfilled in
    place.
    """
    source_ids = _load_source_ids(cur)

    cur.execute(
        """
        SELECT client_id, platform, entity_type, entity_key,
               MIN(observed_at), MAX(observed_at),
               (ARRAY_AGG(canonical_data ORDER BY observed_at DESC))[1]
        FROM operations.entity_observations
        WHERE tenant_id = %s AND device_id IS NULL AND client_id IS NOT NULL
        GROUP BY client_id, platform, entity_type, entity_key
        """,
        (TENANT_ID,),
    )
    unresolved = cur.fetchall()
    if not unresolved:
        return 0

    # (client_id, norm) → list of (platform, entity_type, entity_key, first, last, cd)
    clusters: dict[tuple, list[tuple]] = {}
    for client_id, platform, entity_type, entity_key, first_seen, last_seen, raw_cd in unresolved:
        cd = raw_cd or {}
        hostname = cd.get("hostname") or cd.get("guest_name")
        norm = normalize_hostname(hostname)
        if not norm:
            continue
        clusters.setdefault((client_id, norm), []).append(
            (platform, entity_type, entity_key, first_seen, last_seen, cd)
        )

    promoted = 0
    for (client_id, norm), entries in clusters.items():
        # Re-check existing devices — the resolution loop only scans the
        # newest batch, so an older match may exist that it never saw.
        latest_cd = max(entries, key=lambda e: e[4])[5]
        serial = latest_cd.get("serial_number")
        existing_device_id = _resolve_by_serial(cur, serial, client_id) if serial else None
        if existing_device_id is None:
            vm_uuid = latest_cd.get("vm_uuid")
            existing_device_id = (
                _resolve_by_vm_uuid(cur, vm_uuid, client_id) if vm_uuid else None
            )
        if existing_device_id is None:
            existing_device_id = _resolve_by_hostname(cur, norm, client_id)
        if existing_device_id is not None:
            for platform, _entity_type, entity_key, _first_seen, e_last, cd in entries:
                _attach_observation(
                    cur, source_ids, None, existing_device_id, platform,
                    entity_key, cd, e_last, "hostname_strict", 0.900,
                )
                cur.execute(
                    """
                    UPDATE operations.entity_observations
                    SET device_id = %s
                    WHERE tenant_id = %s AND platform = %s AND entity_key = %s
                      AND device_id IS NULL
                    """,
                    (existing_device_id, TENANT_ID, platform, entity_key),
                )
            continue
        cur.execute(
            """
            SELECT COUNT(*) FROM operations.devices
            WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
              AND client_id = %s
            """,
            (TENANT_ID, norm, client_id),
        )
        if cur.fetchone()[0] >= _MIN_IDENTITY_CANDIDATES:
            continue  # ambiguous — leave for identity_candidates review

        display_name = latest_cd.get("hostname") or norm
        roles = {
            e[5].get("device_role") or e[5].get("device_type")
            for e in entries
        } - {None, ""}
        device_role = roles.pop() if len(roles) == 1 else "unknown"
        device_type = _infer_form_factor(entries)
        os_name = next(
            (e[5].get("os_name") for e in sorted(entries, key=lambda e: e[4], reverse=True)
             if e[5].get("os_name")),
            None,
        )
        platforms = sorted({e[0] for e in entries})
        device_id = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO operations.devices
                (id, version, tenant_id, client_id, canonical_hostname,
                 canonical_serial, canonical_vm_uuid, device_type, device_role,
                 os_name, os_family, exemptions,
                 created_at, created_reason, updated_at, updated_reason,
                 stale_reason, deleted_reason)
            VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, '{}'::jsonb,
                    NOW(), %s, NOW(), '', '', '')
            """,
            (
                device_id, TENANT_ID, client_id, norm, serial or "",
                latest_cd.get("vm_uuid") or "", device_type, device_role, os_name or "",
                os_family(os_name) if os_name else "",
                f"auto-promoted from {', '.join(platforms)}"[:120],
            ),
        )
        for platform, _entity_type, entity_key, _first, e_last, _cd in entries:
            source_id = source_ids.get(platform)
            if source_id is None:
                continue
            cur.execute(
                """
                INSERT INTO operations.device_links
                    (id, version, tenant_id, device_id, source_id,
                     external_id, external_name, first_seen_at, last_seen_at,
                     match_method, match_confidence)
                VALUES (gen_random_uuid(), 1, %s, %s, %s, %s, %s, %s, %s,
                        'promoted', 0.850)
                ON CONFLICT (tenant_id, source_id, external_id) DO NOTHING
                """,
                (TENANT_ID, device_id, source_id, entity_key, display_name,
                 _first, e_last),
            )
            cur.execute(
                """
                UPDATE operations.entity_observations
                SET device_id = %s
                WHERE tenant_id = %s AND platform = %s AND entity_key = %s
                  AND device_id IS NULL
                """,
                (device_id, TENANT_ID, platform, entity_key),
            )
        promoted += 1
        log.info(
            "resolver: promoted device %s hostname=%s client=%s platforms=%s",
            device_id, norm, client_id, platforms,
        )

    if promoted:
        log.info("resolver: promoted %d new devices", promoted)
    return promoted


def _infer_form_factor(entries: list[tuple]) -> str:
    values = [e[5] or {} for e in entries]
    node_classes = {(cd.get("node_class") or "").upper() for cd in values}
    entity_types = {e[1] for e in entries}
    if any(et == "network.device" for et in entity_types) or any(
        nc.startswith("NMS_") for nc in node_classes
    ):
        return "network-device"
    if any(et == "vm.host" for et in entity_types) or any(
        nc.endswith("_VM_HOST") or nc.endswith("_VMM_HOST") for nc in node_classes
    ):
        return "hypervisor-host"
    if any(et == "vm.guest" for et in entity_types) or any(
        bool(cd.get("is_vm")) for cd in values
    ):
        return "vm"
    if any(et and et.startswith("agent.") for et in entity_types):
        return "physical"
    return "unknown"
