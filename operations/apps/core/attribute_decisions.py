"""Validated writes for generic operator attribute decisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone as django_timezone

from .models import (
    AttributeDefinition,
    Entity,
    EntityAttributeDecisionCurrent,
    EntityAttributeDecisionMemberCurrent,
    User,
)


@dataclass(frozen=True)
class DecisionMemberInput:
    action: str
    value: Any


def _typed_value(  # noqa: PLR0912 -- one closed typed union
    *, tenant_id: int, value_type: str, value: Any
) -> tuple[dict[str, Any], bytes]:
    fields: dict[str, Any] = {
        "value_text": None,
        "value_number": None,
        "value_boolean": None,
        "value_timestamp": None,
        "value_entity": None,
        "value_json": None,
    }
    if value_type == AttributeDefinition.ValueType.TEXT:
        normalized = str(value).strip()
        if not normalized:
            raise ValidationError("Text decisions cannot be empty.")
        fields["value_text"] = normalized
        canonical = normalized
    elif value_type == AttributeDefinition.ValueType.NUMBER:
        try:
            normalized = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("Decision value must be numeric.") from exc
        if not normalized.is_finite():
            raise ValidationError("Decision value must be a finite number.")
        fields["value_number"] = normalized
        canonical = str(normalized)
    elif value_type == AttributeDefinition.ValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValidationError("Decision value must be Boolean.")
        fields["value_boolean"] = value
        canonical = "true" if value else "false"
    elif value_type == AttributeDefinition.ValueType.TIMESTAMP:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValidationError("Decision timestamp must include a timezone.")
        normalized = value.astimezone(UTC)
        fields["value_timestamp"] = normalized
        canonical = normalized.isoformat(sep=" ").replace("+00:00", "+00")
    elif value_type == AttributeDefinition.ValueType.ENTITY_REFERENCE:
        try:
            entity_id = value.id if isinstance(value, Entity) else uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationError("Decision value must reference an entity.") from exc
        referenced = Entity.objects.filter(tenant_id=tenant_id, id=entity_id).first()
        if referenced is None:
            raise ValidationError("Referenced entity is outside the decision tenant.")
        fields["value_entity"] = referenced
        canonical = str(referenced.id)
    elif value_type == AttributeDefinition.ValueType.STRUCTURED:
        if not isinstance(value, dict | list):
            raise ValidationError("Structured decisions require an object or array.")
        fields["value_json"] = value
        canonical = json.dumps(value, sort_keys=True, separators=(", ", ": "))
    else:
        raise ValidationError("Unsupported attribute value type.")
    fingerprint = hashlib.sha256(f"{value_type}:{canonical}".encode()).digest()
    return fields, fingerprint


def _authorize(actor: User, entity: Entity) -> None:
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("An active authenticated operator is required.")
    if actor.tenant_id != entity.tenant_id:
        raise PermissionDenied("The operator and entity must share a tenant.")
    if not actor.has_perm("operations.write_decisions"):
        raise PermissionDenied("The operator cannot write decisions.")


@transaction.atomic
def set_attribute_decision(  # noqa: PLR0912, PLR0915 -- full atomic contract
    *,
    actor: User,
    entity: Entity,
    attribute_definition: AttributeDefinition,
    operation: str,
    reason: str,
    value: Any = None,
    members: tuple[DecisionMemberInput, ...] = (),
) -> EntityAttributeDecisionCurrent:
    """Replace one current decision; database triggers audit and queue it."""
    _authorize(actor, entity)
    reason = reason.strip()
    if not reason:
        raise ValidationError("A decision reason is required.")
    if not attribute_definition.enabled:
        raise ValidationError("The attribute definition is disabled.")
    if attribute_definition.entity_class_id != entity.entity_class_id:
        raise ValidationError("The attribute definition does not match the entity class.")

    scalar_fields = {
        "value_text": None,
        "value_number": None,
        "value_boolean": None,
        "value_timestamp": None,
        "value_entity": None,
        "value_json": None,
    }
    scalar_fingerprint = None
    member_rows: list[tuple[DecisionMemberInput, dict[str, Any], bytes]] = []
    if attribute_definition.cardinality == AttributeDefinition.Cardinality.SINGLE:
        if operation not in (
            EntityAttributeDecisionCurrent.Operation.REPLACE,
            EntityAttributeDecisionCurrent.Operation.CLEAR,
        ):
            raise ValidationError("Single-value decisions support replace or clear.")
        if members:
            raise ValidationError("Single-value decisions cannot contain members.")
        if operation == EntityAttributeDecisionCurrent.Operation.REPLACE:
            if value is None:
                raise ValidationError("Replace requires a value.")
            scalar_fields, scalar_fingerprint = _typed_value(
                tenant_id=entity.tenant_id,
                value_type=attribute_definition.value_type,
                value=value,
            )
        elif value is not None:
            raise ValidationError("Clear cannot contain a value.")
    else:
        if operation not in (
            EntityAttributeDecisionCurrent.Operation.REPLACE,
            EntityAttributeDecisionCurrent.Operation.MODIFY,
        ):
            raise ValidationError("Set decisions support replace or modify.")
        if value is not None:
            raise ValidationError("Set decisions use typed members, not a scalar value.")
        seen: set[bytes] = set()
        for member in members:
            if member.action not in (
                EntityAttributeDecisionMemberCurrent.Action.ADD,
                EntityAttributeDecisionMemberCurrent.Action.REMOVE,
            ):
                raise ValidationError("Set member action must be add or remove.")
            if (
                operation == EntityAttributeDecisionCurrent.Operation.REPLACE
                and member.action != EntityAttributeDecisionMemberCurrent.Action.ADD
            ):
                raise ValidationError("Replace-set decisions accept only add members.")
            typed_fields, fingerprint = _typed_value(
                tenant_id=entity.tenant_id,
                value_type=attribute_definition.value_type,
                value=member.value,
            )
            if fingerprint in seen:
                raise ValidationError("A set decision cannot repeat the same member.")
            seen.add(fingerprint)
            member_rows.append((member, typed_fields, fingerprint))

    now = django_timezone.now()
    decision = (
        EntityAttributeDecisionCurrent.objects.select_for_update()
        .filter(
            tenant_id=entity.tenant_id,
            entity=entity,
            attribute_definition=attribute_definition,
        )
        .first()
    )
    if decision is None:
        decision = EntityAttributeDecisionCurrent(
            tenant_id=entity.tenant_id,
            entity=entity,
            entity_class_id=entity.entity_class_id,
            attribute_definition=attribute_definition,
            decided_at=now,
        )
    else:
        decision.version += 1
    decision.operation = operation
    decision.value_type = attribute_definition.value_type
    decision.cardinality = attribute_definition.cardinality
    decision.value_fingerprint = scalar_fingerprint
    decision.active = True
    decision.reason = reason
    decision.decided_by = actor
    decision.updated_at = now
    for field, field_value in scalar_fields.items():
        setattr(decision, field, field_value)
    decision.full_clean()
    decision.save()

    decision.members.all().delete()
    for member, typed_fields, fingerprint in member_rows:
        row = EntityAttributeDecisionMemberCurrent(
            tenant_id=entity.tenant_id,
            decision=decision,
            action=member.action,
            value_type=attribute_definition.value_type,
            value_fingerprint=fingerprint,
            member_key=fingerprint,
            **typed_fields,
        )
        row.full_clean()
        row.save()
    return decision


@transaction.atomic
def deactivate_attribute_decision(
    *, actor: User, entity: Entity, attribute_definition: AttributeDefinition, reason: str
) -> EntityAttributeDecisionCurrent:
    """Deactivate operator precedence while preserving the audited decision row."""
    _authorize(actor, entity)
    reason = reason.strip()
    if not reason:
        raise ValidationError("A decision reason is required.")
    decision = EntityAttributeDecisionCurrent.objects.select_for_update().get(
        tenant_id=entity.tenant_id,
        entity=entity,
        attribute_definition=attribute_definition,
    )
    decision.active = False
    decision.reason = reason
    decision.decided_by = actor
    decision.updated_at = django_timezone.now()
    decision.version += 1
    decision.save(update_fields=("active", "reason", "decided_by", "updated_at", "version"))
    return decision
