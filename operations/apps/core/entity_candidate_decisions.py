"""Atomic generic candidate decisions over authoritative source links."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AuditLog,
    Entity,
    EntityCandidate,
    EntityCandidateEvent,
    EntitySourceLink,
    EntitySourceLinkHistory,
    User,
)


def _authorize(actor: User, candidate: EntityCandidate) -> None:
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("An active authenticated operator is required.")
    if actor.tenant_id != candidate.tenant_id:
        raise PermissionDenied("The operator and candidate must share a tenant.")
    if not actor.has_perm("operations.write_decisions"):
        raise PermissionDenied("The operator cannot write decisions.")


def _record_decision(
    *,
    candidate: EntityCandidate,
    actor: User,
    action: str,
    reason: str,
    before_status: str,
) -> None:
    safe_before = {"status": before_status}
    safe_after = {"status": candidate.status}
    if candidate.resolved_entity_id:
        safe_after["resolved_entity_id"] = str(candidate.resolved_entity_id)
    EntityCandidateEvent.objects.create(
        tenant_id=candidate.tenant_id,
        candidate=candidate,
        action=action,
        actor_kind="user",
        actor=actor,
        reason=reason,
        before_state=safe_before,
        after_state=safe_after,
    )
    AuditLog.objects.create(
        tenant_id=candidate.tenant_id,
        actor=actor,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.API,
        action=f"entity_candidate.{action}",
        entity_type="entity_candidate",
        entity_id=candidate.id,
        before_state=safe_before,
        after_state=safe_after,
    )


@transaction.atomic
def reject_candidate(*, actor: User, candidate: EntityCandidate, reason: str) -> EntityCandidate:
    _authorize(actor, candidate)
    reason = reason.strip()
    if not reason:
        raise ValidationError("A candidate decision reason is required.")
    locked = EntityCandidate.objects.select_for_update().get(
        tenant_id=candidate.tenant_id,
        id=candidate.id,
    )
    if locked.status == EntityCandidate.Status.ATTACHED:
        raise ValidationError("An attached candidate cannot be rejected.")
    before_status = locked.status
    now = timezone.now()
    locked.status = EntityCandidate.Status.REJECTED
    locked.latest_decision = "reject"
    locked.latest_decision_reason = reason
    locked.latest_decided_by = actor
    locked.latest_decided_at = now
    locked.version += 1
    locked.save()
    _record_decision(
        candidate=locked,
        actor=actor,
        action="reject",
        reason=reason,
        before_status=before_status,
    )
    return locked


@transaction.atomic
def attach_candidate(
    *, actor: User, candidate: EntityCandidate, entity: Entity, reason: str
) -> EntityCandidate:
    _authorize(actor, candidate)
    reason = reason.strip()
    if not reason:
        raise ValidationError("A candidate decision reason is required.")
    locked = EntityCandidate.objects.select_for_update().get(
        tenant_id=candidate.tenant_id,
        id=candidate.id,
    )
    if entity.tenant_id != locked.tenant_id:
        raise ValidationError("The candidate and target entity must share a tenant.")
    if entity.entity_class_id != locked.proposed_entity_class_id:
        raise ValidationError("The target entity class does not match the candidate.")
    if locked.client_id and entity.client_id != locked.client_id:
        raise ValidationError("The target entity is outside the candidate client scope.")

    identity = {
        "tenant_id": locked.tenant_id,
        "source_instance": locked.source_instance,
        "external_namespace": locked.external_namespace,
        "parent_external_namespace": locked.parent_external_namespace,
        "parent_external_id": locked.parent_external_id,
        "external_id": locked.external_id,
    }
    existing = EntitySourceLink.objects.select_for_update().filter(**identity).first()
    if existing is not None and existing.entity_id != entity.id:
        raise ValidationError("The stable source identity is already attached elsewhere.")
    now = timezone.now()
    if existing is None:
        existing = EntitySourceLink.objects.create(
            **identity,
            entity=entity,
            entity_class_id=entity.entity_class_id,
            first_seen_at=locked.first_observed_at,
            last_seen_at=locked.last_observed_at,
            match_method="operator",
            match_confidence=1,
            reason=reason[:120],
        )
        EntitySourceLinkHistory.objects.create(
            **identity,
            entity=entity,
            entity_class_id=entity.entity_class_id,
            match_method="operator",
            match_confidence=1,
            actor_kind="user",
            actor=actor,
            reason=reason[:120],
            evidence={"candidate_id": str(locked.id)},
            effective_from=now,
        )

    before_status = locked.status
    locked.status = EntityCandidate.Status.ATTACHED
    locked.resolved_entity = entity
    locked.latest_decision = "attach"
    locked.latest_decision_reason = reason
    locked.latest_decided_by = actor
    locked.latest_decided_at = now
    locked.version += 1
    locked.save()
    _record_decision(
        candidate=locked,
        actor=actor,
        action="attach",
        reason=reason,
        before_status=before_status,
    )
    return locked
