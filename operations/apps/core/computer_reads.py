"""Shared population selectors for operator-facing Computer readers.

``v_device`` is one row per canonical Computer. Its ordinary operational
population is current Computers: non-deleted by the view itself and not
retired here. Pending-cleanup Computers remain current; recent contact and
online state are separate dimensions.
"""

from __future__ import annotations

from django.db.models import QuerySet
from django.db.models.expressions import RawSQL

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


def client_owned_computers(queryset: QuerySet[Device], tenant_id: int, client_id) -> QuerySet[Device]:
    """Only Computers whose current projection authorizes this client."""
    return queryset.filter(
        tenant_id=tenant_id, client_id=client_id, id__in=client_owned_device_ids(tenant_id, client_id)
    )


def current_computer_sql(alias: str = "") -> str:
    """Return the lifecycle predicate for a ``v_device`` SQL reader.

    ``v_device`` already excludes deleted Computers. Callers must supply the
    tenant/access predicate independently before using this fragment.
    """
    prefix = f"{alias}." if alias else ""
    return f"{prefix}lifecycle_status <> 'retired'"
