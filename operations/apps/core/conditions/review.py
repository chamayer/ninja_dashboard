"""Audited operator review for a condition that is intentionally distinct."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction

from ..models import AuditLog


def record_identity_reviewed_distinct(*, actor, tenant_id: int, finding_id, reason: str) -> None:
    """Record a distinct identity decision using DB-derived evidence fingerprints."""
    if not actor.has_perm("operations.write_decisions"):
        raise PermissionDenied("The operator cannot write decisions.")
    if not reason or not reason.strip():
        raise ValidationError("A reviewed-distinct decision reason is required.")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = %s", (str(tenant_id),))
        cursor.execute(
            """
            SELECT condition_key,
                   encode(pg_catalog.sha256(convert_to(
                       (finding_details->'candidate_device_ids')::text, 'UTF8')), 'hex'),
                   encode(pg_catalog.sha256(convert_to(
                       finding_details::text, 'UTF8')), 'hex')
              FROM operations.findings f
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE f.tenant_id = %s AND f.id = %s AND ft.name = 'identity_conflict'
             FOR UPDATE
            """,
            (tenant_id, finding_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValidationError("Identity conflict finding not found.")
        cursor.execute(
            """SELECT operations.record_reviewed_distinct(%s,%s,%s,%s,%s,%s)""",
            (tenant_id, row[0], row[1], row[2], actor.pk, reason.strip()),
        )
        AuditLog.objects.create(
            tenant_id=tenant_id, actor=actor, actor_kind="user", source="ui",
            action="condition.reviewed_distinct", entity_type="condition",
            entity_id=str(finding_id),
            after_state={"condition_identity": row[0], "reason": reason.strip()},
        )


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
