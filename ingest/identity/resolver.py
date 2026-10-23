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

import hashlib
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Json

from ingest import db, device_cache_projector
from ingest.conditions import record_assessment
from ingest.identity import findings as identity_findings
from ingest.identity import identity_entity_types
from ingest.identity.naming import write_computer_names
from ingest.identity.matching import client_record_names, invalidate_client_names
from ingest.identity.matching import (
    IdentityMatchPolicy,
    load_identity_match_policies,
    loose_name,
    record_name_short,
    resolve_device_by_policy,
    resolve_match,
)
from ingest.normalize import (
    form_factor_for_node_class,
    is_macos_name,
    is_usable_serial,
    load_identity_value_rejections,
    os_family,
)
from shared.conditions.contracts import Condition, EvaluationCoverage, Participant

log = logging.getLogger(__name__)

TENANT_ID = 1
_MIN_IDENTITY_CANDIDATES = 2


def _identity_conflict_key(client_id: uuid.UUID, device_ids) -> str:
    """Key for one group of Computers, built from their IDs (ADR-0034 section 8).

    Matches the SQL key of `_CONFLICT_KEY`: IDs sorted bytewise (COLLATE C).
    """
    joined = ",".join(sorted(str(device_id) for device_id in device_ids))
    digest = hashlib.md5(f"{client_id}:{joined}".encode()).hexdigest()
    return f"identity_conflict:{digest}"


def drain_resolution(batch_size: int = 200, *, refresh_current: bool = True) -> int:
    """Resolve up to batch_size unresolved entity_observations.

    Returns the count of observations that were resolved (device_id set).
    Refreshes device_agent_presence_current if any observations were resolved,
    unless the caller will immediately run the full derived-state coordinator.
    """
    resolved_count = 0
    touched: set = set()
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
        load_identity_value_rejections(cur)
        identity_policies = load_identity_match_policies(cur, TENANT_ID)
        refresh_roaming_records(cur)

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

        for (
            obs_id,
            entity_type,
            entity_key,
            platform,
            client_id,
            observed_at,
            canonical_data,
        ) in rows:
            cd = canonical_data or {}

            serial = cd.get("serial_number")
            vm_uuid = cd.get("vm_uuid")
            hostname_raw = cd.get("hostname") or cd.get("guest_name")
            # The one SQL normalization (ADR-0034 section 1).
            norm = record_name_short(cur, platform, entity_type, hostname_raw, cd.get("domain")) or None
            device_id = resolve_device_by_policy(
                cur,
                tenant_id=TENANT_ID,
                source_name=platform,
                external_id=entity_key,
                entity_type=entity_type,
                serial=serial,
                vm_uuid=vm_uuid,
                hostname=norm,
                macs=cd.get("macs") or [],
                client_id=client_id,
                policies=identity_policies,
                is_online=cd.get("is_online"),
            )
            if device_id is not None:
                _attach_observation(cur, obs_id, device_id)
                touched.add(device_id)
                resolved_count += 1
                log.debug(
                    "resolver: policy match %s → device %s", entity_key, device_id
                )
                continue
            if norm:
                _maybe_create_candidate(
                    cur,
                    obs_id,
                    entity_key,
                    norm,
                    client_id,
                    identity_conflict_ft_id=identity_conflict_ft_id,
                )
        write_computer_names(cur, touched)

    log.info(
        "resolver: resolved %d / %d observations",
        resolved_count,
        len(rows) if rows else 0,
    )
    _add_count("observations_resolved", resolved_count)
    _add_count("observations_examined", len(rows) if rows else 0)

    promoted_count = 0
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            promoted_count = _promote_unmatched_clusters(cur, identity_policies)
    except Exception:
        log.exception("resolver: device promotion failed — continuing")

    merged_count = 0
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            merged_count = merge_proven_splits(cur)
    except Exception:
        log.exception("resolver: automatic merge of proven splits failed — continuing")
    _add_count("computers_promoted", promoted_count)
    _add_count("computers_merged", merged_count)
    promoted_count += merged_count

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

    reconcile_computer_names()
    run_shadow_naming()

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
            log.info(
                "resolver: refreshed device_agent_presence_current after %d resolutions",
                resolved_count,
            )
        except Exception:
            log.exception(
                "resolver: device_agent_presence_current refresh failed — continuing"
            )
        else:
            try:
                with db.transaction() as cur:
                    cur.execute("SELECT operations.refresh_device_session_current()")
                log.info("resolver: refreshed device_session_current")
            except Exception:
                log.exception(
                    "resolver: device_session_current refresh failed — continuing"
                )

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


def _entries_same_machine(cd_a: dict, cd_b: dict) -> bool:
    """Hard proof two platform records describe one machine: equal usable
    serial or equal vm_uuid.

    A shared MAC address is not proof (ADR-0032): of 310 same-source pairs
    sharing a MAC that serial could check, 4 were different machines
    (Hyper-V virtual adapters, docks), and MAC alone decided only 2.
    """
    sa, sb = cd_a.get("serial_number"), cd_b.get("serial_number")
    if (
        is_usable_serial(sa)
        and is_usable_serial(sb)
        and sa.strip().lower() == sb.strip().lower()
    ):
        return True
    ua, ub = cd_a.get("vm_uuid"), cd_b.get("vm_uuid")
    return bool(ua and ub and str(ua).lower() == str(ub).lower())


def _group_same_machine(stream_entries: list[tuple]) -> list[list[tuple]]:
    """Partition one stream's entries into machine groups.

    Entries proven to be the same machine (serial / vm_uuid) share a group —
    duplicate agents on one box. Unproven entries stay singletons and are
    matched one by one (ADR-0032), so a same-name record joins its machine
    unless a hard conflict separates it. Groups and entries are ordered
    newest-first.
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
            "UPDATE operations.entity_observation_current SET device_id = %s "
            "WHERE observation_id = %s RETURNING client_id",
            (device_id, obs_id),
        )
        row = cur.fetchone()
        invalidate_client_names(row[0] if row else None)


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
    # From the client's cached record names: this runs once per unresolved
    # record. Current, active identity records only.
    types = identity_entity_types(cur)
    rows = [
        (device_id,)
        for device_id in sorted(
            {
                device_id
                for device_id, _lifecycle, name_short, _key, is_current, _platform, _entity_key,
                entity_type in client_record_names(cur, TENANT_ID, client_id)
                if is_current and entity_type in types and name_short == norm
            },
            key=str,
        )[:5]
    ]
    if len(rows) < _MIN_IDENTITY_CANDIDATES:
        return
    candidate_ids = [row[0] for row in rows]
    device_id_a = candidate_ids[0]

    # Standard operator-visible surface — the ADR's mandated path.
    # condition_key deduplicates repeat observations of the same
    # hostname collision within a tenant.
    if identity_conflict_ft_id is not None and client_id is not None:
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
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            DO UPDATE SET
                client_id = EXCLUDED.client_id,
                subject_id = EXCLUDED.subject_id,
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details,
                severity = EXCLUDED.severity,
                confidence = EXCLUDED.confidence
            """,
            (
                TENANT_ID,
                identity_conflict_ft_id,
                client_id,
                device_id_a,
                Json(
                    {
                        "hostname": norm,
                        "candidate_count": len(rows),
                        "candidate_device_ids": [str(x) for x in candidate_ids],
                        "trigger_observation_id": str(obs_id),
                    }
                ),
                _identity_conflict_key(client_id, candidate_ids),
            ),
        )


# The names a Computer's current identity records report (ADR-0034 section 4),
# normalized by the one SQL function; roaming records carry no name. Runs in
# the session tenant.
_DEVICE_NAMES = """
device_names AS (
    SELECT DISTINCT eo.device_id, f.name_short AS name
      FROM operations.entity_observation_current eo
     CROSS JOIN LATERAL operations.record_name_forms(
          eo.platform, eo.entity_type,
          coalesce(nullif(eo.canonical_data ->> 'hostname', ''), eo.canonical_data ->> 'guest_name'),
          eo.canonical_data ->> 'domain') f
     WHERE eo.tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint
       AND eo.active AND eo.device_id IS NOT NULL
       AND eo.entity_key NOT LIKE 'device-health:%%'
       AND eo.entity_type IN (SELECT name FROM operations.entity_types WHERE is_identity_signal)
       AND f.name_short IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = eo.tenant_id
                          AND rr.source_instance_id = eo.source_instance_id
                          AND rr.external_id = eo.external_id)
)"""

# Keyed by the Computers involved, never by a name (ADR-0034 section 8).
_CONFLICT_KEY = (
    "'identity_conflict:' || md5({client}::text || ':' || "
    "string_agg({id}::text, ',' ORDER BY {id}::text COLLATE \"C\"))"
)

_MERGE_CANDIDATE_UPSERT = (
    "WITH "
    + _DEVICE_NAMES
    + """, collisions AS (
    SELECT d.client_id,
           dn.name AS canonical_hostname,
           COUNT(*) AS member_count,
           """
    + _CONFLICT_KEY.format(client="d.client_id", id="d.id")
    + """ AS canonical_key,
           JSONB_AGG(
               JSONB_BUILD_OBJECT(
                   'device_id', d.id,
                   'hostname', dn.name,
                   'serial', COALESCE(d.canonical_serial, ''),
                   'vm_uuid', COALESCE(d.canonical_vm_uuid, ''),
                   'device_type', d.device_type,
                   'device_role', d.device_role,
                   'os_name', COALESCE(d.os_name, ''),
                   'created_at', d.created_at
               ) ORDER BY d.created_at
           ) AS members
    FROM operations.devices d
    JOIN device_names dn ON dn.device_id = d.id
    WHERE d.tenant_id = %s AND d.deleted_at IS NULL AND d.client_id IS NOT NULL
    GROUP BY d.client_id, dn.name
    HAVING COUNT(*) >= %s
)
INSERT INTO operations.merge_candidates
    (id, version, tenant_id, client_id, entity_type, canonical_key,
     member_snapshots, member_observation_ids, match_reason, confidence, status)
SELECT gen_random_uuid(), 1, %s, c.client_id, 'device', c.canonical_key,
       c.members, NULL,
       FORMAT('%%s devices share the reported name %%s within one client',
              c.member_count, c.canonical_hostname),
       0.9000, 'open'
FROM collisions c
ON CONFLICT (tenant_id, canonical_key) WHERE status = 'open'
DO UPDATE SET
    member_snapshots = EXCLUDED.member_snapshots,
    match_reason = EXCLUDED.match_reason,
    client_id = EXCLUDED.client_id
"""
)


_MERGE_CANDIDATE_CLOSE = (
    "WITH "
    + _DEVICE_NAMES
    + """, current_keys AS (
    SELECT """
    + _CONFLICT_KEY.format(client="d.client_id", id="d.id")
    + """ AS canonical_key
      FROM operations.devices d
      JOIN device_names dn ON dn.device_id = d.id
     WHERE d.deleted_at IS NULL AND d.client_id IS NOT NULL
     GROUP BY d.client_id, dn.name
    HAVING COUNT(*) >= %s
)
UPDATE operations.merge_candidates mc
SET status = 'merged'
WHERE mc.tenant_id = %s
  AND mc.status = 'open'
  AND mc.entity_type = 'device'
  AND NOT EXISTS (SELECT 1 FROM current_keys k WHERE k.canonical_key = mc.canonical_key)
"""
)


def project_merge_candidates(cur) -> dict[str, int]:
    """Reconcile `operations.merge_candidates` against current collisions.

    A reconciling pass, not a detection side effect: a collision is a property
    of current device state, so it is projected from that. Computers collide
    when their current identity records report one name (ADR-0034); the key
    is built from the Computers, so it matches the identity_conflict finding.
    Proposals whose collision no longer holds are closed.
    """
    cur.execute(
        _MERGE_CANDIDATE_UPSERT, (TENANT_ID, _MIN_IDENTITY_CANDIDATES, TENANT_ID)
    )
    upserted = cur.rowcount or 0
    cur.execute(_MERGE_CANDIDATE_CLOSE, (_MIN_IDENTITY_CANDIDATES, TENANT_ID))
    closed = cur.rowcount or 0
    strong = _project_strong_identity_candidates(cur)
    findings = _project_identity_conflict_findings(cur)
    return {
        "upserted": upserted,
        "closed": closed,
        "strong_upserted": strong["upserted"],
        "strong_closed": strong["closed"],
        "findings_upserted": findings["upserted"],
        "findings_closed": findings["closed"],
    }


_IDENTITY_CONFLICT_COLLISIONS = (
    "WITH "
    + _DEVICE_NAMES
    + """, device_evidence AS (
    SELECT d.id,
           d.client_id,
           dn.name AS canonical_hostname,
           d.canonical_serial,
           d.canonical_vm_uuid,
           d.device_type,
           d.device_role,
           d.os_name,
           d.created_at,
           CASE WHEN LENGTH(BTRIM(d.canonical_serial)) >= 4
                 AND LENGTH(REPLACE(LOWER(BTRIM(d.canonical_serial)),
                                    LEFT(LOWER(BTRIM(d.canonical_serial)), 1), '')) > 0
                 AND NOT EXISTS (
                     SELECT 1 FROM operations.identity_value_rejections rejected
                      WHERE rejected.value_kind = 'serial' AND rejected.enabled
                        AND rejected.normalized_value = LOWER(BTRIM(d.canonical_serial)))
                THEN LOWER(BTRIM(d.canonical_serial)) END AS usable_serial,
           ARRAY_REMOVE(ARRAY_AGG(DISTINCT LOWER(mac.value)), NULL) AS macs
      FROM operations.devices d
      JOIN device_names dn ON dn.device_id = d.id
      LEFT JOIN operations.entity_observation_current o
        ON o.tenant_id = d.tenant_id
       AND o.device_id = d.id
       AND o.active
      LEFT JOIN LATERAL jsonb_array_elements_text(
          COALESCE(o.canonical_data -> 'macs', '[]'::jsonb)
      ) AS mac(value) ON TRUE
     WHERE d.tenant_id = %s
       AND d.deleted_at IS NULL
       AND d.client_id IS NOT NULL
     GROUP BY d.id, d.client_id, dn.name, d.canonical_serial,
              d.canonical_vm_uuid, d.device_type, d.device_role, d.os_name,
              d.created_at
), separated AS (
    -- Computers an operator confirmed are different machines (migration 0309).
    SELECT dec.device_id AS a, k.value::uuid AS b
      FROM operations.device_operator_decisions dec,
           jsonb_array_elements_text(dec.value) k
     WHERE dec.dimension = 'identity_separate'
), undecided AS (
    -- Groups with at least one pair no operator has confirmed separate.
    SELECT a.client_id, a.canonical_hostname
      FROM device_evidence a
      JOIN device_evidence b
        ON b.client_id = a.client_id AND b.canonical_hostname = a.canonical_hostname
       AND a.id < b.id
     WHERE NOT EXISTS (SELECT 1 FROM separated s
                        WHERE (s.a = a.id AND s.b = b.id) OR (s.a = b.id AND s.b = a.id))
     GROUP BY a.client_id, a.canonical_hostname
), collision_groups AS (
    SELECT client_id,
           canonical_hostname,
           """
    + _CONFLICT_KEY.format(client="client_id", id="id")
    + """ AS condition_key,
           MIN(id::text)::uuid AS subject_id,
           COUNT(*) AS candidate_count,
           JSONB_AGG(id::text ORDER BY created_at, id) AS candidate_device_ids,
           JSONB_AGG(
               JSONB_BUILD_OBJECT(
                   'device_id', id,
                   'hostname', canonical_hostname,
                   'serial', COALESCE(canonical_serial, ''),
                   'vm_uuid', COALESCE(canonical_vm_uuid, ''),
                   'device_type', device_type,
                   'device_role', device_role,
                   'os_name', COALESCE(os_name, '')
               ) ORDER BY created_at, id
           ) AS candidate_devices,
           COUNT(NULLIF(canonical_serial, '')) >= 2
             AND COUNT(DISTINCT NULLIF(LOWER(canonical_serial), '')) = 1 AS shared_serial,
           COUNT(NULLIF(canonical_vm_uuid, '')) >= 2
             AND COUNT(DISTINCT NULLIF(LOWER(canonical_vm_uuid), '')) = 1 AS shared_vm_uuid
      FROM device_evidence
     WHERE (client_id, canonical_hostname) IN (SELECT client_id, canonical_hostname FROM undecided)
     GROUP BY client_id, canonical_hostname
    -- ADR-0032: same name, proven different machines (two usable serials).
    -- Name-only groups are duplicate_device_records (ingest.identity.findings).
    HAVING COUNT(*) >= %s AND COUNT(DISTINCT usable_serial) >= 2
), shared_mac AS (
    SELECT a.client_id, a.canonical_hostname
      FROM device_evidence a
      JOIN device_evidence b
        ON b.client_id = a.client_id
       AND b.canonical_hostname = a.canonical_hostname
       AND b.id > a.id
       AND cardinality(a.macs) > 0
       AND cardinality(b.macs) > 0
       AND a.macs && b.macs
     GROUP BY a.client_id, a.canonical_hostname
), collisions AS (
    SELECT c.*,
           CASE
             WHEN c.shared_serial THEN 'same serial number'
             WHEN c.shared_vm_uuid THEN 'same VM UUID'
             WHEN sm.client_id IS NOT NULL THEN 'same MAC address'
             ELSE 'same normalized computer name'
           END AS match_signal,
           CASE
             WHEN c.shared_serial OR c.shared_vm_uuid OR sm.client_id IS NOT NULL
               THEN 'probable'
             ELSE 'possible'
           END AS confidence
      FROM collision_groups c
      LEFT JOIN shared_mac sm
        ON sm.client_id = c.client_id
       AND sm.canonical_hostname = c.canonical_hostname
)
"""
)


_IDENTITY_CONFLICT_FINDING_UPSERT = (
    _IDENTITY_CONFLICT_COLLISIONS
    + """
INSERT INTO operations.findings (
    id, version, tenant_id, finding_type_id, client_id,
    subject_type, subject_id, subject_layer, subject_layer_entity_id,
    finding_details, condition_key, severity, confidence, status,
    first_seen_at, last_seen_at, last_detected_at
)
SELECT gen_random_uuid(), 1, %s, %s, c.client_id,
       'device', c.subject_id, '', NULL,
       JSONB_BUILD_OBJECT(
           'hostname', c.canonical_hostname,
           'candidate_count', c.candidate_count,
           'candidate_device_ids', c.candidate_device_ids,
           'candidate_devices', c.candidate_devices,
           'match_signal', c.match_signal,
           'evidence_summary', c.match_signal
       ),
       c.condition_key,
       'medium', c.confidence, 'open', NOW(), NOW(), NOW()
  FROM collisions c
ON CONFLICT (tenant_id, condition_key)
WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
DO UPDATE SET
    client_id = EXCLUDED.client_id,
    subject_id = EXCLUDED.subject_id,
    finding_details = EXCLUDED.finding_details,
    severity = EXCLUDED.severity,
    confidence = EXCLUDED.confidence,
    last_seen_at = EXCLUDED.last_seen_at,
    last_detected_at = EXCLUDED.last_detected_at
"""
)


_IDENTITY_CONFLICT_FINDING_CLOSE = (
    _IDENTITY_CONFLICT_COLLISIONS
    + """
UPDATE operations.findings finding
   SET status = 'resolved', closed_at = NOW(), last_seen_at = NOW()
 WHERE finding.tenant_id = %s
   AND finding.finding_type_id = %s
   AND finding.status IN ('open', 'acknowledged')
   AND finding.condition_key LIKE 'identity_conflict:%%'
   AND NOT EXISTS (SELECT 1 FROM collisions c WHERE finding.condition_key = c.condition_key)
   /* CONDITION_ASSESSMENT_GUARD */
"""
)


def _project_identity_conflict_findings(cur) -> dict[str, int]:
    """Keep one current, client-scoped duplicate-Computer Finding per group.

    Candidate proposals remain internal derived data for compatibility, but
    operators work from Findings.  Name equality is evidence to review, not
    proof to combine; serial, VM UUID, or MAC evidence raises confidence only.
    """
    finding_type_id = _load_finding_type_id(cur, "identity_conflict")
    if finding_type_id is None:
        return {"upserted": 0, "closed": 0}
    cur.execute(
        _IDENTITY_CONFLICT_FINDING_UPSERT,
        (TENANT_ID, _MIN_IDENTITY_CANDIDATES, TENANT_ID, finding_type_id),
    )
    upserted = cur.rowcount or 0
    cur.execute("SELECT to_regclass('operations.condition_assessments')")
    has_assessments = cur.fetchone()[0] is not None
    if has_assessments:
        _record_identity_conflict_assessments(cur, finding_type_id)
    close_sql = _IDENTITY_CONFLICT_FINDING_CLOSE.replace(
        "/* CONDITION_ASSESSMENT_GUARD */",
        """
   AND EXISTS (
       SELECT 1
         FROM operations.condition_assessments assessment
        WHERE assessment.tenant_id = finding.tenant_id
          AND assessment.row_kind = 'entity'
          AND assessment.finding_id = finding.id
          AND (assessment.response ->> 'may_clear')::boolean IS TRUE
          AND assessment.policy_version = (
              SELECT version FROM operations.condition_policy_versions
              WHERE active ORDER BY version DESC LIMIT 1
          )
          AND assessment.assessed_at >= now() - (
              SELECT (policy->>'freshness_hours')::integer * interval '1 hour'
              FROM operations.condition_policy_versions
              WHERE active ORDER BY version DESC LIMIT 1
          )
   )
        """
        if has_assessments
        else "   AND FALSE\n",
    )
    cur.execute(
        close_sql,
        (TENANT_ID, _MIN_IDENTITY_CANDIDATES, TENANT_ID, finding_type_id),
    )
    closed = cur.rowcount or 0
    return {"upserted": upserted, "closed": closed}


def _record_identity_conflict_assessments(cur, finding_type_id: int) -> None:
    """Record eligible participant assessments for current identity groups."""
    now = _assessment_now(cur)
    cur.execute(
        """
        SELECT id, client_id, condition_key, status,
               finding_details -> 'candidate_device_ids'
        FROM operations.findings
        WHERE tenant_id = %s AND finding_type_id = %s
          AND status IN ('open', 'acknowledged', 'investigating')
        """,
        (TENANT_ID, finding_type_id),
    )
    for finding_id, client_id, condition_key, status, raw_candidates in cur.fetchall():
        candidates = raw_candidates if isinstance(raw_candidates, list) else []
        participants = tuple(
            Participant("device", candidate_id, "conflicting", TENANT_ID)
            for candidate in candidates
            if (candidate_id := _candidate_uuid(candidate)) is not None
        )
        if not participants:
            continue
        if client_id:
            participants += (Participant("client", str(client_id), "context", TENANT_ID),)
        condition = Condition(
            TENANT_ID,
            "entity",
            str(finding_id),
            "identity_conflict",
            condition_key,
            status,
            participants,
        )
        for participant in participants:
            if participant.kind != "device":
                continue
            record_assessment(
                cur,
                condition,
                (),
                # Groups are recomputed from every current Computer each run,
                # so a group that is absent is a measured negative: the
                # conflict may clear (ADR-0032; it never could before, which
                # kept 41 open and blocked their Computers' other findings).
                EvaluationCoverage(True, True, True, True),
                now=now,
                reevaluation_key=f"identity-resolver:{condition_key}",
                participant=participant,
            )


def _assessment_now(cur):
    cur.execute("SELECT CURRENT_TIMESTAMP")
    return cur.fetchone()[0]


def _candidate_uuid(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


_STRONG_IDENTITY_CANDIDATE_CTE = """
WITH policy AS (
    SELECT confidence, blocking_signal_keys
      FROM operations.identity_match_policies
     WHERE tenant_id = %s AND matcher = 'hostname_mac' AND enabled = TRUE
), device_evidence AS (
    SELECT d.id AS device_id,
           d.client_id,
           d.canonical_hostname,
           d.canonical_serial,
           d.canonical_vm_uuid,
           d.device_type,
           d.device_role,
           d.os_name,
           ARRAY_REMOVE(ARRAY_AGG(DISTINCT mac.value), NULL) AS macs,
           -- The names the records report, never the stored name (ADR-0034
           -- section 4); roaming records carry no name.
           ARRAY_REMOVE(ARRAY_AGG(DISTINCT CASE WHEN rr.external_id IS NULL THEN f.name_short END),
                        NULL) AS names,
           ARRAY_AGG(DISTINCT o.observation_id::text) AS observation_ids
      FROM operations.devices d
      JOIN operations.entity_observation_current o
        ON o.tenant_id = d.tenant_id
       AND o.device_id = d.id
       AND o.active
      LEFT JOIN operations.identity_roaming_records rr
        ON rr.tenant_id = o.tenant_id AND rr.source_instance_id = o.source_instance_id
       AND rr.external_id = o.external_id
     CROSS JOIN LATERAL operations.record_name_forms(
          o.platform, o.entity_type,
          coalesce(nullif(o.canonical_data ->> 'hostname', ''), o.canonical_data ->> 'guest_name'),
          o.canonical_data ->> 'domain') f
      LEFT JOIN LATERAL jsonb_array_elements_text(
          COALESCE(o.canonical_data -> 'macs', '[]'::jsonb)
      ) AS mac(value) ON TRUE
     WHERE d.tenant_id = %s
       AND d.deleted_at IS NULL
       AND d.client_id IS NOT NULL
       AND o.entity_type = ANY(%s)
     GROUP BY d.id, d.client_id, d.canonical_hostname, d.canonical_serial,
              d.canonical_vm_uuid, d.device_type, d.device_role, d.os_name
), strong_pairs AS (
    SELECT a.client_id,
           a.device_id AS device_a_id,
           b.device_id AS device_b_id,
           a.canonical_hostname,
           a.canonical_serial AS serial_a,
           b.canonical_serial AS serial_b,
           a.canonical_vm_uuid AS vm_uuid_a,
           b.canonical_vm_uuid AS vm_uuid_b,
           a.device_type AS device_type_a,
           b.device_type AS device_type_b,
           a.device_role AS device_role_a,
           b.device_role AS device_role_b,
           a.os_name AS os_name_a,
           b.os_name AS os_name_b,
           policy.confidence,
           a.observation_ids || b.observation_ids AS observation_ids,
           'identity_strong:' || md5(
               a.client_id::text || ':' || a.device_id::text || ':' || b.device_id::text
           ) AS canonical_key
      FROM device_evidence a
      JOIN device_evidence b
        ON b.client_id = a.client_id
       AND a.names && b.names
       AND a.device_id::text < b.device_id::text
       AND cardinality(a.macs) > 0
       AND cardinality(b.macs) > 0
       AND a.macs && b.macs
      JOIN policy ON TRUE
     WHERE NOT (policy.blocking_signal_keys @> '["vm_uuid"]'::jsonb)
        OR NULLIF(a.canonical_vm_uuid, '') IS NULL
        OR NULLIF(b.canonical_vm_uuid, '') IS NULL
        OR LOWER(a.canonical_vm_uuid) = LOWER(b.canonical_vm_uuid)
)
"""


_STRONG_MERGE_CANDIDATE_UPSERT = (
    _STRONG_IDENTITY_CANDIDATE_CTE
    + """
INSERT INTO operations.merge_candidates
    (id, version, tenant_id, client_id, entity_type, canonical_key,
     member_snapshots, member_observation_ids, match_reason, confidence, status)
SELECT gen_random_uuid(), 1, %s, pair.client_id, 'device', pair.canonical_key,
       jsonb_build_array(
           jsonb_build_object(
               'device_id', pair.device_a_id,
               'hostname', pair.canonical_hostname,
               'serial', COALESCE(pair.serial_a, ''),
               'vm_uuid', COALESCE(pair.vm_uuid_a, ''),
               'device_type', pair.device_type_a,
               'device_role', pair.device_role_a,
               'os_name', COALESCE(pair.os_name_a, '')
           ),
           jsonb_build_object(
               'device_id', pair.device_b_id,
               'hostname', pair.canonical_hostname,
               'serial', COALESCE(pair.serial_b, ''),
               'vm_uuid', COALESCE(pair.vm_uuid_b, ''),
               'device_type', pair.device_type_b,
               'device_role', pair.device_role_b,
               'os_name', COALESCE(pair.os_name_b, '')
           )
       ),
       to_jsonb(pair.observation_ids),
       'Strong identity: same client, normalized hostname, and a shared MAC address.',
       pair.confidence, 'open'
  FROM strong_pairs pair
ON CONFLICT (tenant_id, canonical_key) WHERE status = 'open'
DO UPDATE SET
    member_snapshots = EXCLUDED.member_snapshots,
    member_observation_ids = EXCLUDED.member_observation_ids,
    match_reason = EXCLUDED.match_reason,
    confidence = EXCLUDED.confidence,
    client_id = EXCLUDED.client_id
"""
)


_STRONG_MERGE_CANDIDATE_CLOSE = (
    _STRONG_IDENTITY_CANDIDATE_CTE
    + """
UPDATE operations.merge_candidates candidate
   SET status = 'merged'
 WHERE candidate.tenant_id = %s
   AND candidate.status = 'open'
   AND candidate.entity_type = 'device'
   AND candidate.canonical_key LIKE 'identity_strong:%%'
   AND NOT EXISTS (
       SELECT 1
         FROM strong_pairs pair
        WHERE pair.canonical_key = candidate.canonical_key
   )
"""
)


def _project_strong_identity_candidates(cur) -> dict[str, int]:
    """Propose, but never automatically merge, already split strong matches.

    Attachment is deliberately sticky: moving a source observation between
    two existing devices is a merge operation with findings and software
    consequences. This projection makes the strong proof visible in the
    existing review queue instead of treating it as permission to move data.
    """
    identity_types = sorted(identity_entity_types(cur))
    cur.execute(
        _STRONG_MERGE_CANDIDATE_UPSERT,
        (TENANT_ID, TENANT_ID, identity_types, TENANT_ID),
    )
    upserted = cur.rowcount or 0
    cur.execute(
        _STRONG_MERGE_CANDIDATE_CLOSE,
        (TENANT_ID, TENANT_ID, identity_types, TENANT_ID),
    )
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
        # norm is the record's strict SQL name form; its key is the loose form.
        loose = loose_name(norm)
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
                other
                for other in norms
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


def _promote_unmatched_clusters(
    cur, identity_policies: tuple[IdentityMatchPolicy, ...]
) -> int:
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
    touched: set = set()

    # (client_id, norm) → list of (platform, entity_type, entity_key, first, last, cd)
    clusters: dict[tuple, list[tuple]] = {}
    for (
        client_id,
        platform,
        entity_type,
        entity_key,
        first_seen,
        last_seen,
        raw_cd,
    ) in unresolved:
        cd = raw_cd or {}
        hostname = cd.get("hostname") or cd.get("guest_name")
        norm = record_name_short(cur, platform, entity_type, hostname, cd.get("domain"))
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
            touched.add(linked[0])
            invalidate_client_names(client_id)
            continue
        clusters.setdefault((client_id, norm), []).append(
            (platform, entity_type, entity_key, first_seen, last_seen, cd)
        )

    clusters = _collapse_mac_variants(clusters)
    clusters = _collapse_prefix_variants(clusters)

    promoted = 0
    for (client_id, norm), entries in clusters.items():
        # ADR-0032: every machine group goes through the same matching as a
        # single record, in turn. A group joins an existing Computer, or one
        # an earlier group of this cluster just created, unless a hard
        # conflict proves it is a different machine; only then is a new
        # Computer created. Nothing is created without matching (the old
        # "kept separate" path minted Computers for same-source records
        # without looking at their serial).
        for group in _group_same_machine(entries):
            head = max(group, key=lambda entry: entry[4] or entry[3])
            platform, entity_type, entity_key, _first, _last, cd = head
            match = resolve_match(
                cur,
                tenant_id=TENANT_ID,
                source_name=platform,
                external_id=entity_key,
                entity_type=entity_type,
                serial=cd.get("serial_number"),
                vm_uuid=cd.get("vm_uuid"),
                hostname=norm,
                macs=cd.get("macs") or [],
                client_id=client_id,
                policies=identity_policies,
                is_online=cd.get("is_online"),
            )
            if match is not None:
                for entry in group:
                    cur.execute(
                        """
                        UPDATE operations.entity_observation_current
                        SET device_id = %s
                        WHERE tenant_id = %s AND platform = %s AND entity_key = %s
                          AND device_id IS NULL
                        """,
                        (match.device_id, TENANT_ID, entry[0], entry[2]),
                    )
                touched.add(match.device_id)
                invalidate_client_names(client_id)
                continue
            touched.add(_create_device_for_group(cur, agent_ids, client_id, norm, group))
            # The next group of this cluster must see the Computer just created.
            invalidate_client_names(client_id)
            promoted += 1

    # A new Computer is inserted pending and must be named before commit.
    write_computer_names(cur, touched)
    invalidate_client_names()

    if promoted:
        log.info("resolver: promoted %d new devices", promoted)
    return promoted


MAX_AUTOMATIC_MERGES_PER_RUN = 500

# One row per current Computer: the usable serials and VM UUIDs its records
# report (active records; for a Computer with none active, what they last
# reported), whether it is live, and its age.
PROVEN_SPLIT_SQL = """
WITH rej AS (
    SELECT normalized_value AS v FROM operations.identity_value_rejections
     WHERE value_kind = 'serial' AND enabled
), recs AS (
    -- Hardware evidence only: agent and VM records. Documentation (a CMDB
    -- asset's typed-in serial) is never merge proof.
    SELECT d.id AS device_id, d.client_id, d.created_at, eo.active,
           eo.platform || ':' || eo.entity_type AS stream,
           coalesce((eo.canonical_data ->> 'is_online')::boolean, false) AS online,
           lower(split_part(coalesce(eo.canonical_data ->> 'hostname', ''), '.', 1)) AS host,
           -- A roaming record (migration 0318) proves nothing by serial.
           CASE WHEN rr.external_id IS NULL
                THEN lower(trim(eo.canonical_data ->> 'serial_number')) END AS sn,
           CASE WHEN rr.external_id IS NULL
                THEN lower(nullif(trim(eo.canonical_data ->> 'vm_uuid'), '')) END AS vu
      FROM operations.devices d
      JOIN operations.entity_observation_current eo
        ON eo.tenant_id = d.tenant_id AND eo.device_id = d.id
      LEFT JOIN operations.identity_roaming_records rr
        ON rr.tenant_id = eo.tenant_id AND rr.source_instance_id = eo.source_instance_id
       AND rr.external_id = eo.external_id
     WHERE d.tenant_id = %s AND d.deleted_at IS NULL
       AND (eo.entity_type LIKE 'agent.%%' OR eo.entity_type LIKE 'vm.%%')
       AND eo.entity_key NOT LIKE 'device-health:%%'
), live AS (
    SELECT device_id, bool_or(active) AS live FROM recs GROUP BY device_id
), two_machines AS (
    -- Two records of one source online at once under different names: two
    -- machines already share this Computer; it is never merged further.
    SELECT DISTINCT x.device_id
      FROM recs x JOIN recs y
        ON y.device_id = x.device_id AND y.stream = x.stream
       AND x.active AND y.active AND x.online AND y.online
       AND x.host <> '' AND y.host <> '' AND x.host < y.host
)
SELECT r.device_id, r.client_id, min(r.created_at) AS created_at, l.live,
       coalesce(array_agg(DISTINCT r.sn) FILTER (
           WHERE r.sn IS NOT NULL AND length(r.sn) >= 4
             AND r.sn !~ '^(.)\\1*$'
             AND r.sn NOT IN (SELECT v FROM rej)
             AND (r.active OR NOT l.live)), '{}') AS serials,
       coalesce(array_agg(DISTINCT r.vu) FILTER (
           WHERE r.vu IS NOT NULL AND (r.active OR NOT l.live)), '{}') AS vm_uuids,
       coalesce(array_agg(DISTINCT r.stream) FILTER (WHERE r.active AND r.online), '{}')
           AS online_streams,
       EXISTS (SELECT 1 FROM two_machines t WHERE t.device_id = r.device_id) AS two_machines
  FROM recs r JOIN live l ON l.device_id = r.device_id
 GROUP BY r.device_id, r.client_id, l.live
"""


def planned_proven_merges(cur) -> list[tuple]:
    """Merges the resolver would make: (survivor, absorbed, kind, value).

    Computers in one client that report the same usable serial or VM UUID are
    one machine split apart (ADR-0032). A Computer is merged only when it
    reports exactly one serial and at most one VM UUID, so one that holds two
    machines is never merged further (it raises "two machines on one
    Computer" instead). The oldest live Computer of each group survives.
    """
    separated = _operator_separated_pairs(cur)
    cur.execute(PROVEN_SPLIT_SQL, (TENANT_ID,))
    rows = cur.fetchall()
    groups: dict[tuple, list[tuple]] = {}
    for (
        device_id,
        client_id,
        created_at,
        live,
        serials,
        vm_uuids,
        online_streams,
        two_machines,
    ) in rows:
        if two_machines or len(serials) > 1 or len(vm_uuids) > 1:
            continue
        for kind, values in (("serial", serials), ("vm_uuid", vm_uuids)):
            if values:
                groups.setdefault((client_id, kind, values[0]), []).append(
                    (
                        device_id,
                        created_at,
                        live,
                        tuple(serials),
                        tuple(vm_uuids),
                        frozenset(online_streams),
                    )
                )
    planned: list[tuple] = []
    absorbed: set = set()
    for (_client_id, kind, value), members in sorted(
        groups.items(), key=lambda item: str(item[0])
    ):
        members = [member for member in members if member[0] not in absorbed]
        if len(members) < 2 or not any(member[2] for member in members):
            continue
        # A serial group whose members carry different VM UUIDs (or the
        # reverse) is not proven one machine.
        other = 4 if kind == "serial" else 3
        if len({member[other] for member in members if member[other]}) > 1:
            continue
        # Two members each online in the same source: two live installs, so
        # two machines sharing a serial (a cloned VM), not a split.
        seen: set = set()
        clash = False
        for member in members:
            if seen & member[5]:
                clash = True
                break
            seen |= member[5]
        if clash:
            continue
        # An operator decision (confirmed separate, or records split off) is
        # never undone by an automatic merge.
        ids = [member[0] for member in members]
        if any((a, b) in separated for a in ids for b in ids if a != b):
            continue
        survivor = min(
            (member for member in members if member[2]), key=lambda m: (m[1], str(m[0]))
        )
        for member in members:
            if member[0] != survivor[0]:
                planned.append((survivor[0], member[0], kind, value))
                absorbed.add(member[0])
    return planned


def _operator_separated_pairs(cur) -> set[tuple]:
    """Computer pairs an operator kept apart (decisions or a split), both directions."""
    cur.execute(
        """
        SELECT dec.device_id, k.value::uuid
          FROM operations.device_operator_decisions dec,
               jsonb_array_elements_text(dec.value) k
         WHERE dec.tenant_id = %s AND dec.dimension = 'identity_separate'
        UNION
        SELECT dec.device_id, eo.device_id
          FROM operations.device_operator_decisions dec,
               jsonb_array_elements_text(dec.value) k
          JOIN operations.entity_observation_current eo
            ON eo.tenant_id = %s AND eo.platform = split_part(k.value, '|', 1)
           AND eo.entity_key = substr(k.value, length(split_part(k.value, '|', 1)) + 2)
         WHERE dec.tenant_id = %s AND dec.dimension = 'identity_excluded_records'
           AND eo.device_id IS NOT NULL
        UNION
        -- A merge that was split is an operator decision that they differ.
        SELECT survivor_id, absorbed_id FROM operations.computer_merges
         WHERE tenant_id = %s AND split_at IS NOT NULL
        """,
        (TENANT_ID, TENANT_ID, TENANT_ID, TENANT_ID),
    )
    pairs: set[tuple] = set()
    for a, b in cur.fetchall():
        pairs.add((a, b))
        pairs.add((b, a))
    return pairs


# Hourly maintenance inside the resolver. The cadence lives in the database
# (migration 0323): every Jobs run is a new process, so a timestamp held in
# memory would let the work run on every resolver run.
_MAINTENANCE_INTERVAL = "1 hour"
ROAMING_COMPONENT = "identity.roaming_records"
SHADOW_NAMING_COMPONENT = "identity.shadow_naming"

# Aggregate telemetry of the current resolver run, returned in the Job result
# (counts, durations, whether each maintenance component ran). Never names or
# record evidence.
_telemetry: dict[str, object] = {}


def reset_telemetry() -> None:
    _telemetry.clear()


def take_telemetry() -> dict[str, object]:
    """The telemetry gathered since the last reset, then reset."""
    snapshot = dict(_telemetry)
    _telemetry.clear()
    return snapshot


def _add_count(key: str, value: int) -> None:
    _telemetry[key] = int(_telemetry.get(key, 0)) + int(value)


def _claim_maintenance(cur, component: str) -> bool | None:
    """True when this run takes the component's hourly slot; None before 0323."""
    cur.execute(
        "SELECT to_regprocedure('operations.claim_maintenance(bigint, text, interval)') IS NOT NULL"
    )
    if not cur.fetchone()[0]:
        return None
    # Explicit casts: psycopg sends small ints as smallint and floats as double
    # precision, and PostgreSQL has no implicit cast from double precision to
    # numeric, so an uncast call finds no function.
    cur.execute(
        "SELECT operations.claim_maintenance(%s::bigint, %s::text, %s::interval)",
        (TENANT_ID, component, _MAINTENANCE_INTERVAL),
    )
    return bool(cur.fetchone()[0])


def _complete_maintenance(cur, component: str, seconds: float) -> None:
    cur.execute(
        "SELECT operations.complete_maintenance(%s::bigint, %s::text, %s::numeric)",
        (TENANT_ID, component, round(seconds, 3)),
    )


def refresh_roaming_records(cur) -> None:
    """Recompute roaming agent records (migrations 0318, 0322) at most once an hour.

    Reading the observation history takes seconds, so it is not done on every
    resolution batch; a new clone's record becomes roaming within the hour.
    The claim is part of the resolution transaction: if that rolls back, the
    slot is free again.
    """
    cur.execute(
        "SELECT to_regprocedure('operations.refresh_identity_roaming_records(bigint)') IS NOT NULL"
    )
    if not cur.fetchone()[0]:
        return
    claimed = _claim_maintenance(cur, ROAMING_COMPONENT)
    if claimed is False:
        _telemetry["roaming"] = {"ran": False}
        return
    started = time.monotonic()
    cur.execute("SELECT operations.refresh_identity_roaming_records(%s)", (TENANT_ID,))
    records = cur.fetchone()[0]
    seconds = time.monotonic() - started
    if claimed:
        _complete_maintenance(cur, ROAMING_COMPONENT, seconds)
    _telemetry["roaming"] = {"ran": True, "records": records, "seconds": round(seconds, 1)}
    log.info("resolver: %s roaming agent records in %.1fs", records, seconds)


def reconcile_computer_names() -> None:
    """Full set-based naming reconciliation, each resolver run (ADR-0034 section 6).

    Catches source updates, name-kind changes, missed signals and the 30-day
    reporting boundary; writes only changed decisions.
    """
    try:
        started = time.monotonic()
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            cur.execute("SET LOCAL statement_timeout = '300s'")
            changed = write_computer_names(cur, None)
        seconds = time.monotonic() - started
        _telemetry["naming"] = {"changed": changed, "seconds": round(seconds, 1)}
        log.info("resolver: naming reconciliation changed %d Computers in %.1fs", changed, seconds)
    except Exception:
        _telemetry["naming"] = {"failed": True}
        log.exception("resolver: naming reconciliation failed — continuing")


def run_shadow_naming() -> None:
    """Compute every Computer's name under ADR-0034 and record what would change.

    Step 1 of the ADR's activation order: read only, at most once an hour, so
    it never affects resolution. The claim is committed on its own; the pass
    runs in a read-only transaction; the counts and runtime go to the log and
    the Job result for the activation review.
    """
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            cur.execute(
                "SELECT to_regprocedure('operations.computer_name_shadow(bigint)') IS NOT NULL"
            )
            if not cur.fetchone()[0]:
                return
            claimed = _claim_maintenance(cur, SHADOW_NAMING_COMPONENT)
        if claimed is False:
            _telemetry["shadow_naming"] = {"ran": False}
            return
        started = time.monotonic()
        collisions = None
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            cur.execute(
                "SELECT to_regprocedure('operations.refresh_computer_name_collisions(bigint)') IS NOT NULL"
            )
            if cur.fetchone()[0]:
                # Collisions of this pass, for the identity findings (ADR-0034).
                cur.execute(
                    "SELECT operations.refresh_computer_name_collisions(%s::bigint)", (TENANT_ID,)
                )
                collisions = cur.fetchone()[0]
        with db.transaction() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
            cur.execute("SET LOCAL statement_timeout = '300s'")
            cur.execute(
                """
                SELECT lifecycle_status = 'retired', outcome, name_rule, count(*)
                  FROM operations.computer_name_shadow(%s)
                 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
                """,
                (TENANT_ID,),
            )
            counts = cur.fetchall()
        seconds = time.monotonic() - started
        if claimed:
            with db.transaction() as cur:
                cur.execute(f"SET LOCAL operations.tenant_id = {TENANT_ID}")
                _complete_maintenance(cur, SHADOW_NAMING_COMPONENT, seconds)
        summary = {
            f"{'retired' if retired else 'live'}:{outcome}:{rule}": n
            for retired, outcome, rule, n in counts
        }
        _telemetry["shadow_naming"] = {
            "ran": True,
            "seconds": round(seconds, 1),
            "counts": summary,
            "collisions": collisions,
        }
        log.info(
            "resolver: shadow naming in %.1fs: %s",
            seconds,
            "; ".join(f"{key}={n}" for key, n in summary.items()),
        )
    except Exception:
        _telemetry["shadow_naming"] = {"ran": False, "failed": True}
        log.exception("resolver: shadow naming failed — continuing")


def merge_proven_splits(cur) -> int:
    """Merge Computers proven to be one machine; each merge is recorded."""
    planned = planned_proven_merges(cur)[:MAX_AUTOMATIC_MERGES_PER_RUN]
    for survivor, absorbed, kind, value in planned:
        label = "serial number" if kind == "serial" else "VM UUID"
        cur.execute(
            """
            SELECT operations.merge_computers(%s::uuid, %s::uuid, %s::text, %s::jsonb,
                                              'process', NULL::bigint,
                                              'ingest.identity.resolver')
            """,
            (
                survivor,
                absorbed,
                f"Both Computers report the same {label}.",
                Json({kind: value}),
            ),
        )
    write_computer_names(cur, [c for row in planned for c in row[:2]])
    if planned:
        log.info("resolver: merged %d Computers proven to be one machine", len(planned))
    return len(planned)


def _create_device_for_group(
    cur,
    agent_ids: dict[str, int],
    client_id,
    norm: str,
    group: list[tuple],
) -> uuid.UUID:
    """Create one Computer for a machine group no existing Computer matched."""
    # device_role is not derived here — the projector owns it. The layer
    # entities below still need a form factor at creation time; the facet
    # propagation reconciles it against the projector-owned cache on the next
    # cycle.
    latest_cd = max(group, key=lambda entry: entry[4] or entry[3])[5]
    serial = latest_cd.get("serial_number")
    if not is_usable_serial(serial):
        serial = None
    os_name = next(
        (
            entry[5].get("os_name")
            for entry in sorted(
                group, key=lambda entry: entry[4] or entry[3], reverse=True
            )
            if entry[5].get("os_name")
        ),
        None,
    )
    platforms = sorted({entry[0] for entry in group})
    device_id = uuid.uuid4()
    reason = f"auto-promoted from {', '.join(platforms)}"
    _create_device_anchor(cur, device_id, client_id, reason)
    cur.execute(
        """
        -- ADR-0012: promotion creates the identity anchor only. The five
        -- cache columns are NOT NULL, so they get neutral placeholders here
        -- and `device_cache_projector` fills them later in this same resolver
        -- cycle.
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
            device_id,
            TENANT_ID,
            client_id,
            device_id,
            norm,
            serial or "",
            latest_cd.get("vm_uuid") or "",
            reason[:120],
        ),
    )
    _write_layer_entities_for_new_device(
        cur,
        device_id=device_id,
        form_factor=_infer_form_factor(group),
        serial=serial or "",
        vm_uuid=latest_cd.get("vm_uuid") or "",
        os_name=os_name or "",
        os_fam=os_family(os_name) if os_name else "",
        os_group="Unknown",
        first_seen=min((entry[3] for entry in group if entry[3]), default=None),
        last_seen=max((entry[4] for entry in group if entry[4]), default=None),
        entries=group,
        agent_ids=agent_ids,
    )
    # The observation update is the whole attachment;
    # sync_entity_source_links_from_observations() derives the link.
    for entry in group:
        cur.execute(
            """
            UPDATE operations.entity_observation_current
            SET device_id = %s
            WHERE tenant_id = %s AND platform = %s AND entity_key = %s
              AND device_id IS NULL
            """,
            (device_id, TENANT_ID, entry[0], entry[2]),
        )
    log.info(
        "resolver: promoted device %s hostname=%s client=%s platforms=%s",
        device_id,
        norm,
        client_id,
        platforms,
    )
    return device_id


def _upsert_shared_serial_findings(cur, finding_type_id: int) -> int:
    """Upsert shared-serial findings with a UUID canonical subject.

    ADR-0032: the serials compared are those the active agent and VM records
    of current Computers report now, not the stored Computer serial (which
    missed 26 Computers). Automatic merges absorb most groups first; what
    remains is two live installs of one source (a clone) or a Computer that
    holds two machines. ``subject_id`` is the first Computer by UUID text.
    Each finding gets a measured assessment and clears once its group is gone.
    """
    cur.execute(
        """
        WITH reported AS (
            -- The key keeps the Computer's stored spelling of the serial when
            -- it is the same value, so existing findings keep their key.
            SELECT DISTINCT d.tenant_id, d.client_id, d.id, d.canonical_hostname,
                   lower(btrim(eo.canonical_data ->> 'serial_number')) AS serial_key,
                   CASE WHEN lower(btrim(d.canonical_serial))
                             = lower(btrim(eo.canonical_data ->> 'serial_number'))
                        THEN btrim(d.canonical_serial)
                        ELSE btrim(eo.canonical_data ->> 'serial_number') END AS serial
              FROM operations.devices d
              JOIN operations.entity_observation_current eo
                ON eo.tenant_id = d.tenant_id AND eo.device_id = d.id
             WHERE d.tenant_id = %s AND d.deleted_at IS NULL AND eo.active
               AND (eo.entity_type LIKE 'agent.%%' OR eo.entity_type LIKE 'vm.%%')
               AND eo.entity_key NOT LIKE 'device-health:%%'
               AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                                WHERE rr.tenant_id = eo.tenant_id
                                  AND rr.source_instance_id = eo.source_instance_id
                                  AND rr.external_id = eo.external_id)
               AND LENGTH(BTRIM(eo.canonical_data ->> 'serial_number')) >= 4
               AND LENGTH(REPLACE(
                     LOWER(BTRIM(eo.canonical_data ->> 'serial_number')),
                     LEFT(LOWER(BTRIM(eo.canonical_data ->> 'serial_number')), 1), ''
                   )) > 0
               AND NOT EXISTS (
                   SELECT 1
                   FROM operations.identity_value_rejections rejected
                   WHERE rejected.value_kind = 'serial'
                     AND rejected.enabled
                     AND rejected.normalized_value
                         = LOWER(BTRIM(eo.canonical_data ->> 'serial_number'))
               )
        )
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
                tenant_id, client_id,
                min(serial COLLATE "C") AS serial,
                COUNT(DISTINCT id) AS device_count,
                (ARRAY_AGG(id ORDER BY id::text))[1] AS first_device_id,
                ARRAY_AGG(DISTINCT id::text) AS device_ids,
                ARRAY_AGG(DISTINCT canonical_hostname) AS hostnames
            FROM (SELECT DISTINCT ON (id, serial_key) * FROM reported
                   ORDER BY id, serial_key, serial COLLATE "C") per_computer
            GROUP BY tenant_id, client_id, serial_key
            HAVING COUNT(DISTINCT id) > 1
        ) sub
        ON CONFLICT (tenant_id, condition_key)
        WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            client_id = EXCLUDED.client_id,
            subject_id = EXCLUDED.subject_id,
            last_seen_at = NOW(),
            last_detected_at = NOW(),
            finding_details = EXCLUDED.finding_details,
            severity = EXCLUDED.severity,
            confidence = EXCLUDED.confidence
        RETURNING id, condition_key, subject_id
        """,
        (TENANT_ID, finding_type_id),
    )
    rows = cur.fetchall()
    now = datetime.now(UTC)
    for finding_id, condition_key, subject_id in rows:
        identity_findings.record_measured(
            cur, TENANT_ID, finding_id, finding_type_id, condition_key, subject_id, now
        )
    identity_findings.resolve_absent(
        cur, TENANT_ID, finding_type_id, [row[1] for row in rows], now
    )
    return len(rows)


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
    ft_shared = _load_finding_type_id(cur, "shared_serial")
    ft_unmatched = _load_finding_type_id(cur, "unmatched_source_group")
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
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            DO UPDATE SET
                client_id = EXCLUDED.client_id,
                subject_id = EXCLUDED.subject_id,
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details,
                severity = EXCLUDED.severity,
                confidence = EXCLUDED.confidence
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

    # cross_client_serial is replaced by computer_client_conflict
    # (ingest.identity.findings, ADR-0040).

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
                'critical', 'confirmed', 'open',
                u.first_seen_at, u.last_seen_at, NOW()
            FROM operations.unmatched_source_groups u
            WHERE u.tenant_id = %s AND u.status = 'pending'
            ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            DO UPDATE SET
                client_id = EXCLUDED.client_id,
                subject_id = EXCLUDED.subject_id,
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details,
                severity = EXCLUDED.severity,
                confidence = EXCLUDED.confidence
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
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            DO UPDATE SET
                client_id = EXCLUDED.client_id,
                subject_id = EXCLUDED.subject_id,
                last_seen_at = NOW(),
                last_detected_at = NOW(),
                finding_details = EXCLUDED.finding_details,
                severity = EXCLUDED.severity,
                confidence = EXCLUDED.confidence
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

    Per ADR-0005 slice 2. Called from `_create_device_for_group`, the
    single Device creation site.

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
            TENANT_ID,
            device_id,
            form_factor,
            serial or "",
            vm_uuid or "",
            first_seen,
            first_seen,
            last_seen,
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
                TENANT_ID,
                device_id,
                os_name or "",
                os_fam or "",
                os_group or "Unknown",
                first_seen,
                first_seen,
                last_seen,
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
                    TENANT_ID,
                    device_id,
                    agent_id,
                    install_token,
                    agent_ver,
                    e_first,
                    e_first,
                    e_last,
                ),
            )
