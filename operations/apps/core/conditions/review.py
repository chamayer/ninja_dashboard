"""Audited operator review for a condition that is intentionally distinct."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction

from ..models import AuditLog


def record_reviewed_distinct(
    *, actor, tenant_id: int, condition_identity: str,
    membership_fingerprint: str, evidence_fingerprint: str, reason: str,
) -> None:
    """Record a review tied to exact membership and evidence fingerprints."""
    if not actor.has_perm("operations.write_decisions"):
        raise PermissionDenied("The operator cannot write decisions.")
    if not reason or not reason.strip():
        raise ValidationError("A reviewed-distinct decision reason is required.")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = %s", (str(tenant_id),))
        cursor.execute(
            """SELECT operations.record_reviewed_distinct(%s,%s,%s,%s,%s,%s)""",
            (tenant_id, condition_identity, membership_fingerprint,
             evidence_fingerprint, actor.pk, reason.strip()),
        )
        AuditLog.objects.create(
            tenant_id=tenant_id, actor=actor, actor_kind="user", source="ui",
            action="condition.reviewed_distinct", entity_type="condition",
            after_state={
                "condition_identity": condition_identity,
                "membership_fingerprint": membership_fingerprint,
                "evidence_fingerprint": evidence_fingerprint,
                "reason": reason.strip(),
            },
        )
