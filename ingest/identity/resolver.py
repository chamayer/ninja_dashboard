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
from typing import Any

from psycopg.types.json import Json

from ingest import db, device_cache_projector
from ingest.identity import identity_entity_types
from ingest.normalize import (
    form_factor_for_node_class,
    is_macos_name,
    is_usable_serial,
    load_identity_value_rejections,
    normalize_hostname,
    normalize_loose_hostname,
    os_family,
)

log = logging.getLogger(__name__)

TENANT_ID = 1
_MIN_IDENTITY_CANDIDATES = 2


def drain_resolution(batch_size: int = 200, *, refresh_current: bool = True) -> int:
    """Resolve up to batch_size unresolved entity_observations.

    Returns the count of observations that were resolved (device_id set).
    Refreshes device_agent_presence_current if any observations were resolved,
    unless the caller will immediately run the full derived-state coordinator.
    """
    resolved_count = 0
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
        load_identity_value_rejections(cur)

        cur.execute(
            """
            SELECT observation_id, entity_type, entity_key, platform, client_id,
                   observed_at, canonical_data
            FROM operations.entity_observation_current
            WHERE tenant_id = %s AND device_id IS NULL
              AND active = TRUE
              -- Allowlist, not `<> 'org'`: only identity-signal streams may
              -- be matched or promoted into a Device. Documentation rows
              -- (doc.*) would otherwise be hostname-matched on an asset name
              -- and promoted into Devices invented from a wiki page.
              AND entity_type = ANY(%s)
            ORDER BY observed_at DESC
            LIMIT %s
            """,
            (TENANT_ID, sorted(identity_entity_types(cur)), batch_size),
        )
        rows = cur.fetchall()

        identity_conflict_ft_id = _load_finding_type_id(cur, "identity_conflict")

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
                    _attach_observation(cur, obs_id, device_id)
                    resolved_count += 1
                    log.debug("resolver: serial match %s → device %s", entity_key, device_id)
                    continue

            vm_uuid = cd.get("vm_uuid")
            if vm_uuid:
                device_id = _resolve_by_vm_uuid(cur, vm_uuid, client_id)
                if device_id is not None:
                    _attach_observation(cur, obs_id, device_id)
                    resolved_count += 1
                    log.debug("resolver: vm_uuid match %s → device %s", entity_key, device_id)
                    continue

            # Fall back to normalized hostname
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
                _attach_observation(cur, obs_id, device_id)
                resolved_count += 1
                log.debug("resolver: hostname match %s → device %s", entity_key, device_id)
            elif device_id is None:
                _maybe_create_candidate(
                    cur, obs_id, entity_key, norm, client_id,
                    identity_conflict_ft_id=identity_conflict_ft_id,
                )

    log.info("resolver: resolved %d / %d observations", resolved_count, len(rows) if rows else 0)

    promoted_count = 0
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            promoted_count = _promote_unmatched_clusters(cur)
    except Exception:
        log.exception("resolver: device promotion failed — continuing")

    # ADR-0012: the projector is the sole writer of the five device cache
    # columns. It must run before _sync_device_attributes, which copies that
    # cache into the layer entities — otherwise the facets propagate the
    # previous cycle's values.
    try:
        counts = device_cache_projector.project(dry_run=False, tenant_id=TENANT_ID)
        log.info("resolver: device cache projection %s", counts)
    except Exception:
        log.exception("resolver: device cache projection failed — continuing")

    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            _sync_device_attributes(cur)
    except Exception:
        log.exception("resolver: layer propagation failed — continuing")

    # After promotion and projection have settled the device rows this reads.
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            counts = project_merge_candidates(cur)
        log.info("resolver: merge candidates %s", counts)
    except Exception:
        log.exception("resolver: merge candidate projection failed — continuing")

    if (resolved_count or promoted_count) and refresh_current:
        # Refresh derived presence matviews in dependency order:
        # device_agent_presence_current first (per-source × device), then
        # device_session_current (per-device rollup). Formalized as a
        # refresh manifest in Track O batch O5.
        try:
            with db.transaction() as cur:
                cur.execute("SELECT operations.refresh_device_agent_presence_current()")
            log.info("resolver: refreshed device_agent_presence_current after %d resolutions", resolved_count)
        except Exception:
            log.exception("resolver: device_agent_presence_current refresh failed — continuing")
        else:
            try:
                with db.transaction() as cur:
                    cur.execute("SELECT operations.refresh_device_session_current()")
                log.info("resolver: refreshed device_session_current")
            except Exception:
                log.exception("resolver: device_session_current refresh failed — continuing")

    return resolved_count


def _load_agent_ids(cur) -> dict[str, int]:
    """Map canonical Agent-product name → operations.agents.id.

    Ninja / SentinelOne / LogMeIn / ScreenConnect are the seeded Agent
    products (migration 0033). Observation `platform` values are
    already normalized to these names via `canonical_platform()` in
    `ingest/normalize.py`, so a direct name lookup is sufficient.
    """
    cur.execute("SELECT name, id FROM operations.agents")
    return {row[0]: row[1] for row in cur.fetchall()}


def _load_finding_type_id(cur, name: str) -> int | None:
    cur.execute(
        "SELECT id FROM operations.finding_types WHERE name = %s",
        (name,),
    )
    row = cur.fetchone()
    return row[0] if row else None


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
        SELECT 1 FROM operations.entity_observation_current
        WHERE tenant_id = %s AND device_id = %s
          AND active = TRUE
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
        FROM operations.entity_observation_current
        WHERE tenant_id = %s AND device_id = %s
          AND active = TRUE
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


def _attach_observation(cur, obs_id: uuid.UUID | None, device_id: uuid.UUID) -> None:
    """Attach one observation to a device.

    This used to also upsert `operations.device_links`, carrying the match
    method, confidence, display name and observed timestamps needed for that
    row. Migration 0121 retires both that write and the table — attachment
    authority is observations ->
    sync_entity_source_links_from_observations() — so the only remaining
    responsibility is the device_id, and the parameters that existed solely to
    populate the link are gone rather than left unused.
    """
    if obs_id is not None:
        cur.execute(
            "UPDATE operations.entity_observation_current SET device_id = %s WHERE observation_id = %s",
            (device_id, obs_id),
        )


def _maybe_create_candidate(
    cur,
    obs_id: uuid.UUID,
    entity_key: str,
    norm: str,
    client_id: uuid.UUID | None,
    identity_conflict_ft_id: int | None = None,
) -> None:
    """If multiple devices match the hostname, record the conflict.

    This emits the *notification* — an `identity_conflict` Finding
    (ADR-0005 slice 3). The reviewable *proposal* is produced separately by
    `project_merge_candidates`, which reconciles against current device state
    rather than firing from here: a collision exists whether or not an
    observation happens to be pending, and this function only runs for
    unresolved ones.
    """
    cur.execute(
        """
        SELECT id FROM operations.devices
        WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
          AND (%s::uuid IS NULL OR client_id = %s)
        LIMIT 5
        """,
        (TENANT_ID, norm, client_id, client_id),
    )
    rows = cur.fetchall()
    if len(rows) < _MIN_IDENTITY_CANDIDATES:
        return
    candidate_ids = [row[0] for row in rows]
    device_id_a = candidate_ids[0]

    # Standard operator-visible surface — the ADR's mandated path.
    # condition_key deduplicates repeat observations of the same
    # hostname collision within a tenant.
    if identity_conflict_ft_id is not None:
        cur.execute(
            """
            INSERT INTO operations.findings (
                id, version, tenant_id, finding_type_id, client_id,
                subject_type, subject_id, subject_layer,
                subject_layer_entity_id, finding_details, condition_key,
                severity, confidence, status, first_seen_at, last_seen_at,
                last_detected_at
            )
            VALUES (
                gen_random_uuid(), 1, %s, %s, %s,
                'device', %s, '', NULL, %s, %s,
                'high', 'confirmed', 'open', NOW(), NOW(), NOW()
            )
            ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
            DO UPDATE SET
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details
            """,
            (
                TENANT_ID,
                identity_conflict_ft_id,
                client_id,
                device_id_a,
                Json({
                    "hostname": norm,
                    "candidate_count": len(rows),
                    "candidate_device_ids": [str(x) for x in candidate_ids],
                    "trigger_observation_id": str(obs_id),
                }),
                f"identity_conflict:{norm}",
            ),
        )



_MERGE_CANDIDATE_UPSERT = """
WITH collisions AS (
    SELECT d.client_id,
           d.canonical_hostname,
           COUNT(*) AS member_count,
           JSONB_AGG(
               JSONB_BUILD_OBJECT(
                   'device_id', d.id,
                   'hostname', d.canonical_hostname,
                   'serial', COALESCE(d.canonical_serial, ''),
                   'vm_uuid', COALESCE(d.canonical_vm_uuid, ''),
                   'device_type', d.device_type,
                   'device_role', d.device_role,
                   'os_name', COALESCE(d.os_name, ''),
                   'created_at', d.created_at
               ) ORDER BY d.created_at
           ) AS members
    FROM operations.devices d
    WHERE d.tenant_id = %s AND d.deleted_at IS NULL AND d.canonical_hostname <> ''
    GROUP BY d.client_id, d.canonical_hostname
    HAVING COUNT(*) >= %s
)
INSERT INTO operations.merge_candidates
    (id, version, tenant_id, client_id, entity_type, canonical_key,
     member_snapshots, member_observation_ids, match_reason, confidence, status)
SELECT gen_random_uuid(), 1, %s, c.client_id, 'device',
       'identity_conflict:' || c.canonical_hostname,
       c.members, NULL,
       FORMAT('%%s devices share the normalized hostname %%s within one client',
              c.member_count, c.canonical_hostname),
       0.9000, 'open'
FROM collisions c
ON CONFLICT (tenant_id, canonical_key) WHERE status = 'open'
DO UPDATE SET
    member_snapshots = EXCLUDED.member_snapshots,
    match_reason = EXCLUDED.match_reason,
    client_id = EXCLUDED.client_id
"""


_MERGE_CANDIDATE_CLOSE = """
UPDATE operations.merge_candidates mc
SET status = 'merged'
WHERE mc.tenant_id = %s
  AND mc.status = 'open'
  AND mc.entity_type = 'device'
  AND NOT EXISTS (
      SELECT 1
      FROM operations.devices d
      WHERE d.tenant_id = mc.tenant_id
        AND d.deleted_at IS NULL
        AND d.canonical_hostname <> ''
        AND 'identity_conflict:' || d.canonical_hostname = mc.canonical_key
      GROUP BY d.client_id, d.canonical_hostname
      HAVING COUNT(*) >= %s
  )
"""


def project_merge_candidates(cur) -> dict[str, int]:
    """Reconcile `operations.merge_candidates` against current collisions.

    A reconciling pass, not a detection side effect. The first attempt hooked
    production onto `_maybe_create_candidate`, which only runs while resolving
    an observation that has no device yet. Measured against production there
    were zero such observations and nineteen open `identity_conflict`
    findings, so the queue would have stayed permanently empty while real
    collisions existed. A collision is a property of current device state, so
    it is projected from that.

    `canonical_key` matches the finding's `condition_key`, so the notification
    and the proposal address the same collision. Proposals whose collision no
    longer holds — after a merge, a rename or a deletion — are closed, so the
    queue reflects what is true now rather than accumulating stale rows.
    """
    cur.execute(_MERGE_CANDIDATE_UPSERT, (TENANT_ID, _MIN_IDENTITY_CANDIDATES, TENANT_ID))
    upserted = cur.rowcount or 0
    cur.execute(_MERGE_CANDIDATE_CLOSE, (TENANT_ID, _MIN_IDENTITY_CANDIDATES))
    closed = cur.rowcount or 0
    return {"upserted": upserted, "closed": closed}


def _collapse_mac_variants(
    clusters: dict[tuple, list[tuple]],
) -> dict[tuple, list[tuple]]:
    """Merge Mac hostname separator variants within a client.

    Legacy `_apply_mac_safe_matches` port. `GCNY-25s-iMac.local` and
    `GCNY-25's iMac` share a loose_hostname (`gcny25simac`) that the
    strict normalizer drops apart. Collapse them into ONE cluster only
    when the same client sees them across ≥2 platforms AND no single
    platform has >1 entity_key under the loose key (otherwise we'd
    merge distinct devices).
    """
    # (client_id, loose_key) → list of (cluster_key, cluster_entries)
    grouped: dict[tuple, list[tuple]] = {}
    for key, entries in clusters.items():
        client_id, norm = key
        # Any Mac-family entry qualifies the cluster for loose matching.
        head_cd = entries[0][5] if entries else {}
        os_name = head_cd.get("os_name") or head_cd.get("osName") or ""
        if not is_macos_name(os_name):
            continue
        hostname = head_cd.get("hostname") or head_cd.get("guest_name") or norm
        loose = normalize_loose_hostname(str(hostname))
        if not loose or len(loose) < 6:
            continue
        grouped.setdefault((client_id, loose), []).append((key, entries))

    # Pick a canonical cluster per (client, loose) group and merge others in.
    for (_client_id, _loose), group in grouped.items():
        if len(group) < 2:
            continue
        # Count platforms and per-platform entity_key counts.
        platforms: set[str] = set()
        ids_by_platform: dict[str, set[str]] = {}
        for _key, entries in group:
            for platform, _entity_type, entity_key, _first, _last, _cd in entries:
                platforms.add(platform)
                ids_by_platform.setdefault(platform, set()).add(entity_key)
        if len(platforms) < 2:
            continue
        if any(len(ids) > 1 for ids in ids_by_platform.values()):
            continue
        # Safe to merge — pick the longest norm as canonical (most information).
        canonical_key = max(group, key=lambda kv: len(kv[0][1]))[0]
        merged: list[tuple] = []
        for key, entries in group:
            merged.extend(entries)
            if key != canonical_key:
                clusters.pop(key, None)
        clusters[canonical_key] = merged

    return clusters


def _collapse_prefix_variants(
    clusters: dict[tuple, list[tuple]],
) -> dict[tuple, list[tuple]]:
    """Merge truncated hostname variants within a client.

    Legacy `_apply_prefix_matches` port. If `norm_A` is a prefix of
    `norm_B` (both ≥10 chars) and B is the unique such peer for A within
    the same client, treat them as the same machine (longer wins as
    canonical — has more information).
    """
    # client_id → set(norm)
    norms_by_client: dict[Any, set[str]] = {}
    for (client_id, norm), _entries in clusters.items():
        norms_by_client.setdefault(client_id, set()).add(norm)

    rewrites: dict[tuple, tuple] = {}
    for client_id, norms in norms_by_client.items():
        for norm in norms:
            candidates = [
                other for other in norms
                if other != norm
                and min(len(other), len(norm)) >= 10
                and (other.startswith(norm) or norm.startswith(other))
            ]
            if len(candidates) != 1:
                continue
            candidate = candidates[0]
            canonical = candidate if len(candidate) > len(norm) else norm
            if canonical == norm:
                continue
            rewrites[(client_id, norm)] = (client_id, canonical)

    for src, dst in rewrites.items():
        src_entries = clusters.pop(src, None)
        if src_entries is None:
            continue
        clusters.setdefault(dst, []).extend(src_entries)
    return clusters


def _create_device_anchor(cur, device_id, client_id, created_reason: str) -> None:
    """Create the generic entity anchor for a device being promoted.

    ADR-0005 makes Device a learned identity anchor, so a device row without
    its `entities` row is the inversion ADR-0013 objects to. Until now the
    anchor was created after the fact by
    `operations.sync_entity_source_links_from_observations()`, which runs in a
    later transaction (`ingest/derived.py`). That left every freshly promoted
    device with a NULL `entity_id` for part of a cycle and made
    `entity_id NOT NULL` -- the first E6 constraint -- impossible to apply.

    The anchor reuses the device UUID, matching the backfill in migration 0101,
    so `entities.id = devices.id` continues to hold. `ON CONFLICT DO NOTHING`
    keeps the sync function idempotent alongside this.
    """
    cur.execute(
        """
        INSERT INTO operations.entities
            (id, tenant_id, entity_class_id, scope_kind, client_id, version,
             created_at, created_reason, updated_at, updated_reason,
             retired_at, retired_reason, deleted_at, deleted_reason)
        VALUES (%s, %s, 'device', 'client', %s, 1,
                NOW(), %s, NOW(), %s, NULL, '', NULL, '')
        ON CONFLICT (id) DO NOTHING
        """,
        (device_id, TENANT_ID, client_id, created_reason[:120], created_reason[:120]),
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
    agent_ids = _load_agent_ids(cur)

    cur.execute(
        """
        SELECT client_id, platform, entity_type, entity_key,
               MIN(observed_at), MAX(observed_at),
               (ARRAY_AGG(canonical_data ORDER BY observed_at DESC))[1]
        FROM operations.entity_observation_current
        WHERE tenant_id = %s AND device_id IS NULL AND client_id IS NOT NULL
          AND active = TRUE
          -- Allowlist, not `<> 'org'`. This query PROMOTES unmatched rows
          -- into brand-new Devices, so anything reaching it becomes canonical
          -- inventory. A `<> 'org'` exclusion let documentation rows through:
          -- 4,991 Devices were minted from Hudu doc.asset records before this
          -- was caught. Promotion must be opt-in per entity type.
          AND entity_type = ANY(%s)
        GROUP BY client_id, platform, entity_type, entity_key
        """,
        (TENANT_ID, sorted(identity_entity_types(cur))),
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
        # A record already attached to a device was resolved in an earlier
        # pass — these stale NULL observations just backfill; a new device for
        # them would be an empty orphan row.
        #
        # This guard used to read `operations.device_links`, which was written
        # a few lines below in this same transaction. Migration 0121 retires
        # that write, and the replacement `entity_source_links` is only
        # derived later in the cycle by
        # sync_entity_source_links_from_observations(). Reading the derived
        # table here would leave the guard blind to anything attached during
        # the current run and mint a duplicate device for it — the same
        # ordering trap the entity anchor had before 322d2a4.
        #
        # The sibling observation is the correct source: every attachment,
        # whether by fast path, by this resolver or by promotion, sets
        # `entity_observation_current.device_id` in the transaction that makes
        # it. Verified against production before the cutover: across all four
        # sources, zero (source, external_id) keys disagreed between the link
        # table and the observation's device_id.
        cur.execute(
            """
            SELECT device_id FROM operations.entity_observation_current
            WHERE tenant_id = %s AND platform = %s AND entity_key = %s
              AND entity_type = %s AND device_id IS NOT NULL
            LIMIT 1
            """,
            (TENANT_ID, platform, entity_key, entity_type),
        )
        linked = cur.fetchone()
        if linked:
            cur.execute(
                """
                UPDATE operations.entity_observation_current
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

    clusters = _collapse_mac_variants(clusters)
    clusters = _collapse_prefix_variants(clusters)

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
                # The `_attach_observation` call that stood here passed
                # obs_id=None, so its only effect was the source-link upsert
                # retired by migration 0121. The observation UPDATE below was
                # already doing the attaching.
                for entry in group:
                    platform, entity_type, entity_key = entry[0], entry[1], entry[2]
                    cur.execute(
                        """
                        UPDATE operations.entity_observation_current
                        SET device_id = %s
                        WHERE tenant_id = %s AND platform = %s AND entity_key = %s
                          AND device_id IS NULL
                        """,
                        (existing_device_id, TENANT_ID, platform, entity_key),
                    )
            promoted += _promote_entry_groups(
                cur, agent_ids, client_id, norm, extra_groups
            )
            continue

        # device_role is no longer derived here — the projector owns it. The
        # layer entities below still need a form factor at creation time; the
        # facet propagation reconciles it against the projector-owned cache on
        # the next cycle.
        device_type = _infer_form_factor(primary)
        os_name = next(
            (e[5].get("os_name") for e in sorted(primary, key=lambda e: e[4], reverse=True)
             if e[5].get("os_name")),
            None,
        )
        platforms = sorted({e[0] for e in primary})
        device_id = uuid.uuid4()
        promote_reason = f"auto-promoted from {', '.join(platforms)}"
        _create_device_anchor(cur, device_id, client_id, promote_reason)
        cur.execute(
            """
            -- ADR-0012: promotion creates the identity anchor only. The five
            -- cache columns are NOT NULL, so they get neutral placeholders
            -- here and `device_cache_projector` fills them later in this same
            -- resolver cycle. Stamping the promoting observation's values
            -- would make promotion a second producer, and the previous
            -- hardcoded os_group='Unknown' is exactly how 17 devices ended up
            -- stuck on a sentinel nothing ever revisited.
            INSERT INTO operations.devices
                (id, version, tenant_id, client_id, entity_id, canonical_hostname,
                 canonical_serial, canonical_vm_uuid, device_type, device_role,
                 lifecycle_status, os_name, os_family, os_group,
                 created_at, created_reason, updated_at, updated_reason,
                 stale_reason, deleted_reason)
            VALUES (%s, 1, %s, %s, %s, %s, %s, %s, 'unknown', 'unknown',
                    'active', '', '', 'Unknown',
                    NOW(), %s, NOW(), '', '', '')
            """,
            (
                device_id, TENANT_ID, client_id, device_id, norm, serial or "",
                latest_cd.get("vm_uuid") or "",
                promote_reason[:120],
            ),
        )
        _first_seen = min((e[3] for e in primary if e[3]), default=None)
        _last_seen = max((e[4] for e in primary if e[4]), default=None)
        _write_layer_entities_for_new_device(
            cur,
            device_id=device_id,
            form_factor=device_type,
            serial=serial or "",
            vm_uuid=latest_cd.get("vm_uuid") or "",
            os_name=os_name or "",
            os_fam=os_family(os_name) if os_name else "",
            os_group="Unknown",
            first_seen=_first_seen,
            last_seen=_last_seen,
            entries=primary,
            agent_ids=agent_ids,
        )
        # Attach every record in the promoted groups. The paired
        # source-link INSERT is retired with migration 0121; the observation
        # update below is now the whole attachment, and
        # sync_entity_source_links_from_observations() derives the link.
        for group in primary_groups:
            for entry in group:
                platform, _entity_type, entity_key = entry[0], entry[1], entry[2]
                cur.execute(
                    """
                    UPDATE operations.entity_observation_current
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
            cur, agent_ids, client_id, norm, extra_groups
        )

    if promoted:
        log.info("resolver: promoted %d new devices", promoted)
    return promoted


def _promote_entry_groups(
    cur,
    agent_ids: dict[str, int],
    client_id,
    norm: str,
    groups: list[list[tuple]],
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
        _create_device_anchor(cur, device_id, client_id, reason)
        cur.execute(
            """
            -- ADR-0012: neutral placeholders only. See the sibling INSERT in
            -- _promote_unmatched_clusters; device_cache_projector fills these
            -- later in the same cycle.
            INSERT INTO operations.devices
                (id, version, tenant_id, client_id, entity_id, canonical_hostname,
                 canonical_serial, canonical_vm_uuid, device_type, device_role,
                 lifecycle_status, os_name, os_family, os_group,
                 created_at, created_reason, updated_at, updated_reason,
                 stale_reason, deleted_reason)
            VALUES (%s, 1, %s, %s, %s, %s, %s, %s, 'unknown', 'unknown',
                    'active', '', '', 'Unknown',
                    NOW(), %s, NOW(), '', '', '')
            """,
            (
                device_id, TENANT_ID, client_id, device_id, norm, serial or "",
                cd.get("vm_uuid") or "",
                reason[:120],
            ),
        )
        _group_first = min((e[3] for e in group if e[3]), default=None)
        _group_last = max((e[4] for e in group if e[4]), default=None)
        _write_layer_entities_for_new_device(
            cur,
            device_id=device_id,
            form_factor=_infer_form_factor(group),
            serial=serial or "",
            vm_uuid=cd.get("vm_uuid") or "",
            os_name=os_name or "",
            os_fam=os_family(os_name) if os_name else "",
            os_group="Unknown",
            first_seen=_group_first,
            last_seen=_group_last,
            entries=group,
            agent_ids=agent_ids,
        )
        # As above: the source-link INSERT that paired with this update is
        # retired with migration 0121.
        for entry in group:
            platform, entity_type, entity_key = entry[0], entry[1], entry[2]
            cur.execute(
                """
                UPDATE operations.entity_observation_current
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


def _upsert_shared_serial_findings(cur, finding_type_id: int) -> int:
    """Upsert shared-serial findings with a UUID canonical subject.

    JSON evidence retains text IDs for compatibility, but ``subject_id`` is a
    typed Device UUID. Ordering by UUID text preserves the historical
    deterministic subject selection without coercing the selected value to
    text before insertion.
    """
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, subject_layer,
            subject_layer_entity_id, finding_details, condition_key,
            severity, confidence, status, first_seen_at, last_seen_at,
            last_detected_at
        )
        SELECT
            gen_random_uuid(), 1, sub.tenant_id, %s, sub.client_id,
            'device', sub.first_device_id, '', NULL,
            jsonb_build_object(
                'serial',       sub.serial,
                'device_count', sub.device_count,
                'device_ids',   sub.device_ids,
                'hostnames',    sub.hostnames
            ),
            'shared_serial:' || sub.client_id || ':' || sub.serial,
            'high', 'confirmed', 'open',
            NOW(), NOW(), NOW()
        FROM (
            SELECT
                d.tenant_id, d.client_id,
                d.canonical_serial AS serial,
                COUNT(*) AS device_count,
                (ARRAY_AGG(d.id ORDER BY d.id::text))[1] AS first_device_id,
                ARRAY_AGG(d.id::text ORDER BY d.id::text) AS device_ids,
                ARRAY_AGG(d.canonical_hostname ORDER BY d.id::text) AS hostnames
            FROM operations.devices d
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND COALESCE(d.canonical_serial, '') <> ''
              AND LENGTH(BTRIM(d.canonical_serial)) >= 4
              AND LENGTH(REPLACE(
                    BTRIM(d.canonical_serial), LEFT(BTRIM(d.canonical_serial), 1), ''
                  )) > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM operations.identity_value_rejections rejected
                  WHERE rejected.value_kind = 'serial'
                    AND rejected.enabled
                    AND rejected.normalized_value = LOWER(BTRIM(d.canonical_serial))
              )
            GROUP BY d.tenant_id, d.client_id, d.canonical_serial
            HAVING COUNT(*) > 1
        ) sub
        ON CONFLICT (tenant_id, condition_key)
        WHERE condition_key > '' AND status IN ('open', 'acknowledged')
        DO UPDATE SET
            last_seen_at = NOW(),
            last_detected_at = NOW(),
            finding_details = EXCLUDED.finding_details
        """,
        (finding_type_id, TENANT_ID),
    )
    return cur.rowcount


def _upsert_cross_client_serial_findings(cur, finding_type_id: int) -> int:
    """Emit one review finding per device for usable cross-client serials.

    A serial exact match is only automatic identity evidence within a client.
    Seeing the same usable value under different clients is an ownership or
    source-attribution conflict, never authority to merge the devices. Each
    device receives its own finding so both client views expose the conflict.
    """
    cur.execute(
        """
        WITH source_serials AS (
            SELECT
                DISTINCT d.id,
                d.tenant_id,
                d.client_id,
                d.canonical_hostname,
                BTRIM(value.serial) AS serial,
                LOWER(BTRIM(value.serial)) AS serial_key
            FROM operations.devices d
            JOIN operations.entity_observation_current observation
              ON observation.tenant_id = d.tenant_id
             AND observation.device_id = d.id
             AND observation.active
            CROSS JOIN LATERAL (
                VALUES
                    (observation.canonical_data ->> 'serial_number'),
                    (observation.canonical_data ->> 'service_tag')
            ) AS value(serial)
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND d.client_id IS NOT NULL
              AND COALESCE(value.serial, '') <> ''
        ),
        eligible AS (
            SELECT *
            FROM source_serials
            WHERE LENGTH(serial) >= 4
              AND LENGTH(REPLACE(
                    serial, LEFT(serial, 1), ''
                  )) > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM operations.identity_value_rejections rejected
                  WHERE rejected.value_kind = 'serial'
                    AND rejected.enabled
                    AND rejected.normalized_value = serial_key
              )
        ),
        collisions AS (
            SELECT
                tenant_id,
                serial_key,
                COUNT(DISTINCT id) AS device_count,
                COUNT(DISTINCT client_id) AS client_count,
                ARRAY_AGG(DISTINCT client_id::text ORDER BY client_id::text) AS client_ids,
                ARRAY_AGG(DISTINCT id::text ORDER BY id::text) AS device_ids
            FROM eligible
            GROUP BY tenant_id, serial_key
            HAVING COUNT(DISTINCT client_id) > 1
        )
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, subject_layer,
            subject_layer_entity_id, finding_details, condition_key,
            severity, confidence, status, first_seen_at, last_seen_at,
            last_detected_at
        )
        SELECT
            gen_random_uuid(), 1, e.tenant_id, %s, e.client_id,
            'device', e.id, '', NULL,
            jsonb_build_object(
                'serial', e.serial,
                'device_count', c.device_count,
                'client_count', c.client_count,
                'client_ids', c.client_ids,
                'device_ids', c.device_ids
            ),
            'cross_client_serial:' || e.id || ':' || md5(e.serial_key),
            'high', 'confirmed', 'open',
            NOW(), NOW(), NOW()
        FROM eligible e
        JOIN collisions c
          ON c.tenant_id = e.tenant_id
         AND c.serial_key = e.serial_key
        ON CONFLICT (tenant_id, condition_key)
        WHERE condition_key > '' AND status IN ('open', 'acknowledged')
        DO UPDATE SET
            last_seen_at = NOW(),
            last_detected_at = NOW(),
            finding_details = EXCLUDED.finding_details
        """,
        (TENANT_ID, finding_type_id),
    )
    return cur.rowcount


def _sync_device_attributes(cur) -> None:
    """Propagate the projector-owned device cache into the layer entities.

    Formerly this also derived `device_role`, `device_type`, `os_name` and
    `os_family` from observations. Per ADR-0012 an evidence producer does not
    write a source-derived value: those five cache columns are now written
    only by `ingest.device_cache_projector`, which reads the effective
    attribute contract.

    What remains reads `operations.devices` — the projector's output — and is
    therefore a cache-to-facet copy, not a second producer. It must run *after*
    the projector in the cycle, which is why `run_projection()` is invoked
    ahead of this in `resolve_all()`.
    """

    # ── Layer-entity propagation (ADR-0005 slice 2) ───────────────────
    # Keep the open-window Asset.form_factor in sync with the flat
    # Device.device_type cache. Same criterion — an evaluator-visible
    # form-factor change is a first-class layer event.
    cur.execute(
        """
        UPDATE operations.assets a
        SET form_factor = d.device_type,
            last_seen_at = GREATEST(a.last_seen_at, d.updated_at),
            updated_at = NOW()
        FROM operations.devices d
        WHERE a.tenant_id = %s
          AND a.tenant_id = d.tenant_id
          AND a.device_id = d.id
          AND a.effective_to IS NULL
          AND a.asset_type = 'endpoint_hardware'
          AND a.form_factor IS DISTINCT FROM d.device_type
        """,
        (TENANT_ID,),
    )
    if cur.rowcount:
        log.info(
            "resolver: layer sync set assets.form_factor on %d rows",
            cur.rowcount,
        )

    # Open OSInstance for devices that now have an os_name but never
    # got one at promotion time (typical for LMI-first promotions where
    # Ninja arrives with the OS later). Idempotent.
    cur.execute(
        """
        INSERT INTO operations.os_instances (
            id, tenant_id, version, device_id, os_name, os_family,
            os_group, os_version, install_identifier, patch_state,
            config_state, effective_from, effective_to,
            first_seen_at, last_seen_at,
            first_observed_source_id, last_observed_source_id,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(), d.tenant_id, 1, d.id,
            COALESCE(d.os_name, ''), COALESCE(d.os_family, ''),
            COALESCE(d.os_group, 'Unknown'),
            '', '', '{}'::jsonb, '{}'::jsonb,
            COALESCE(d.updated_at, NOW()), NULL,
            COALESCE(d.updated_at, NOW()), COALESCE(d.updated_at, NOW()),
            NULL, NULL, NOW(), NOW()
        FROM operations.devices d
        WHERE d.tenant_id = %s
          AND d.deleted_at IS NULL
          AND (
              COALESCE(d.os_name, '') <> ''
              OR d.device_type IN ('physical', 'vm')
          )
          AND NOT EXISTS (
              SELECT 1 FROM operations.os_instances o
              WHERE o.tenant_id = d.tenant_id
                AND o.device_id = d.id
                AND o.effective_to IS NULL
          )
        ON CONFLICT (tenant_id, device_id)
        WHERE effective_to IS NULL
        DO NOTHING
        """,
        (TENANT_ID,),
    )
    if cur.rowcount:
        log.info(
            "resolver: layer sync opened %d os_instances rows",
            cur.rowcount,
        )

    # Propagate os_name / os_family / os_group updates on the current
    # OSInstance window when the Device cache changed.
    cur.execute(
        """
        UPDATE operations.os_instances o
        SET os_name = d.os_name,
            os_family = d.os_family,
            os_group = COALESCE(d.os_group, 'Unknown'),
            last_seen_at = GREATEST(o.last_seen_at, d.updated_at),
            updated_at = NOW()
        FROM operations.devices d
        WHERE o.tenant_id = %s
          AND o.tenant_id = d.tenant_id
          AND o.device_id = d.id
          AND o.effective_to IS NULL
          AND (
              o.os_name IS DISTINCT FROM d.os_name
              OR o.os_family IS DISTINCT FROM d.os_family
              OR o.os_group IS DISTINCT FROM COALESCE(d.os_group, 'Unknown')
          )
        """,
        (TENANT_ID,),
    )
    if cur.rowcount:
        log.info(
            "resolver: layer sync updated %d os_instances rows",
            cur.rowcount,
        )

    # AgentInstance: open one row per (Device, Agent product) for any
    # agent-nature observation attached to a Device that doesn't yet
    # have an open window for that product. Non-agent observations
    # (vm.guest, vm.host, network.device) never open AgentInstance —
    # `entity_type LIKE 'agent.%'` gates the write. `platform` values
    # are canonicalized upstream to match `operations.agents.name`.
    cur.execute(
        """
        INSERT INTO operations.agent_instances (
            id, tenant_id, version, device_id, agent_id,
            install_token, agent_version, coverage_state,
            effective_from, effective_to,
            first_seen_at, last_seen_at,
            first_observed_source_id, last_observed_source_id,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(), sub.tenant_id, 1,
            sub.device_id, sub.agent_id,
            '', '', '{}'::jsonb,
            sub.first_at, NULL,
            sub.first_at, sub.last_at,
            NULL, NULL, NOW(), NOW()
        FROM (
            SELECT eo.tenant_id, eo.device_id, ag.id AS agent_id,
                   MIN(eo.effective_from) AS first_at,
                   MAX(COALESCE(eo.effective_to, eo.effective_from)) AS last_at
            FROM operations.entity_observation_history eo
            JOIN operations.agents ag ON ag.name = eo.platform
            WHERE eo.tenant_id = %s
              AND eo.device_id IS NOT NULL
              AND eo.entity_type LIKE 'agent.%%'
            GROUP BY eo.tenant_id, eo.device_id, ag.id
        ) sub
        WHERE NOT EXISTS (
            SELECT 1 FROM operations.agent_instances ai
            WHERE ai.tenant_id = sub.tenant_id
              AND ai.device_id = sub.device_id
              AND ai.agent_id = sub.agent_id
              AND ai.effective_to IS NULL
        )
        ON CONFLICT (tenant_id, device_id, agent_id)
        WHERE effective_to IS NULL
        DO NOTHING
        """,
        (TENANT_ID,),
    )
    if cur.rowcount:
        log.info(
            "resolver: layer sync opened %d agent_instances rows",
            cur.rowcount,
        )

    # ── Data-quality Findings (nothing hidden or silently ignored) ─────
    # Emit standard operations.findings rows for the three silent
    # filters that used to be visible only on the retired identity
    # admin page or (worse) only in logs. Idempotent via condition_key.

    ft_placeholder = _load_finding_type_id(cur, "placeholder_serial")
    ft_shared      = _load_finding_type_id(cur, "shared_serial")
    ft_cross_client_serial = _load_finding_type_id(cur, "cross_client_serial")
    ft_unmatched   = _load_finding_type_id(cur, "unmatched_source_group")
    ft_placeholder_mac = _load_finding_type_id(cur, "placeholder_mac")

    # placeholder_serial — devices whose canonical_serial is rejected by the
    # data-backed explicit-value registry or structural serial checks.
    # Devices with an empty serial are excluded: an absent value is not a
    # data-quality finding.
    if ft_placeholder is not None:
        cur.execute(
            """
            INSERT INTO operations.findings (
                id, version, tenant_id, finding_type_id, client_id,
                subject_type, subject_id, subject_layer,
                subject_layer_entity_id, finding_details, condition_key,
                severity, confidence, status, first_seen_at, last_seen_at,
                last_detected_at
            )
            SELECT
                gen_random_uuid(), 1, d.tenant_id, %s, d.client_id,
                'device', d.id, '', NULL,
                jsonb_build_object(
                    'hostname', d.canonical_hostname,
                    'serial',   d.canonical_serial
                ),
                'placeholder_serial:' || d.id,
                'high', 'confirmed', 'open',
                NOW(), NOW(), NOW()
            FROM operations.devices d
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND COALESCE(d.canonical_serial, '') <> ''
              AND (
                  EXISTS (
                      SELECT 1
                      FROM operations.identity_value_rejections rejected
                      WHERE rejected.value_kind = 'serial'
                        AND rejected.enabled
                        AND rejected.normalized_value = LOWER(BTRIM(d.canonical_serial))
                  )
                  OR LENGTH(BTRIM(d.canonical_serial)) < 4
                  OR LENGTH(REPLACE(
                      BTRIM(d.canonical_serial), LEFT(BTRIM(d.canonical_serial), 1), ''
                  )) = 0
              )
            ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
            DO UPDATE SET
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details
            """,
            (ft_placeholder, TENANT_ID),
        )
        if cur.rowcount:
            log.info(
                "resolver: data-quality upserted %d placeholder_serial findings",
                cur.rowcount,
            )

    # shared_serial — one finding per (client, serial) where 2+ devices
    # share the value. subject_id points to the alphabetically-first
    # device_id; finding_details lists all sharers.
    if ft_shared is not None:
        shared_serial_count = _upsert_shared_serial_findings(cur, ft_shared)
        if shared_serial_count:
            log.info(
                "resolver: data-quality upserted %d shared_serial findings",
                shared_serial_count,
            )

    if ft_cross_client_serial is not None:
        cross_client_serial_count = _upsert_cross_client_serial_findings(
            cur, ft_cross_client_serial
        )
        if cross_client_serial_count:
            log.info(
                "resolver: identity review upserted %d cross_client_serial findings",
                cross_client_serial_count,
            )

    # unmatched_source_group — one finding per pending row in
    # operations.unmatched_source_groups. finding_class is 'admin'
    # (subject_type='source_binding' would be closest but the
    # unmatched group isn't a binding; use 'source_binding' subject
    # with source_id in details).
    if ft_unmatched is not None:
        cur.execute(
            """
            INSERT INTO operations.findings (
                id, version, tenant_id, finding_type_id, client_id,
                subject_type, subject_id, subject_layer,
                subject_layer_entity_id, finding_details, condition_key,
                severity, confidence, status, first_seen_at, last_seen_at,
                last_detected_at
            )
            SELECT
                gen_random_uuid(), 1, u.tenant_id, %s, NULL,
                'source_binding', u.id, '', NULL,
                jsonb_build_object(
                    'source_id',     u.source_id,
                    'external_id',   u.external_id,
                    'external_name', u.external_name,
                    'device_count',  u.device_count,
                    'first_seen_at', u.first_seen_at
                ),
                'unmatched_source_group:' || u.source_id || ':' || u.external_id,
                'medium', 'confirmed', 'open',
                u.first_seen_at, u.last_seen_at, NOW()
            FROM operations.unmatched_source_groups u
            WHERE u.tenant_id = %s AND u.status = 'pending'
            ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
            DO UPDATE SET
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details
            """,
            (ft_unmatched, TENANT_ID),
        )
        if cur.rowcount:
            log.info(
                "resolver: data-quality upserted %d unmatched_source_group findings",
                cur.rowcount,
            )

    # placeholder_mac — devices whose observations contain any junk
    # MAC (all-zero, all-FF, VirtualBox default NAT). Correctness gate
    # in normalize._JUNK_MACS silently ignores them for identity
    # correlation; here we surface the affected devices. Bounded to
    # the last 30 days of observations to keep the CROSS JOIN LATERAL
    # scan cheap.
    if ft_placeholder_mac is not None:
        cur.execute(
            """
            INSERT INTO operations.findings (
                id, version, tenant_id, finding_type_id, client_id,
                subject_type, subject_id, subject_layer,
                subject_layer_entity_id, finding_details, condition_key,
                severity, confidence, status, first_seen_at, last_seen_at,
                last_detected_at
            )
            SELECT
                gen_random_uuid(), 1, sub.tenant_id, %s, d.client_id,
                'device', sub.device_id, '', NULL,
                jsonb_build_object(
                    'hostname',  d.canonical_hostname,
                    'junk_macs', sub.junk_macs
                ),
                'placeholder_mac:' || sub.device_id,
                'medium', 'confirmed', 'open',
                NOW(), NOW(), NOW()
            FROM (
                SELECT
                    eo.tenant_id,
                    eo.device_id,
                    ARRAY_AGG(DISTINCT LOWER(mac_val)) AS junk_macs
                FROM operations.entity_observation_current eo
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    COALESCE(eo.canonical_data->'macs', '[]'::jsonb)
                ) AS mac_val
                WHERE eo.tenant_id = %s
                  AND eo.device_id IS NOT NULL
                  AND eo.active = TRUE
                  AND eo.observed_at > NOW() - INTERVAL '30 days'
                  AND LOWER(mac_val) IN (
                      '00:00:00:00:00:00',
                      'ff:ff:ff:ff:ff:ff',
                      '02:00:4c:4f:4f:50'
                  )
                GROUP BY eo.tenant_id, eo.device_id
            ) sub
            JOIN operations.devices d
              ON d.id = sub.device_id AND d.tenant_id = sub.tenant_id
            WHERE d.deleted_at IS NULL
            ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
            DO UPDATE SET
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details
            """,
            (ft_placeholder_mac, TENANT_ID),
        )
        if cur.rowcount:
            log.info(
                "resolver: data-quality upserted %d placeholder_mac findings",
                cur.rowcount,
            )


def _infer_form_factor(entries: list[tuple]) -> str:
    """Infer Asset form factor from a group of source observations.

    Per ADR-0005: `form_factor='unknown'` is a legitimate value; positive
    evidence is required to leave it. Agent presence is *not* evidence
    of form factor — an `agent.*` observation says "an OS is being
    managed," not "the hardware is physical." Only explicit
    asset-nature signals (network.device / vm.host / vm.guest entity
    types, or matching node_class markers, or an is_vm flag) upgrade
    form factor away from unknown.
    """
    values = [e[5] or {} for e in entries]
    entity_types = {e[1] for e in entries}
    # node_class markers come from operations.node_class_mappings (0119)
    # rather than inline prefix/suffix tests. `form_factor_for_node_class`
    # returns None for every agent.* class, so agent presence still cannot
    # upgrade form factor.
    node_class_factors = {
        form_factor_for_node_class(cd.get("node_class")) for cd in values
    } - {None}

    if "network.device" in entity_types or "network-device" in node_class_factors:
        return "network-device"
    if "vm.host" in entity_types or "hypervisor-host" in node_class_factors:
        return "hypervisor-host"
    if (
        "vm.guest" in entity_types
        or "vm" in node_class_factors
        or any(bool(cd.get("is_vm")) for cd in values)
    ):
        return "vm"
    # No asset-nature evidence — form factor stays unknown regardless of
    # any agent.* observations. See ADR-0005.
    return "unknown"


def _write_layer_entities_for_new_device(
    cur,
    device_id: uuid.UUID,
    form_factor: str,
    serial: str,
    vm_uuid: str,
    os_name: str,
    os_fam: str,
    os_group: str,
    first_seen,
    last_seen,
    entries: list[tuple] | None = None,
    agent_ids: dict[str, int] | None = None,
) -> None:
    """Open the initial Asset, OSInstance, and AgentInstance rows for
    a freshly-promoted Device.

    Per ADR-0005 slice 2. Kept as a single helper so both Device
    creation sites (`_promote_unmatched_clusters` primary path and
    `_promote_entry_groups` duplicate-group path) stay in sync.

    - `assets` row is always opened (asset_type='endpoint_hardware',
      effective_to=NULL). form_factor may be 'unknown' — that's a
      legitimate state per the rule.
    - `os_instances` row is opened only when os_name is present or
      form factor is physical / vm (same criterion as the 0051
      backfill). Pure network-device / hypervisor-host devices don't
      get an OSInstance row.
    - `agent_instances` rows are opened one per (Device, Agent
      product) observed in `entries` with `entity_type LIKE 'agent.%'`.
      Non-agent observations (vm.guest, vm.host, network.device)
      never open an AgentInstance. `agent_ids` maps platform name to
      Agent PK; when None the AgentInstance step is skipped.

    Uses `ON CONFLICT DO NOTHING` on the partial unique indexes so
    concurrent resolver drains never duplicate open windows.
    """
    cur.execute(
        """
        INSERT INTO operations.assets (
            id, tenant_id, version, asset_type, device_id, form_factor,
            serial, vm_uuid, chassis, virtualization, effective_from,
            effective_to, first_seen_at, last_seen_at,
            first_observed_source_id, last_observed_source_id,
            created_at, updated_at
        )
        VALUES (
            gen_random_uuid(), %s, 1, 'endpoint_hardware', %s, %s,
            %s, %s, '', '{}'::jsonb, COALESCE(%s, NOW()), NULL,
            COALESCE(%s, NOW()), COALESCE(%s, NOW()),
            NULL, NULL, NOW(), NOW()
        )
        ON CONFLICT (tenant_id, device_id)
        WHERE effective_to IS NULL
          AND device_id IS NOT NULL
          AND asset_type = 'endpoint_hardware'
        DO NOTHING
        """,
        (
            TENANT_ID, device_id, form_factor,
            serial or "", vm_uuid or "",
            first_seen, first_seen, last_seen,
        ),
    )
    if os_name or form_factor in ("physical", "vm"):
        cur.execute(
            """
            INSERT INTO operations.os_instances (
                id, tenant_id, version, device_id, os_name, os_family,
                os_group, os_version, install_identifier, patch_state,
                config_state, effective_from, effective_to,
                first_seen_at, last_seen_at,
                first_observed_source_id, last_observed_source_id,
                created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), %s, 1, %s, %s, %s,
                %s, '', '', '{}'::jsonb,
                '{}'::jsonb, COALESCE(%s, NOW()), NULL,
                COALESCE(%s, NOW()), COALESCE(%s, NOW()),
                NULL, NULL, NOW(), NOW()
            )
            ON CONFLICT (tenant_id, device_id)
            WHERE effective_to IS NULL
            DO NOTHING
            """,
            (
                TENANT_ID, device_id, os_name or "", os_fam or "",
                os_group or "Unknown", first_seen, first_seen, last_seen,
            ),
        )
    if entries and agent_ids:
        seen_agents: set[int] = set()
        for entry in entries:
            platform, entity_type, _entity_key, e_first, e_last, e_cd = entry
            if not entity_type or not entity_type.startswith("agent."):
                continue
            agent_id = agent_ids.get(platform)
            if agent_id is None or agent_id in seen_agents:
                continue
            seen_agents.add(agent_id)
            cd = e_cd or {}
            install_token = str(cd.get("install_token") or "")[:240]
            agent_ver = str(cd.get("agent_version") or cd.get("version") or "")[:80]
            cur.execute(
                """
                INSERT INTO operations.agent_instances (
                    id, tenant_id, version, device_id, agent_id,
                    install_token, agent_version, coverage_state,
                    effective_from, effective_to,
                    first_seen_at, last_seen_at,
                    first_observed_source_id, last_observed_source_id,
                    created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), %s, 1, %s, %s,
                    %s, %s, '{}'::jsonb,
                    COALESCE(%s, NOW()), NULL,
                    COALESCE(%s, NOW()), COALESCE(%s, NOW()),
                    NULL, NULL, NOW(), NOW()
                )
                ON CONFLICT (tenant_id, device_id, agent_id)
                WHERE effective_to IS NULL
                DO NOTHING
                """,
                (
                    TENANT_ID, device_id, agent_id,
                    install_token, agent_ver,
                    e_first, e_first, e_last,
                ),
            )
