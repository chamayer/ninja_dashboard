"""Validated operator decisions for canonical relationship edges."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    Entity,
    EntityRelationshipDecisionCurrent,
    RelationshipType,
    User,
)


def _authorize(actor: User, source: Entity, target: Entity) -> None:
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("An active authenticated operator is required.")
    if actor.tenant_id != source.tenant_id or actor.tenant_id != target.tenant_id:
        raise PermissionDenied("The operator and endpoints must share a tenant.")
    if not actor.has_perm("operations.write_decisions"):
        raise PermissionDenied("The operator cannot write decisions.")


@transaction.atomic
def set_relationship_decision(
    *,
    actor: User,
    relationship_type: RelationshipType,
    source_entity: Entity,
    target_entity: Entity,
    operation: str,
    reason: str,
) -> EntityRelationshipDecisionCurrent:
    """Set include/exclude intent; database triggers audit and queue the edge."""
    _authorize(actor, source_entity, target_entity)
    reason = reason.strip()
    if not reason:
        raise ValidationError("A relationship decision reason is required.")
    if not relationship_type.enabled:
        raise ValidationError("The relationship type is disabled.")
    if relationship_type.source_entity_class_id != source_entity.entity_class_id:
        raise ValidationError("The source entity class violates the relationship type.")
    if relationship_type.target_entity_class_id != target_entity.entity_class_id:
        raise ValidationError("The target entity class violates the relationship type.")
    if source_entity.id == target_entity.id:
        raise ValidationError("A relationship cannot connect an entity to itself.")
    if operation not in EntityRelationshipDecisionCurrent.Operation.values:
        raise ValidationError("Relationship decisions support include or exclude.")

    now = timezone.now()
    decision = (
        EntityRelationshipDecisionCurrent.objects.select_for_update()
        .filter(
            tenant_id=source_entity.tenant_id,
            relationship_type=relationship_type,
            source_entity=source_entity,
            target_entity=target_entity,
        )
        .first()
    )
    if decision is None:
        decision = EntityRelationshipDecisionCurrent(
            tenant_id=source_entity.tenant_id,
            relationship_type=relationship_type,
            source_entity=source_entity,
            target_entity=target_entity,
            decided_at=now,
        )
    else:
        decision.version += 1
    decision.operation = operation
    decision.active = True
    decision.reason = reason
    decision.decided_by = actor
    decision.updated_at = now
    decision.full_clean()
    decision.save()
    return decision


@transaction.atomic
def deactivate_relationship_decision(
    *, actor: User, decision: EntityRelationshipDecisionCurrent, reason: str
) -> EntityRelationshipDecisionCurrent:
    _authorize(actor, decision.source_entity, decision.target_entity)
    reason = reason.strip()
    if not reason:
        raise ValidationError("A relationship decision reason is required.")
    locked = EntityRelationshipDecisionCurrent.objects.select_for_update().get(
        tenant_id=decision.tenant_id,
        id=decision.id,
    )
    locked.active = False
    locked.reason = reason
    locked.decided_by = actor
    locked.updated_at = timezone.now()
    locked.version += 1
    locked.save(update_fields=("active", "reason", "decided_by", "updated_at", "version"))
    return locked
