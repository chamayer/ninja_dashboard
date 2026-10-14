"""Approve remote access from the Issues queue.

Remote access is a separate decision from software approval: this writes only
the product authorization for the remote access capability, and software
approval never writes it. Scope is either every client (the MSP's own
management tool) or the client of each selected finding. The older decision is
kept and marked superseded, so the history stays visible.
"""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from .finding_actions import APPROVE_REMOTE_ACCESS_ALL, FindingAction
from .models import AuditLog, Finding, ProductAuthorization

REASON_MAX_LENGTH = 500


def _targets(findings: list[Finding], all_clients: bool) -> set[tuple[uuid.UUID | None, uuid.UUID, str]]:
    """The distinct (client, product, capability) approvals the selection asks for."""
    targets = set()
    for finding in findings:
        details = finding.finding_details or {}
        try:
            product = uuid.UUID(str(details["product_uuid"]))
        except (KeyError, ValueError):
            raise ValueError("A selected issue does not name a product.") from None
        capability = str(details.get("capability") or "")
        if not capability:
            raise ValueError("A selected issue does not name a capability.")
        if not all_clients and finding.client_id is None:
            raise ValueError("A selected issue has no client to approve it for.")
        targets.add((None if all_clients else finding.client_id, product, capability))
    return targets


@transaction.atomic
def approve_remote_access(request: HttpRequest, ids: list[str], action: FindingAction) -> HttpResponse:
    back = request.POST.get("next") or "findings_queue"
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.warning(request, "A reason is required to approve remote access.")
        return redirect(back)
    if len(reason) > REASON_MAX_LENGTH:
        messages.warning(request, f"Keep the reason to {REASON_MAX_LENGTH} characters or fewer.")
        return redirect(back)

    findings = list(
        Finding.objects.select_related("finding_type").filter(tenant_id=1, id__in=ids)
    )
    if len(findings) != len(ids):
        messages.warning(request, "One or more selected issues are no longer available.")
        return redirect(back)
    if any(f.finding_type.name not in action.finding_types for f in findings):
        messages.warning(
            request, "Remote access can only be approved from remote access issues."
        )
        return redirect(back)
    all_clients = action.key == APPROVE_REMOTE_ACCESS_ALL.key
    try:
        targets = _targets(findings, all_clients)
    except ValueError as exc:
        messages.warning(request, str(exc))
        return redirect(back)

    now = timezone.now()
    for client_id, product, capability in sorted(targets, key=str):
        superseded = ProductAuthorization.objects.filter(
            tenant_id=1,
            client_id=client_id,
            product_uuid=product,
            capability=capability,
            withdrawn_at__isnull=True,
        ).update(withdrawn_at=now, withdrawn_reason="superseded by a new permit decision")
        ProductAuthorization.objects.create(
            tenant_id=1,
            client_id=client_id,
            product_uuid=product,
            capability=capability,
            polarity=True,
            rationale=reason,
            authorized_by=request.user,
        )
        AuditLog.objects.create(
            tenant_id=1,
            actor=request.user,
            actor_kind=AuditLog.ActorKind.USER,
            source=AuditLog.Source.UI,
            action="software_authorization.permit",
            entity_type="operations.product_authorization",
            entity_id=str(product),
            before_state={"superseded_rows": superseded},
            after_state={
                "product_uuid": str(product),
                "capability": capability,
                "client_id": str(client_id) if client_id else None,
                "polarity": True,
                "rationale": reason,
                "via": action.key,
            },
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
        )

    # Imported here: views imports this module.
    from .views import _queue_software_rebuild_after_commit

    _queue_software_rebuild_after_commit(request.user.id)
    scope = "all clients" if all_clients else "the selected clients"
    messages.success(
        request,
        f"Remote access approved for {scope} ({len(targets)} approval"
        f"{'s' if len(targets) != 1 else ''}). The issues close on the next software check.",
    )
    return redirect(back)
