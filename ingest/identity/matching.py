"""Operator-managed Computer identity matching (ADR-0032).

The policy table selects from a small set of evidence matchers and their order.
The code owns normalization, the live-Computer boundary, hard conflicts and
candidate selection:

* A candidate is a live Computer in the record's client: one with at least one
  active record. Empty Computers (no active record) are candidates only when no
  live Computer matches, so a returning machine keeps its history.
* Serial and VM UUID are compared with what active records report now, not with
  a Computer's stored value (a stale stored serial caused a wrong merge).
* Names are the names the client's source records report (ADR-0034
  section 4), never a Computer's stored name: matched exactly, ignoring
  separators, or as a 15-character cut of a longer name, in tiers (current
  records on active Computers, on other non-retired Computers, withdrawn
  records, record history).
* Only a hard conflict excludes a candidate: a different usable serial, a
  different VM UUID, or a record of the same source and type that is live on
  the candidate at the same time as the incoming record. For an empty Computer
  its last-known serial counts. A record an operator split off a Computer
  never matches that Computer again.
* A roaming record (an agent identity moving between clones of one image,
  ``operations.identity_roaming_records``) proves nothing by serial or VM
  UUID, as candidate or as incoming record.
* Several candidates: the most recently active one is chosen (ties: the oldest
  Computer). The evaluator surfaces name-only groups as findings; nothing here
  creates a Computer to avoid a choice.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from ingest.normalize import is_usable_serial

_MATCHERS = frozenset(
    {"source_identity", "serial", "vm_uuid", "hostname_mac", "hostname"}
)
_SIGNALS = frozenset({"serial", "vm_uuid", "same_source_live"})
_NETBIOS_LENGTH = 15
_LOOSE_RE = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True)
class IdentityMatchPolicy:
    matcher: str
    priority: int
    requires_client_scope: bool
    requires_unique_candidate: bool
    avoid_same_stream_duplicates: bool
    blocking_signal_keys: frozenset[str]
    confidence: Decimal


@dataclass(frozen=True)
class MatchResult:
    """The selected Computer and the evidence that selected it."""

    device_id: uuid.UUID
    matcher: str
    compared: dict = field(default_factory=dict)
    candidates: tuple[uuid.UUID, ...] = ()


def load_identity_match_policies(
    cur, tenant_id: int
) -> tuple[IdentityMatchPolicy, ...]:
    """Load validated enabled policies, failing closed on bad configuration."""
    cur.execute(
        """
        SELECT matcher, priority, requires_client_scope,
               requires_unique_candidate, avoid_same_stream_duplicates,
               blocking_signal_keys, confidence
          FROM operations.identity_match_policies
         WHERE tenant_id = %s AND enabled = TRUE
         ORDER BY priority, matcher
        """,
        (tenant_id,),
    )
    policies: list[IdentityMatchPolicy] = []
    seen: set[str] = set()
    for (
        matcher,
        priority,
        client_scope,
        unique,
        avoid_same_stream,
        blockers,
        confidence,
    ) in cur.fetchall():
        blocker_set = frozenset(blockers or [])
        if matcher not in _MATCHERS or matcher in seen or not blocker_set <= _SIGNALS:
            raise RuntimeError("invalid enabled Computer identity-match policy")
        seen.add(matcher)
        policies.append(
            IdentityMatchPolicy(
                matcher=matcher,
                priority=priority,
                requires_client_scope=client_scope,
                requires_unique_candidate=unique,
                avoid_same_stream_duplicates=avoid_same_stream,
                blocking_signal_keys=blocker_set,
                confidence=confidence,
            )
        )
    if not policies:
        raise RuntimeError("no enabled Computer identity-match policy")
    return tuple(policies)


def loose_name(name: str | None) -> str:
    """The name with separators removed (dash, space, apostrophe, dot...)."""
    return _LOOSE_RE.sub("", (name or "").lower())


def resolve_device_by_policy(cur, **kwargs) -> uuid.UUID | None:
    """Return one Computer selected by the configured policy, or None."""
    result = resolve_match(cur, **kwargs)
    return result.device_id if result else None


def resolve_match(
    cur,
    *,
    tenant_id: int,
    source_name: str,
    external_id: str,
    entity_type: str,
    serial: str | None,
    vm_uuid: str | None,
    hostname: str | None,
    macs: list[str] | None,
    client_id: uuid.UUID | None,
    policies: tuple[IdentityMatchPolicy, ...],
    is_online: bool | None = None,
    skip_source_identity: bool = False,
    identity_types: list[str] | None = None,
) -> MatchResult | None:
    """Select a Computer for one source record, or None when nothing matches.

    ``skip_source_identity`` is the re-check: an attached record whose serial
    or VM UUID arrived or changed is matched again without its current link.
    """
    if identity_types is None:
        identity_types = _identity_types(cur)
    record_serial = serial.strip().lower() if is_usable_serial(serial) else None
    record_vm_uuid = (vm_uuid or "").strip().lower() or None
    if (record_serial or record_vm_uuid) and _is_roaming(cur, tenant_id, source_name, external_id):
        # The record moves between clones of one image (migration 0317): its
        # serial and VM UUID prove nothing about this machine.
        record_serial = record_vm_uuid = None
    for policy in policies:
        if skip_source_identity and policy.matcher == "source_identity":
            continue
        if policy.requires_client_scope and client_id is None:
            continue
        candidates = _candidates(
            cur,
            tenant_id=tenant_id,
            source_name=source_name,
            external_id=external_id,
            entity_type=entity_type,
            serial=record_serial,
            vm_uuid=record_vm_uuid,
            hostname=hostname,
            macs=macs or [],
            client_id=client_id if policy.requires_client_scope else None,
            matcher=policy.matcher,
            identity_types=identity_types,
        )
        if not candidates:
            continue
        usable = [
            device_id
            for device_id in candidates
            if not _hard_conflict(
                cur,
                tenant_id,
                device_id,
                policy.blocking_signal_keys,
                source_name=source_name,
                entity_type=entity_type,
                external_id=external_id,
                serial=record_serial,
                vm_uuid=record_vm_uuid,
                is_online=is_online,
            )
        ]
        if not usable:
            continue
        if policy.requires_unique_candidate and len(usable) != 1:
            continue
        chosen = _most_recently_active(cur, tenant_id, usable)
        return MatchResult(
            device_id=chosen,
            matcher=policy.matcher,
            compared=_compared(policy.matcher, record_serial, record_vm_uuid, hostname),
            candidates=tuple(usable),
        )
    return None


def _identity_types(cur) -> list[str]:
    from ingest.identity import identity_entity_types

    return sorted(identity_entity_types(cur))


def _is_roaming(cur, tenant_id: int, source_name: str, external_id: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM operations.entity_observation_current eo
          JOIN operations.identity_roaming_records rr
            ON rr.tenant_id = eo.tenant_id AND rr.source_instance_id = eo.source_instance_id
           AND rr.external_id = eo.external_id
         WHERE eo.tenant_id = %s AND eo.platform = %s AND eo.entity_key = %s
         LIMIT 1
        """,
        (tenant_id, source_name, external_id),
    )
    return cur.fetchone() is not None


def _compared(matcher: str, serial, vm_uuid, hostname) -> dict:
    if matcher == "serial":
        return {"serial": serial}
    if matcher == "vm_uuid":
        return {"vm_uuid": vm_uuid}
    if matcher in ("hostname", "hostname_mac"):
        return {"hostname": hostname}
    return {}


def _candidates(
    cur,
    *,
    tenant_id: int,
    source_name: str,
    external_id: str,
    entity_type: str,
    serial: str | None,
    vm_uuid: str | None,
    hostname: str | None,
    macs: list[str],
    client_id: uuid.UUID | None,
    matcher: str,
    identity_types: list[str],
) -> list[uuid.UUID]:
    if matcher == "source_identity":
        cur.execute(
            """
            SELECT DISTINCT d.id
              FROM operations.entity_observation_current eo
              JOIN operations.devices d
                ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
             WHERE eo.tenant_id = %s AND eo.platform = %s AND eo.entity_key = %s
               AND eo.entity_type = %s AND d.deleted_at IS NULL
               AND (%s::uuid IS NULL OR d.client_id = %s::uuid)
            """,
            (tenant_id, source_name, external_id, entity_type, client_id, client_id),
        )
        return [row[0] for row in cur.fetchall()]
    if matcher == "serial" and serial:
        cur.execute(
            """
            SELECT DISTINCT d.id
              FROM operations.entity_observation_current eo
              JOIN operations.devices d
                ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
             WHERE eo.tenant_id = %s AND eo.active
               AND lower(trim(eo.canonical_data ->> 'serial_number')) = %s
               AND NOT (eo.platform = %s AND eo.entity_key = %s)
               AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                                WHERE rr.tenant_id = eo.tenant_id
                                  AND rr.source_instance_id = eo.source_instance_id
                                  AND rr.external_id = eo.external_id)
               AND d.deleted_at IS NULL
               AND (%s::uuid IS NULL OR d.client_id = %s::uuid)
            """,
            (tenant_id, serial, source_name, external_id, client_id, client_id),
        )
        return [row[0] for row in cur.fetchall()]
    if matcher == "vm_uuid" and vm_uuid:
        cur.execute(
            """
            SELECT DISTINCT d.id
              FROM operations.entity_observation_current eo
              JOIN operations.devices d
                ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
             WHERE eo.tenant_id = %s AND eo.active
               AND lower(eo.canonical_data ->> 'vm_uuid') = %s
               AND NOT (eo.platform = %s AND eo.entity_key = %s)
               AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                                WHERE rr.tenant_id = eo.tenant_id
                                  AND rr.source_instance_id = eo.source_instance_id
                                  AND rr.external_id = eo.external_id)
               AND d.deleted_at IS NULL
               AND (%s::uuid IS NULL OR d.client_id = %s::uuid)
            """,
            (tenant_id, vm_uuid, source_name, external_id, client_id, client_id),
        )
        return [row[0] for row in cur.fetchall()]
    if matcher in ("hostname", "hostname_mac") and hostname:
        if matcher == "hostname_mac" and not macs:
            return []
        return _name_candidates(
            cur,
            tenant_id=tenant_id,
            hostname=hostname,
            client_id=client_id,
            macs=macs if matcher == "hostname_mac" else None,
            source_name=source_name,
            external_id=external_id,
            identity_types=identity_types,
        )
    return []


_NAME_CANDIDATES = """
WITH inc AS (
    SELECT %(name)s::text AS short,
           regexp_replace(%(name)s::text, '[^a-z0-9]', '', 'g') AS key,
           -- Every match (same key, or either 15-character cut) has a raw name
           -- whose letters and digits start with these: a cheap necessary
           -- condition checked before the normalization function.
           regexp_replace(left(%(name)s::text, 15), '[^a-z0-9]', '', 'g') AS pre
), recs AS (
    -- Every named identity record of the client's Computers, normalized by the
    -- one SQL function (ADR-0034 section 1). Roaming records carry no name.
    SELECT eo.device_id, d.lifecycle_status, f.name_short, f.name_key,
           eo.active AND coalesce(lc.record_lifecycle, '') <> 'archived' AS is_current
      FROM operations.entity_observation_current eo
      JOIN operations.devices d
        ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id AND d.deleted_at IS NULL
      LEFT JOIN operations.v_device_source_record_lifecycle_current lc
        ON lc.observation_id = eo.observation_id
     CROSS JOIN LATERAL operations.record_name_forms(
          eo.platform, eo.entity_type,
          coalesce(nullif(eo.canonical_data ->> 'hostname', ''), eo.canonical_data ->> 'guest_name'),
          eo.canonical_data ->> 'domain') f
     WHERE eo.tenant_id = %(tenant)s
       AND (%(client)s::uuid IS NULL OR d.client_id = %(client)s::uuid)
       AND eo.entity_type = ANY(%(types)s::text[])
       AND eo.entity_key NOT LIKE 'device-health:%%'
       AND NOT (eo.platform = %(source)s AND eo.entity_key = %(key)s)
       AND left(regexp_replace(lower(coalesce(nullif(eo.canonical_data ->> 'hostname', ''),
                                                 eo.canonical_data ->> 'guest_name', '')),
                               '[^a-z0-9]', '', 'g'), length((SELECT pre FROM inc)))
           = (SELECT pre FROM inc)
       AND f.name_short IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = eo.tenant_id
                          AND rr.source_instance_id = eo.source_instance_id
                          AND rr.external_id = eo.external_id)
)
SELECT r.device_id,
       CASE WHEN r.is_current AND r.lifecycle_status = 'active' THEN 1
            WHEN r.is_current AND r.lifecycle_status <> 'retired' THEN 2
            ELSE 3 END AS tier,
       r.name_short, r.name_key
  FROM recs r, inc
 WHERE r.name_key = inc.key
    OR (length(inc.short) = 15 AND length(r.name_short) > 15 AND left(r.name_short, 15) = inc.short)
    OR (length(r.name_short) = 15 AND length(inc.short) > 15 AND left(inc.short, 15) = r.name_short)
"""

# Names the client's records reported earlier (tier 4), distinct per record.
# Reading the history of every record of a large client takes seconds, so it
# is computed once per client and kept briefly (_HISTORY_TTL).
_HISTORY_NAMES = """
SELECT DISTINCT eo.device_id, eo.platform, eo.entity_key, f.name_short, f.name_key
  FROM (
    SELECT DISTINCT eo.device_id, eo.platform, eo.entity_key, h.platform AS h_platform,
           h.entity_type AS h_type,
           coalesce(nullif(h.material_data ->> 'hostname', ''), h.material_data ->> 'guest_name') AS raw,
           h.material_data ->> 'domain' AS domain
      FROM operations.entity_observation_current eo
      JOIN operations.devices d
        ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id AND d.deleted_at IS NULL
      JOIN operations.entity_observation_history h
        ON h.tenant_id = eo.tenant_id AND h.source_instance_id = eo.source_instance_id
       AND h.external_id = eo.external_id AND h.entity_type = eo.entity_type
     WHERE eo.tenant_id = %(tenant)s
       AND (%(client)s::uuid IS NULL OR d.client_id = %(client)s::uuid)
       AND eo.entity_type = ANY(%(types)s::text[])
       AND NOT EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = eo.tenant_id
                          AND rr.source_instance_id = eo.source_instance_id
                          AND rr.external_id = eo.external_id)
  ) eo
 CROSS JOIN LATERAL operations.record_name_forms(eo.h_platform, eo.h_type, eo.raw, eo.domain) f
 WHERE f.name_key IS NOT NULL
"""
_HISTORY_TTL = 600.0
_history_cache: dict[tuple, tuple[float, list[tuple]]] = {}


def _history_names(cur, tenant_id: int, client_id, identity_types: list[str]) -> list[tuple]:
    cache_key = (tenant_id, client_id, tuple(sorted(identity_types)))
    cached = _history_cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _HISTORY_TTL:
        return cached[1]
    cur.execute(
        _HISTORY_NAMES, {"tenant": tenant_id, "client": client_id, "types": identity_types}
    )
    rows = cur.fetchall()
    _history_cache[cache_key] = (now, rows)
    return rows


def _name_candidates(
    cur,
    *,
    tenant_id: int,
    hostname: str,
    client_id: uuid.UUID | None,
    macs: list[str] | None,
    source_name: str,
    external_id: str,
    identity_types: list[str],
) -> list[uuid.UUID]:
    """Computers whose records report the name (ADR-0034 section 4).

    ``hostname`` is the incoming record's strict name form from
    ``operations.record_name_forms``. Tiers, the first with a candidate
    deciding: current records on active Computers, on other non-retired
    Computers, withdrawn records, record history. Within the tier a strict
    match may name several Computers (the most recently active is chosen and
    the duplicate is reported); a loose match decides only when it identifies
    exactly one Computer; a 15-character match only when exactly one distinct
    longer name starts with it.
    """
    cur.execute(
        _NAME_CANDIDATES,
        {
            "tenant": tenant_id,
            "client": client_id,
            "name": hostname,
            "source": source_name,
            "key": external_id,
            "types": identity_types,
        },
    )
    rows = cur.fetchall()
    key = _LOOSE_RE.sub("", hostname)
    if not rows:
        # Tier 4 only decides when no current or withdrawn record holds the name.
        rows = [
            (device_id, 4, short, name_key)
            for device_id, platform, entity_key, short, name_key in _history_names(
                cur, tenant_id, client_id, identity_types
            )
            if name_key == key and not (platform == source_name and entity_key == external_id)
        ]
    chosen: list[uuid.UUID] = []
    for tier in (1, 2, 3, 4):
        in_tier = [row for row in rows if row[1] == tier]
        if not in_tier:
            continue
        strict = sorted({row[0] for row in in_tier if row[2] == hostname}, key=str)
        loose = sorted({row[0] for row in in_tier if row[3] == key}, key=str)
        cut_names = {row[2] for row in in_tier if row[3] != key}
        if strict:
            chosen = strict
        elif loose:
            chosen = loose if len(loose) == 1 else []
        elif len(cut_names) == 1:
            chosen = sorted({row[0] for row in in_tier if row[2] in cut_names}, key=str)
        # The highest tier holding the name decides, even when it is ambiguous.
        break
    if chosen and macs is not None:
        cur.execute(
            """
            SELECT DISTINCT eo.device_id
              FROM operations.entity_observation_current eo
             WHERE eo.tenant_id = %s AND eo.device_id = ANY(%s::uuid[]) AND eo.active
               AND EXISTS (SELECT 1
                             FROM jsonb_array_elements_text(
                                  COALESCE(eo.canonical_data -> 'macs', '[]'::jsonb)) m(mac)
                            WHERE m.mac = ANY(%s::text[]) AND m.mac NOT LIKE '00:15:5d:%%')
            """,
            (tenant_id, chosen, macs),
        )
        with_mac = {row[0] for row in cur.fetchall()}
        chosen = [device_id for device_id in chosen if device_id in with_mac]
    return chosen


def record_name_short(cur, platform: str, entity_type: str, name: str | None, domain=None) -> str:
    """The strict name form of one reported name (``operations.record_name_forms``)."""
    if not name:
        return ""
    cur.execute(
        "SELECT name_short FROM operations.record_name_forms(%s, %s, %s, %s)",
        (platform, entity_type, name, domain),
    )
    row = cur.fetchone()
    return (row[0] or "") if row else ""


def _hard_conflict(
    cur,
    tenant_id: int,
    device_id: uuid.UUID,
    blockers: frozenset[str],
    *,
    source_name: str,
    entity_type: str,
    external_id: str,
    serial: str | None,
    vm_uuid: str | None,
    is_online: bool | None,
) -> bool:
    """True when the candidate is proven to be a different machine."""
    # An operator split this record off the candidate (migration 0309).
    cur.execute(
        """
        SELECT 1 FROM operations.device_operator_decisions
         WHERE tenant_id = %s AND device_id = %s AND dimension = 'identity_excluded_records'
           AND value ? %s
        """,
        (tenant_id, device_id, f"{source_name}|{external_id}"),
    )
    if cur.fetchone() is not None:
        return True
    cur.execute(
        """
        SELECT eo.active, eo.platform, eo.entity_type, eo.entity_key,
               lower(trim(eo.canonical_data ->> 'serial_number')),
               lower(eo.canonical_data ->> 'vm_uuid'),
               (eo.canonical_data ->> 'is_online')::boolean,
               eo.canonical_data ->> 'parent_ninja_id',
               EXISTS (SELECT 1 FROM operations.identity_roaming_records rr
                        WHERE rr.tenant_id = eo.tenant_id
                          AND rr.source_instance_id = eo.source_instance_id
                          AND rr.external_id = eo.external_id) AS roaming
          FROM operations.entity_observation_current eo
         WHERE eo.tenant_id = %s AND eo.device_id = %s
           AND NOT (eo.platform = %s AND eo.entity_key = %s)
        """,
        (tenant_id, device_id, source_name, external_id),
    )
    rows = cur.fetchall()
    live_rows = [row for row in rows if row[0]]
    # An empty Computer is judged by what its records last reported. A roaming
    # record's serial and VM UUID belong to whichever clone it ran on last.
    judged = [row for row in (live_rows or rows) if not row[8]]
    if "serial" in blockers and serial:
        known = {row[4] for row in judged if row[4] and is_usable_serial(row[4])}
        if known and serial not in known:
            return True
    if "vm_uuid" in blockers and vm_uuid:
        known = {row[5] for row in judged if row[5]}
        if known and vm_uuid not in known:
            return True
    if "same_source_live" in blockers and is_online:
        # A record of the same source and type that is online on the
        # candidate at the same time as this one: two live installs, so two
        # machines (or, for VM records, two VM objects on different hosts).
        for active, platform, other_type, _key, _sn, _vu, online, _parent, _roam in live_rows:
            if (
                active
                and platform == source_name
                and other_type == entity_type
                and online
            ):
                return True
    return False


def _most_recently_active(
    cur, tenant_id: int, device_ids: list[uuid.UUID]
) -> uuid.UUID:
    if len(device_ids) == 1:
        return device_ids[0]
    cur.execute(
        """
        SELECT d.id
          FROM operations.devices d
          LEFT JOIN LATERAL (
              SELECT max(eo.last_seen_at) AS seen
                FROM operations.entity_observation_current eo
               WHERE eo.tenant_id = d.tenant_id AND eo.device_id = d.id AND eo.active
          ) activity ON TRUE
         WHERE d.tenant_id = %s AND d.id = ANY(%s::uuid[])
         ORDER BY activity.seen DESC NULLS LAST, d.created_at, d.id
         LIMIT 1
        """,
        (tenant_id, list(device_ids)),
    )
    return cur.fetchone()[0]
