"""Operator-managed Computer identity matching.

The policy table selects from a small set of evidence matchers.  The code owns
normalization, tenant/deleted-anchor boundaries, and safe SQL; policy owns the
order, confidence, scope, duplicate-stream guard, and conflict blockers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from ingest.normalize import is_usable_serial

_MATCHERS = frozenset(
    {"source_identity", "serial", "vm_uuid", "hostname_mac", "hostname"}
)
_SIGNALS = frozenset({"vm_uuid"})


@dataclass(frozen=True)
class IdentityMatchPolicy:
    matcher: str
    priority: int
    requires_client_scope: bool
    requires_unique_candidate: bool
    avoid_same_stream_duplicates: bool
    blocking_signal_keys: frozenset[str]
    confidence: Decimal


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


def resolve_device_by_policy(
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
) -> uuid.UUID | None:
    """Return one live Computer selected by the configured policy, or None."""
    for policy in policies:
        candidates = _candidates(
            cur,
            tenant_id=tenant_id,
            source_name=source_name,
            external_id=external_id,
            entity_type=entity_type,
            serial=serial,
            vm_uuid=vm_uuid,
            hostname=hostname,
            macs=macs or [],
            client_id=client_id,
            policy=policy,
        )
        if policy.requires_unique_candidate and len(candidates) != 1:
            continue
        for candidate in candidates:
            if _blocked_by_conflicting_signal(
                cur, tenant_id, candidate, vm_uuid, policy.blocking_signal_keys
            ):
                continue
            if policy.avoid_same_stream_duplicates and _same_stream_conflict(
                cur, tenant_id, candidate, source_name, entity_type, external_id
            ):
                continue
            return candidate
    return None


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
    policy: IdentityMatchPolicy,
) -> list[uuid.UUID]:
    if policy.requires_client_scope and client_id is None:
        return []
    client_where = "AND d.client_id = %s" if policy.requires_client_scope else ""
    client_params: tuple[object, ...] = (
        (client_id,) if policy.requires_client_scope else ()
    )
    if policy.matcher == "source_identity":
        cur.execute(
            f"""
            SELECT DISTINCT d.id
              FROM operations.entity_observation_current eo
              JOIN operations.devices d
                ON d.tenant_id = eo.tenant_id AND d.id = eo.device_id
             WHERE eo.tenant_id = %s AND eo.platform = %s AND eo.entity_key = %s
               AND eo.entity_type = %s AND d.deleted_at IS NULL {client_where}
            """,
            (tenant_id, source_name, external_id, entity_type, *client_params),
        )
    elif policy.matcher == "serial" and is_usable_serial(serial):
        cur.execute(
            f"""
            SELECT d.id FROM operations.devices d
             WHERE d.tenant_id = %s AND d.canonical_serial = %s
               AND d.deleted_at IS NULL {client_where}
            """,
            (tenant_id, serial, *client_params),
        )
    elif policy.matcher == "vm_uuid" and vm_uuid:
        cur.execute(
            f"""
            SELECT d.id FROM operations.devices d
             WHERE d.tenant_id = %s AND LOWER(d.canonical_vm_uuid) = LOWER(%s)
               AND d.deleted_at IS NULL {client_where}
            """,
            (tenant_id, vm_uuid, *client_params),
        )
    elif policy.matcher == "hostname_mac" and hostname and macs:
        cur.execute(
            f"""
            SELECT DISTINCT d.id
              FROM operations.devices d
              JOIN operations.entity_observation_current eo
                ON eo.tenant_id = d.tenant_id AND eo.device_id = d.id
               AND eo.active = TRUE
             WHERE d.tenant_id = %s AND d.canonical_hostname = %s
               AND d.deleted_at IS NULL {client_where}
               AND EXISTS (
                   SELECT 1
                     FROM jsonb_array_elements_text(
                         COALESCE(eo.canonical_data -> 'macs', '[]'::jsonb)
                     ) AS known(mac)
                    WHERE known.mac = ANY(%s)
               )
            """,
            (tenant_id, hostname, *client_params, macs),
        )
    elif policy.matcher == "hostname" and hostname:
        cur.execute(
            f"""
            SELECT d.id FROM operations.devices d
             WHERE d.tenant_id = %s AND d.canonical_hostname = %s
               AND d.deleted_at IS NULL {client_where}
            """,
            (tenant_id, hostname, *client_params),
        )
    else:
        return []
    return [row[0] for row in cur.fetchall()]


def _blocked_by_conflicting_signal(
    cur,
    tenant_id: int,
    device_id: uuid.UUID,
    incoming_vm_uuid: str | None,
    blockers: frozenset[str],
) -> bool:
    if "vm_uuid" not in blockers or not incoming_vm_uuid:
        return False
    cur.execute(
        """
        SELECT 1
          FROM operations.entity_observation_current eo
         WHERE eo.tenant_id = %s AND eo.device_id = %s AND eo.active = TRUE
           AND NULLIF(eo.canonical_data ->> 'vm_uuid', '') IS NOT NULL
           AND LOWER(eo.canonical_data ->> 'vm_uuid') <> LOWER(%s)
         LIMIT 1
        """,
        (tenant_id, device_id, incoming_vm_uuid),
    )
    return cur.fetchone() is not None


def _same_stream_conflict(
    cur,
    tenant_id: int,
    device_id: uuid.UUID,
    platform: str,
    entity_type: str,
    entity_key: str,
) -> bool:
    cur.execute(
        """
        SELECT 1 FROM operations.entity_observation_current
         WHERE tenant_id = %s AND device_id = %s AND active = TRUE
           AND platform = %s AND entity_type = %s AND entity_key <> %s
         LIMIT 1
        """,
        (tenant_id, device_id, platform, entity_type, entity_key),
    )
    return cur.fetchone() is not None
