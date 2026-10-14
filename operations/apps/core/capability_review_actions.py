"""Confirm or reject a product capability from the Issues queue.

A ``capability_review_candidate`` finding says rule-based evidence suggests a
product has a capability (remote access, endpoint security, RMM) that a curator
has not yet judged. This records the same global curator decision the product
page records, then resolves the matching findings with a recorded reason, since
no software run produces or closes these findings.
"""

from __future__ import annotations

import json
import uuid

from django.contrib import messages
from django.db import IntegrityError, connection, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from . import capability as capability_evidence
from .finding_actions import CAPABILITY_CONFIRM, FindingAction
from .models import AuditLog, Finding

REASON_MAX_LENGTH = 500

_RESOLVE_SQL = """
UPDATE operations.findings finding
   SET status = 'resolved',
       closed_at = COALESCE(finding.closed_at, now()),
       last_seen_at = now(),
       finding_details = finding.finding_details || %(resolution)s::jsonb
  FROM operations.finding_types finding_type
 WHERE finding_type.id = finding.finding_type_id
   AND finding_type.name = 'capability_review_candidate'
   AND finding.tenant_id = 1
   AND finding.status IN ('open', 'acknowledged')
   AND finding.finding_details->>'product_uuid' = %(product)s
   AND finding.finding_details->>'capability' = %(capability)s
"""


def targets(findings: list[Finding]) -> set[tuple[uuid.UUID, str]]:
    """The distinct (product, capability) judgements the selection asks for."""
    found = set()
    for finding in findings:
        details = finding.finding_details or {}
        try:
            product = uuid.UUID(str(details["product_uuid"]))
        except (KeyError, ValueError):
            raise ValueError("A selected issue does not name a product.") from None
        capability = str(details.get("capability") or "")
        if not capability:
            raise ValueError("A selected issue does not name a capability.")
        found.add((product, capability))
    return found


@transaction.atomic
def decide_capability(request: HttpRequest, ids: list[str], action: FindingAction) -> HttpResponse:
    back = request.POST.get("next") or "findings_queue"
    reason = (request.POST.get("reason") or "").strip()
    if len(reason) > REASON_MAX_LENGTH:
        messages.warning(request, f"Keep the reason to {REASON_MAX_LENGTH} characters or fewer.")
        return redirect(back)
    findings = list(Finding.objects.select_related("finding_type").filter(tenant_id=1, id__in=ids))
    if len(findings) != len(ids):
        messages.warning(request, "One or more selected issues are no longer available.")
        return redirect(back)
    if any(f.finding_type.name not in action.finding_types for f in findings):
        messages.warning(request, "That decision can only be made on capability review issues.")
        return redirect(back)
    try:
        wanted = targets(findings)
    except ValueError as exc:
        messages.warning(request, str(exc))
        return redirect(back)

    confirm = action.key == CAPABILITY_CONFIRM.key
    now = timezone.now()
    username = request.user.get_username()
    resolved = 0
    for product, capability in sorted(wanted, key=str):
        try:
            # Nested, so one rejected input does not poison the audit trail.
            with transaction.atomic():
                capability_evidence.confirm(str(product), capability, confirm, username, reason)
        except (capability_evidence.CapabilitySchemaUnavailable, IntegrityError, ValueError) as exc:
            messages.error(request, str(exc))
            return redirect(back)
        AuditLog.objects.create(
            tenant_id=1,
            actor=request.user,
            actor_kind=AuditLog.ActorKind.USER,
            source=AuditLog.Source.UI,
            action="software_capability.confirm" if confirm else "software_capability.reject",
            entity_type="catalog.product_capability",
            entity_id=str(product),
            before_state={},
            after_state={
                "product_uuid": str(product),
                "capability": capability,
                "polarity": confirm,
                "rationale": reason,
                "via": action.key,
            },
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
        )
        resolution = json.dumps({"resolution": {
            "reason": "capability_decided",
            "detail": f"A curator {'confirmed' if confirm else 'rejected'} this capability.",
            "resolved_by": username,
            "resolved_at": now.isoformat(),
        }})
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                _RESOLVE_SQL,
                {"resolution": resolution, "product": str(product), "capability": capability},
            )
            resolved += max(cur.rowcount, 0)

    messages.success(
        request,
        f"Capability {'confirmed' if confirm else 'rejected'} for {len(wanted)} "
        f"product{'s' if len(wanted) != 1 else ''}; {resolved} issue{'s' if resolved != 1 else ''} closed.",
    )
    return redirect(back)
