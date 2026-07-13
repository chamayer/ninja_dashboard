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
from ingest.normalize import is_usable_serial, normalize_hostname, os_family

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
              AND entity_type <> 'org'  -- containers resolve to clients, not devices
            ORDER BY observed_at DESC
            LIMIT %s
            """,
            (TENANT_ID, batch_size),
        )
        rows = cur.fetchall()

        source_ids = _load_source_ids(cur)

        for obs_id, entity_type, entity_key, platform, client_id, observed_at, canonical_data in rows:
            cd = canonical_data or {}

            # Try serial number first (high confidence, unique hardware ID).
            # BIOS placeholder serials ('None', 'Default string', ...) are
            # shared across machines and must never drive a match.
            # A usable serial or vm_uuid match is PROOF of the same machine,
            # so it may attach even alongside another record of the same
            # (platform, entity_type) stream — that's a duplicate agent on
            # one machine: separate link, still flagged by the
            # duplicate_platform_record finding. Hostname alone stays
            # cross-stream only (same name could be two machines).
            serial = cd.get("serial_number")
            if is_usable_serial(serial):
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
            if device_id is not None and (
                not _same_stream_conflict(cur, device_id, platform, entity_type, entity_key)
                or _same_machine_on_device(cur, device_id, platform, entity_type, entity_key, cd)
            ):
                _attach_observation(
                    cur, source_ids, obs_id, device_id, platform, entity_key,
                    cd, observed_at, "hostname_strict", 0.900,
                )
                resolved_count += 1
                log.debug("resolver: hostname match %s → device %s", entity_key, device_id)
            elif device_id is None:
                _maybe_create_candidate(cur, obs_id, entity_key, norm, client_id)

    log.info("resolver: resolved %d / %d observations", resolved_count, len(rows) if rows else 0)

    promoted_count = 0
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            promoted_count = _promote_unmatched_clusters(cur)
    except Exception:
        log.exception("resolver: device promotion failed — continuing")

    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            _sync_device_attributes(cur)
    except Exception:
        log.exception("resolver: device attribute sync failed — continuing")

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


def _same_stream_conflict(
    cur, device_id: uuid.UUID, platform: str, entity_type: str, entity_key: str
) -> bool:
    """True when the device already carries a DIFFERENT record of this stream.

    Two records of the same (platform, entity_type) are potential duplicates
    (each consumes a license); they stay separate devices UNLESS a usable
    serial / vm_uuid / MAC proves they are the same machine (see
    _same_machine_on_device). Either way the evaluator surfaces the group
    as a duplicate_platform_record finding.
    """
    cur.execute(
        """
        SELECT 1 FROM operations.entity_observations
        WHERE tenant_id = %s AND device_id = %s
          AND platform = %s AND entity_type = %s AND entity_key <> %s
        LIMIT 1
        """,
        (TENANT_ID, device_id, platform, entity_type, entity_key),
    )
    return cur.fetchone() is not None


def _entries_same_machine(cd_a: dict, cd_b: dict) -> bool:
    """Hard proof two platform records describe one machine: equal usable
    serial, equal vm_uuid, or a shared MAC address."""
    sa, sb = cd_a.get("serial_number"), cd_b.get("serial_number")
    if (
        is_usable_serial(sa) and is_usable_serial(sb)
        and sa.strip().lower() == sb.strip().lower()
    ):
        return True
    ua, ub = cd_a.get("vm_uuid"), cd_b.get("vm_uuid")
    if ua and ub and str(ua).lower() == str(ub).lower():
        return True
    macs_a = set(cd_a.get("macs") or [])
    macs_b = set(cd_b.get("macs") or [])
    return bool(macs_a & macs_b)


def _same_machine_on_device(
    cur, device_id: uuid.UUID, platform: str, entity_type: str,
    entity_key: str, cd: dict,
) -> bool:
    """True when a conflicting same-stream record on the device is provably
    the same machine as the incoming observation (reprovisioned agent)."""
    cur.execute(
        """
        SELECT DISTINCT ON (entity_key) canonical_data
        FROM operations.entity_observations
        WHERE tenant_id = %s AND device_id = %s
          AND platform = %s AND entity_type = %s AND entity_key <> %s
        ORDER BY entity_key, observed_at DESC
        """,
        (TENANT_ID, device_id, platform, entity_type, entity_key),
    )
    return any(_entries_same_machine(cd, row[0] or {}) for row in cur.fetchall())


def _group_same_machine(stream_entries: list[tuple]) -> list[list[tuple]]:
    """Partition one stream's entries into machine groups.

    Entries proven to be the same machine (serial / vm_uuid / MAC) share a
    group — duplicate agents on one box. Unproven entries stay singletons
    (same hostname could be two real machines). Groups and entries are
    ordered newest-first.
    """
    ordered = sorted(stream_entries, key=lambda e: e[4] or e[3], reverse=True)
    groups: list[list[tuple]] = []
    for entry in ordered:
        cd = entry[5]
        for group in groups:
            if any(_entries_same_machine(cd, member[5]) for member in group):
                group.append(entry)
                break
        else:
            groups.append([entry])
    return groups


def _proof_match_method(cd_a: dict, cd_b: dict) -> tuple[str, float]:
    sa, sb = cd_a.get("serial_number"), cd_b.get("serial_number")
    if (
        is_usable_serial(sa) and is_usable_serial(sb)
        and sa.strip().lower() == sb.strip().lower()
    ):
        return "serial", 0.980
    ua, ub = cd_a.get("vm_uuid"), cd_b.get("vm_uuid")
    if ua and ub and str(ua).lower() == str(ub).lower():
        return "vm_uuid", 0.950
    return "mac", 0.960


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
            (id, version, tenant_id, observation_id, device_id_a, device_id_b,
             device_a_id, device_b_id, confidence, signals, status, created_at,
             resolved_by)
        VALUES (gen_random_uuid(), 1, %s, %s, %s, %s, %s, %s, 'low', %s,
                'pending', NOW(), '')
        ON CONFLICT DO NOTHING
        """,
        (
            TENANT_ID, obs_id, device_id_a, device_id_b, device_id_a, device_id_b,
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
    # The source queue drains resolution from one thread per source, so
    # concurrent promotions see the same NULL observations and each mint a
    # device — the loser's link INSERTs conflict away, leaving orphan
    # device rows. Serialize promotion; the linked-entity-key guard below
    # then turns later passes into pure backfills.
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext('operations.resolver_promotion'))"
    )
    source_ids = _load_source_ids(cur)

    cur.execute(
        """
        SELECT client_id, platform, entity_type, entity_key,
               MIN(observed_at), MAX(observed_at),
               (ARRAY_AGG(canonical_data ORDER BY observed_at DESC))[1]
        FROM operations.entity_observations
        WHERE tenant_id = %s AND device_id IS NULL AND client_id IS NOT NULL
          AND entity_type <> 'org'  -- containers resolve to clients, not devices
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
        # A record that already carries a device_link was resolved in an
        # earlier pass — these stale NULL observations just backfill; a new
        # device for them would be an empty orphan row.
        source_id = source_ids.get(platform)
        if source_id is not None:
            cur.execute(
                """
                SELECT device_id FROM operations.device_links
                WHERE tenant_id = %s AND source_id = %s AND external_id = %s
                """,
                (TENANT_ID, source_id, entity_key),
            )
            linked = cur.fetchone()
            if linked:
                cur.execute(
                    """
                    UPDATE operations.entity_observations
                    SET device_id = %s
                    WHERE tenant_id = %s AND platform = %s AND entity_key = %s
                      AND device_id IS NULL
                    """,
                    (linked[0], TENANT_ID, platform, entity_key),
                )
                continue
        clusters.setdefault((client_id, norm), []).append(
            (platform, entity_type, entity_key, first_seen, last_seen, cd)
        )

    promoted = 0
    for (client_id, norm), entries in clusters.items():
        # Hardware proof (serial / vm_uuid / MAC) is stream-agnostic, so the
        # whole cluster partitions into machine groups first: a Ninja rmm
        # record, its vm.guest twin, and both S1 agents sharing one MAC are
        # ONE machine. Hostname-only correlation then merges at most one
        # group per stream onto the cluster device (cross-stream rule);
        # any further group re-using an already-covered stream is a
        # potential duplicate machine/agent and gets its own device row so
        # every platform row stays accounted for.
        groups = _group_same_machine(entries)
        primary_groups: list[list[tuple]] = []
        extra_groups: list[list[tuple]] = []
        covered_streams: set[tuple[str, str]] = set()
        for group in groups:
            streams = {(e[0], e[1]) for e in group}
            if covered_streams & streams:
                extra_groups.append(group)
            else:
                primary_groups.append(group)
                covered_streams |= streams
        primary: list[tuple] = [e for g in primary_groups for e in g]

        # Re-check existing devices — the resolution loop only scans the
        # newest batch, so an older match may exist that it never saw.
        latest_cd = max(primary, key=lambda e: e[4])[5]
        serial = latest_cd.get("serial_number")
        if not is_usable_serial(serial):
            serial = None
        existing_device_id = _resolve_by_serial(cur, serial, client_id) if serial else None
        if existing_device_id is None:
            vm_uuid = latest_cd.get("vm_uuid")
            existing_device_id = (
                _resolve_by_vm_uuid(cur, vm_uuid, client_id) if vm_uuid else None
            )
        if existing_device_id is None:
            existing_device_id = _resolve_by_hostname(cur, norm, client_id)
        if existing_device_id is not None:
            for group in primary_groups:
                head = group[0]
                platform, entity_type, entity_key, _first_seen, e_last, cd = head
                if _same_stream_conflict(
                    cur, existing_device_id, platform, entity_type, entity_key
                ) and not _same_machine_on_device(
                    cur, existing_device_id, platform, entity_type, entity_key, cd
                ):
                    extra_groups.append(group)
                    continue
                for i, entry in enumerate(group):
                    platform, entity_type, entity_key, _first_seen, e_last, e_cd = entry
                    method, conf = (
                        ("hostname_strict", 0.900) if i == 0
                        else _proof_match_method(e_cd, head[5])
                    )
                    _attach_observation(
                        cur, source_ids, None, existing_device_id, platform,
                        entity_key, e_cd, e_last, method, conf,
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
            promoted += _promote_entry_groups(
                cur, source_ids, client_id, norm, extra_groups
            )
            continue

        display_name = latest_cd.get("hostname") or norm
        roles = {
            e[5].get("device_role") or e[5].get("device_type")
            for e in primary
        } - {None, ""}
        device_role = roles.pop() if len(roles) == 1 else "unknown"
        device_type = _infer_form_factor(primary)
        os_name = next(
            (e[5].get("os_name") for e in sorted(primary, key=lambda e: e[4], reverse=True)
             if e[5].get("os_name")),
            None,
        )
        platforms = sorted({e[0] for e in primary})
        device_id = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO operations.devices
                (id, version, tenant_id, client_id, canonical_hostname,
                 canonical_serial, canonical_vm_uuid, device_type, device_role,
                 lifecycle_status, os_name, os_family, exemptions,
                 created_at, created_reason, updated_at, updated_reason,
                 stale_reason, deleted_reason)
            VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s,
                    'active', %s, %s, '{}'::jsonb,
                    NOW(), %s, NOW(), '', '', '')
            """,
            (
                device_id, TENANT_ID, client_id, norm, serial or "",
                latest_cd.get("vm_uuid") or "", device_type, device_role, os_name or "",
                os_family(os_name) if os_name else "",
                f"auto-promoted from {', '.join(platforms)}"[:120],
            ),
        )
        for group in primary_groups:
            head = group[0]
            for i, entry in enumerate(group):
                platform, _entity_type, entity_key, _first, e_last, e_cd = entry
                source_id = source_ids.get(platform)
                if source_id is None:
                    continue
                method, conf = (
                    ("promoted", 0.850) if i == 0
                    else _proof_match_method(e_cd, head[5])
                )
                cur.execute(
                    """
                    INSERT INTO operations.device_links
                        (id, version, tenant_id, device_id, source_id,
                         external_id, external_name, first_seen_at, last_seen_at,
                         match_method, match_confidence)
                    VALUES (gen_random_uuid(), 1, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s)
                    ON CONFLICT (tenant_id, source_id, external_id) DO NOTHING
                    """,
                    (TENANT_ID, device_id, source_id, entity_key, display_name,
                     _first, e_last, method, conf),
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
        promoted += _promote_entry_groups(
            cur, source_ids, client_id, norm, extra_groups
        )

    if promoted:
        log.info("resolver: promoted %d new devices", promoted)
    return promoted


def _promote_entry_groups(
    cur, source_ids: dict[str, int], client_id, norm: str, groups: list[list[tuple]]
) -> int:
    """One device per machine group.

    A multi-entry group is one machine with duplicate agents (proven by
    serial / vm_uuid / MAC) — one device row, one link per record. A
    singleton is a same-hostname record with no proof either way — its own
    device row. Every platform record stays an accounted row; the evaluator
    flags groups as duplicate_platform_record.
    """
    promoted = 0
    for group in groups:
        head = group[0]
        platform, entity_type, entity_key, first_seen, last_seen, cd = head
        serial = cd.get("serial_number")
        if not is_usable_serial(serial):
            serial = None
        os_name = cd.get("os_name")
        device_id = uuid.uuid4()
        reason = (
            f"duplicate {platform} {entity_type} record — kept separate"
            if len(group) == 1
            else f"{platform} {entity_type} duplicate agents on one machine ({len(group)} records)"
        )
        cur.execute(
            """
            INSERT INTO operations.devices
                (id, version, tenant_id, client_id, canonical_hostname,
                 canonical_serial, canonical_vm_uuid, device_type, device_role,
                 lifecycle_status, os_name, os_family, exemptions,
                 created_at, created_reason, updated_at, updated_reason,
                 stale_reason, deleted_reason)
            VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s,
                    'active', %s, %s, '{}'::jsonb,
                    NOW(), %s, NOW(), '', '', '')
            """,
            (
                device_id, TENANT_ID, client_id, norm, serial or "",
                cd.get("vm_uuid") or "",
                _infer_form_factor(group),
                cd.get("device_role") or "unknown",
                os_name or "", os_family(os_name) if os_name else "",
                reason[:120],
            ),
        )
        for i, entry in enumerate(group):
            platform, entity_type, entity_key, first_seen, last_seen, e_cd = entry
            source_id = source_ids.get(platform)
            if source_id is not None:
                method, conf = (
                    ("promoted", 0.850) if i == 0
                    else _proof_match_method(e_cd, cd)
                )
                cur.execute(
                    """
                    INSERT INTO operations.device_links
                        (id, version, tenant_id, device_id, source_id,
                         external_id, external_name, first_seen_at, last_seen_at,
                         match_method, match_confidence)
                    VALUES (gen_random_uuid(), 1, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s)
                    ON CONFLICT (tenant_id, source_id, external_id) DO NOTHING
                    """,
                    (TENANT_ID, device_id, source_id, entity_key,
                     e_cd.get("hostname") or norm, first_seen, last_seen,
                     method, conf),
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
            "resolver: promoted duplicate-record device %s hostname=%s platform=%s records=%d",
            device_id, norm, platform, len(group),
        )
    return promoted


def _sync_device_attributes(cur) -> None:
    """Recompute device_role / device_type / os_* from ALL linked observations.

    Devices are created from whichever observation group resolves first, so
    a device promoted from an LMI-only cluster gets role 'unknown' even
    though the Ninja record that attaches later carries node_class=SERVER.
    Set-based and idempotent — attribute truth is order-independent.
    """
    # Role: fill 'unknown' only when linked observations agree on exactly
    # one explicit role. Conflicts stay 'unknown' (visible), never guessed.
    cur.execute(
        """
        WITH sig AS (
            SELECT device_id,
                   ARRAY_AGG(DISTINCT canonical_data->>'device_role')
                       FILTER (WHERE COALESCE(canonical_data->>'device_role', '') <> '') AS roles
            FROM operations.entity_observations
            WHERE tenant_id = %s AND device_id IS NOT NULL
            GROUP BY device_id
        )
        UPDATE operations.devices d
        SET device_role = sig.roles[1],
            updated_at = NOW(),
            updated_reason = 'attribute sync from observations'
        FROM sig
        WHERE d.id = sig.device_id
          AND COALESCE(d.device_role, 'unknown') IN ('unknown', '')
          AND cardinality(sig.roles) = 1
        """,
        (TENANT_ID,),
    )
    if cur.rowcount:
        log.info("resolver: attribute sync set device_role on %d devices", cur.rowcount)

    # Form factor: same precedence as _infer_form_factor, over all streams.
    cur.execute(
        """
        WITH ft AS (
            SELECT eo.device_id,
                   BOOL_OR(eo.entity_type = 'network.device'
                           OR COALESCE(eo.canonical_data->>'node_class', '') ~ '^NMS_') AS is_net,
                   BOOL_OR(eo.entity_type = 'vm.host'
                           OR COALESCE(eo.canonical_data->>'node_class', '') ~ '(_VMM_HOST|_VM_HOST)$') AS is_host,
                   BOOL_OR(eo.entity_type = 'vm.guest'
                           OR COALESCE(eo.canonical_data->>'node_class', '') ~ '(_VMM_GUEST|_VM_GUEST)$'
                           OR COALESCE(eo.canonical_data->>'is_vm', '') IN ('true', 'True', '1')) AS is_vm,
                   BOOL_OR(eo.entity_type LIKE 'agent.%%') AS is_agent
            FROM operations.entity_observations eo
            WHERE eo.tenant_id = %s AND eo.device_id IS NOT NULL
            GROUP BY eo.device_id
        )
        UPDATE operations.devices d
        SET device_type = t.target,
            updated_at = NOW(),
            updated_reason = 'attribute sync from observations'
        FROM (
            SELECT device_id,
                   CASE WHEN is_net THEN 'network-device'
                        WHEN is_host THEN 'hypervisor-host'
                        WHEN is_vm THEN 'vm'
                        WHEN is_agent THEN 'physical'
                        ELSE 'unknown' END AS target
            FROM ft
        ) t
        WHERE d.id = t.device_id AND d.device_type IS DISTINCT FROM t.target
        """,
        (TENANT_ID,),
    )
    if cur.rowcount:
        log.info("resolver: attribute sync set device_type on %d devices", cur.rowcount)

    # OS: backfill devices with no os_name from the newest observation
    # that carries one (os_family derives in Python, so update per row).
    cur.execute(
        """
        SELECT DISTINCT ON (eo.device_id) eo.device_id, eo.canonical_data->>'os_name'
        FROM operations.entity_observations eo
        JOIN operations.devices d ON d.id = eo.device_id
        WHERE eo.tenant_id = %s AND COALESCE(d.os_name, '') = ''
          AND COALESCE(eo.canonical_data->>'os_name', '') <> ''
        ORDER BY eo.device_id, eo.observed_at DESC
        """,
        (TENANT_ID,),
    )
    os_rows = cur.fetchall()
    for device_id, os_name in os_rows:
        cur.execute(
            """
            UPDATE operations.devices
            SET os_name = %s, os_family = %s,
                updated_at = NOW(), updated_reason = 'attribute sync from observations'
            WHERE id = %s
            """,
            (os_name, os_family(os_name), device_id),
        )
    if os_rows:
        log.info("resolver: attribute sync set os_name on %d devices", len(os_rows))


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
