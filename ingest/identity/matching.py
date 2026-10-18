"""Operator-managed Computer identity matching (ADR-0032).

The policy table selects from a small set of evidence matchers and their order.
The code owns normalization, the live-Computer boundary, hard conflicts and
candidate selection:

* A candidate is a live Computer in the record's client: one with at least one
  active record. Empty Computers (no active record) are candidates only when no
  live Computer matches, so a returning machine keeps its history.
* Serial and VM UUID are compared with what active records report now, not with
  a Computer's stored value (a stale stored serial caused a wrong merge).
* Names match exactly, ignoring separators, or as a 15-character cut of a
  longer name (Ninja reports Windows' 15-character name).
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
) -> MatchResult | None:
    """Select a Computer for one source record, or None when nothing matches.

    ``skip_source_identity`` is the re-check: an attached record whose serial
    or VM UUID arrived or changed is matched again without its current link.
    """
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
        )
    return []


def _name_candidates(
    cur,
    *,
    tenant_id: int,
    hostname: str,
    client_id: uuid.UUID | None,
    macs: list[str] | None,
    source_name: str,
    external_id: str,
) -> list[uuid.UUID]:
    """Live Computers whose name matches; empty ones only when no live one does."""
    loose = loose_name(hostname)
    cut = hostname if len(hostname) == _NETBIOS_LENGTH else None
    cur.execute(
        """
        WITH named AS (
            SELECT d.id, d.canonical_hostname
              FROM operations.devices d
             WHERE d.tenant_id = %(tenant)s AND d.deleted_at IS NULL
               -- Retired Computers stay candidates (as empty ones): a machine
               -- that reappears returns to its Computer and history.
               AND (%(client)s::uuid IS NULL OR d.client_id = %(client)s::uuid)
               AND (d.canonical_hostname = %(name)s
                    OR regexp_replace(lower(d.canonical_hostname), '[^a-z0-9]', '', 'g') = %(loose)s
                    OR (%(cut)s::text IS NOT NULL
                        AND length(d.canonical_hostname) > 15
                        AND left(d.canonical_hostname, 15) = %(cut)s)
                    OR (length(d.canonical_hostname) = 15
                        AND length(%(name)s) > 15
                        AND left(%(name)s, 15) = d.canonical_hostname))
        ), classified AS (
            SELECT n.id, n.canonical_hostname,
                   EXISTS (SELECT 1 FROM operations.entity_observation_current eo
                            WHERE eo.tenant_id = %(tenant)s AND eo.device_id = n.id AND eo.active
                              AND NOT (eo.platform = %(source)s AND eo.entity_key = %(key)s)) AS live,
                   (%(macs)s::text[] IS NULL OR EXISTS (
                        SELECT 1 FROM operations.entity_observation_current eo
                         WHERE eo.tenant_id = %(tenant)s AND eo.device_id = n.id AND eo.active
                           AND EXISTS (SELECT 1
                                         FROM jsonb_array_elements_text(
                                              COALESCE(eo.canonical_data -> 'macs', '[]'::jsonb)) m(mac)
                                        WHERE m.mac = ANY(%(macs)s::text[])
                                          AND m.mac NOT LIKE '00:15:5d:%%'))) AS mac_ok
              FROM named n
        )
        SELECT id, canonical_hostname, live FROM classified WHERE mac_ok
        """,
        {
            "tenant": tenant_id,
            "client": client_id,
            "name": hostname,
            "loose": loose,
            "cut": cut,
            "macs": macs,
            "source": source_name,
            "key": external_id,
        },
    )
    rows = cur.fetchall()
    # A 15-character cut matches a longer name only when exactly one such name
    # exists; two longer names behind one cut are ambiguous, not a match.
    if cut:
        longer = {name for _id, name, _live in rows if len(name) > _NETBIOS_LENGTH}
        if len(longer) > 1:
            rows = [row for row in rows if len(row[1]) <= _NETBIOS_LENGTH]
    live = [row[0] for row in rows if row[2]]
    return live or [row[0] for row in rows]


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
