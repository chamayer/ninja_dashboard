"""Shared population selectors for operator-facing Computer readers.

``v_device`` is one row per canonical Computer. Its ordinary operational
population is current Computers: non-deleted by the view itself and not
retired here. Pending-cleanup Computers remain current; recent contact and
online state are separate dimensions.
"""

from __future__ import annotations

from uuid import UUID

from django.db import connection
from django.db.models import QuerySet
from django.db.models.expressions import RawSQL
from django.http import Http404

from .models import Device


def current_computers(queryset: QuerySet[Device]) -> QuerySet[Device]:
    """Select the ordinary operational Computer population from an ORM query."""
    return queryset.exclude(lifecycle_status=Device.LifecycleStatus.RETIRED)


def client_owned_device_ids(tenant_id: int, client_id) -> RawSQL:
    return RawSQL(
        "SELECT device_id FROM operations.computer_client_ownership "
        "WHERE tenant_id = %s AND effective_client_id = %s "
        "AND state IN ('resolved', 'decision_protected')",
        [tenant_id, client_id],
    )


def effectively_owned_device_ids(tenant_id: int) -> RawSQL:
    """Current owners whose projected client agrees with the Computer copy."""
    return RawSQL(
        "SELECT owner.device_id FROM operations.computer_client_ownership owner "
        "JOIN operations.devices d ON d.tenant_id = owner.tenant_id AND d.id = owner.device_id "
        "AND d.client_id = owner.effective_client_id "
        "WHERE owner.tenant_id = %s AND owner.state IN ('resolved', 'decision_protected')",
        [tenant_id],
    )


def effective_computer_client_sql(alias: str) -> str:
    """Client of a v_device row, or NULL while ownership is unresolved."""
    return (
        "(SELECT owner.effective_client_id FROM operations.computer_client_ownership owner "
        f"WHERE owner.tenant_id = {alias}.tenant_id AND owner.device_id = {alias}.device_id "
        f"AND owner.effective_client_id = {alias}.client_id "
        "AND owner.state IN ('resolved', 'decision_protected'))"
    )


def client_owned_finding_ids(tenant_id: int) -> RawSQL:
    """Device findings whose stored client is still the effective owner."""
    return RawSQL(
        "SELECT f.id FROM operations.findings f "
        "JOIN operations.computer_client_ownership owner "
        "ON owner.tenant_id = f.tenant_id AND owner.device_id = f.subject_id "
        "AND owner.effective_client_id = f.client_id "
        "AND owner.state IN ('resolved', 'decision_protected') "
        "WHERE f.tenant_id = %s AND f.subject_type = 'device'",
        [tenant_id],
    )


def source_owned_finding_ids(tenant_id: int) -> RawSQL:
    """Source-record findings whose stored client is still independently supported."""
    return RawSQL(
        "SELECT f.id FROM operations.findings f "
        "JOIN operations.source_record_subjects s ON s.tenant_id = f.tenant_id AND s.id = f.subject_id "
        "WHERE f.tenant_id = %s AND f.subject_type = 'source_record' "
        "AND f.client_id = operations.computer_client_independent_evidence(s.tenant_id, s.observation_id)",
        [tenant_id],
    )


def client_owned_computers(queryset: QuerySet[Device], tenant_id: int, client_id) -> QuerySet[Device]:
    """Only Computers whose current projection authorizes this client."""
    return queryset.filter(
        tenant_id=tenant_id, client_id=client_id, id__in=client_owned_device_ids(tenant_id, client_id)
    )


def lock_client_owned_computer(tenant_id: int, device_id, client_id) -> None:
    """Fence an ownership-dependent write until the surrounding transaction ends."""
    if not connection.in_atomic_block:
        raise RuntimeError("Computer ownership locks require an atomic transaction")
    try:
        device_id = UUID(str(device_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise Http404("Computer not found") from exc
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT operations.lock_computer_client_scope(%s, %s::uuid, %s::uuid)",
            [tenant_id, device_id, client_id],
        )
        if not cursor.fetchone()[0]:
            raise Http404("Computer not found")


def current_computer_sql(alias: str = "") -> str:
    """Return the lifecycle predicate for a ``v_device`` SQL reader.

    ``v_device`` already excludes deleted Computers. Callers must supply the
    tenant/access predicate independently before using this fragment.
    """
    prefix = f"{alias}." if alias else ""
    return f"{prefix}lifecycle_status <> 'retired'"
