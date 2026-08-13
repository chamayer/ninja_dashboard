"""Atomic generic candidate decisions over authoritative source links.

Three decisions, all operator-invoked and all audited:

* **attach** — this source identity is the entity we already know about.
* **reject** — this source identity is not worth anchoring.
* **promote** — this source identity *is* a thing we do not yet track, so
  create its anchor. Until this existed, an entity class with zero entities
  could never gain its first one: `attach_candidate` requires a target that
  already exists, and the only two creation paths in the platform mint a
  `device` or a `client` by reusing that typed row's UUID. Classes without a
  typed table -- `asset` above all -- had no way in.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AuditLog,
    Client,
    Device,
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


def _link_candidate_to_entity(
    *, candidate: EntityCandidate, entity: Entity, actor: User, reason: str
):
    """Attach the candidate's stable source identity to `entity`.

    Extracted verbatim from `attach_candidate` so promotion reuses the exact
    link and history behavior rather than a second copy that can drift.
    Returns the timestamp used, so the caller stamps the decision with it.
    """
    identity = {
        "tenant_id": candidate.tenant_id,
        "source_instance": candidate.source_instance,
        "external_namespace": candidate.external_namespace,
        "parent_external_namespace": candidate.parent_external_namespace,
        "parent_external_id": candidate.parent_external_id,
        "external_id": candidate.external_id,
    }
    existing = EntitySourceLink.objects.select_for_update().filter(**identity).first()
    if existing is not None and existing.entity_id != entity.id:
        raise ValidationError("The stable source identity is already attached elsewhere.")
    now = timezone.now()
    if existing is None:
        EntitySourceLink.objects.create(
            **identity,
            entity=entity,
            entity_class_id=entity.entity_class_id,
            first_seen_at=candidate.first_observed_at,
            last_seen_at=candidate.last_observed_at,
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
            evidence={"candidate_id": str(candidate.id)},
            effective_from=now,
        )
    return now


def class_supports_promotion(entity_class_id: str) -> bool:
    """Whether a bare anchor may be minted for this class. See the guard below."""
    return not (
        Device.objects.filter(entity__entity_class_id=entity_class_id).exists()
        or Client.objects.filter(entity__entity_class_id=entity_class_id).exists()
    )


def _assert_class_has_no_typed_record(entity_class_id: str) -> None:
    """Refuse to mint a bare anchor for a class that keeps a typed twin.

    `device` and `client` anchors are created by reusing the typed row's UUID
    (`resolver._create_device_anchor`, migration 0101), so every anchor of
    those classes has a `devices` / `clients` row behind it. A bare anchor
    would satisfy no such invariant and would render as an orphan.

    Derived by asking the data rather than listing class names, so a future
    typed class is covered without editing this file -- and so this stays a
    structural guard rather than a hardcoded domain mapping (ADR-0012 s6).
    """
    if not class_supports_promotion(entity_class_id):
        raise ValidationError(
            f"Entities of class '{entity_class_id}' are created with their typed "
            "record; promoting a bare anchor would orphan it."
        )


@transaction.atomic
def promote_candidate(
    *, actor: User, candidate: EntityCandidate, reason: str
) -> EntityCandidate:
    """Create the anchor this candidate proposes, then attach it.

    The candidate already carries everything an anchor needs: tenant, proposed
    class, and client scope. Scope follows ownership per ADR-0012 s4 -- a
    client-attributed candidate yields a client-scoped entity, otherwise
    tenant-scoped -- which is also what `ck_entities_scope_owner` enforces.
    """
    _authorize(actor, candidate)
    reason = reason.strip()
    if not reason:
        raise ValidationError("A candidate decision reason is required.")
    locked = EntityCandidate.objects.select_for_update().get(
        tenant_id=candidate.tenant_id,
        id=candidate.id,
    )
    if locked.status == EntityCandidate.Status.ATTACHED:
        raise ValidationError("An attached candidate is already anchored.")
    if locked.status == EntityCandidate.Status.REJECTED:
        raise ValidationError("A rejected candidate cannot be promoted.")
    _assert_class_has_no_typed_record(locked.proposed_entity_class_id)

    entity = Entity.objects.create(
        tenant_id=locked.tenant_id,
        entity_class_id=locked.proposed_entity_class_id,
        scope_kind=(
            Entity.ScopeKind.CLIENT if locked.client_id else Entity.ScopeKind.TENANT
        ),
        client_id=locked.client_id,
        created_reason=f"candidate.promote:{locked.id}"[:120],
        updated_reason=f"candidate.promote:{locked.id}"[:120],
    )
    now = _link_candidate_to_entity(
        candidate=locked, entity=entity, actor=actor, reason=reason
    )

    before_status = locked.status
    locked.status = EntityCandidate.Status.ATTACHED
    locked.resolved_entity = entity
    locked.latest_decision = "promote"
    locked.latest_decision_reason = reason
    locked.latest_decided_by = actor
    locked.latest_decided_at = now
    locked.version += 1
    locked.save()
    _record_decision(
        candidate=locked,
        actor=actor,
        action="promote",
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

    now = _link_candidate_to_entity(
        candidate=locked, entity=entity, actor=actor, reason=reason
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
