"""Inline Computer identity resolution during collection.

The matcher order and conflict blockers live in
``operations.identity_match_policies``. This module deliberately has no
source- or virtualization-specific matching branches.
"""

from __future__ import annotations

import uuid

from ingest.identity.matching import (
    IdentityMatchPolicy,
    load_identity_match_policies,
    resolve_device_by_policy,
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
) -> uuid.UUID | None:
    """Return one live Computer selected by the enabled identity policy."""
    return resolve_device_by_policy(
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
    )
