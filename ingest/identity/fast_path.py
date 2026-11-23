"""Inline Computer identity resolution during collection.

The matcher order and conflict blockers live in
``operations.identity_match_policies``. This module deliberately has no
source- or virtualization-specific matching branches.
"""

from __future__ import annotations

import uuid

from ingest.identity.matching import (
    IdentityMatchPolicy,
    OwnershipMatchDeferred,
    load_identity_match_policies,
    resolve_match,
)


def resolve_device_fast(
    cur,
    tenant_id: int,
    source_name: str,
    external_id: str,
    entity_type: str,
    serial: str | None = None,
    vm_uuid: str | None = None,
    hostname: str | None = None,
    macs: list[str] | None = None,
    client_id: uuid.UUID | None = None,
    policies: tuple[IdentityMatchPolicy, ...] | None = None,
    is_online: bool | None = None,
    source_instance_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Return one Computer selected by the enabled identity policy (ADR-0032)."""
    result = resolve_device_fast_match(
        cur, tenant_id, source_name, external_id, entity_type, serial, vm_uuid,
        hostname, macs, client_id, policies, is_online, source_instance_id,
    )
    return result.device_id if result else None


def resolve_device_fast_match(*args, **kwargs):
    """Return match evidence for intake while retaining deferred-ownership behavior."""
    try:
        return _resolve_device_fast(*args, **kwargs)
    except OwnershipMatchDeferred:
        return None


def _resolve_device_fast(
    cur, tenant_id, source_name, external_id, entity_type, serial, vm_uuid,
    hostname, macs, client_id, policies, is_online, source_instance_id,
    source_identity_key=None, source_seen_at=None,
):
    return resolve_match(
        cur,
        tenant_id=tenant_id,
        source_name=source_name,
        external_id=external_id,
        entity_type=entity_type,
        serial=serial,
        vm_uuid=vm_uuid,
        hostname=hostname,
        macs=macs,
        client_id=client_id,
        policies=policies or load_identity_match_policies(cur, tenant_id),
        is_online=is_online,
        source_instance_id=source_instance_id,
        source_identity_key=source_identity_key,
        source_seen_at=source_seen_at,
    )
