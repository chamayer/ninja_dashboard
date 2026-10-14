"""Decide undecided software from the Issues queue.

An undecided title is a finding (``rare_recent`` or ``whitelist_suggestion``).
These registered actions record the same global SoftwareDecision the review
page records, then close the prompts the decision answers and queue a software
check. Remote access is a separate decision (remote_access_approval) and is not
written here.
"""

from __future__ import annotations

from django.contrib import messages
from django.db import connection, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from . import software_review
from .finding_actions import FindingAction
from .models import AuditLog, Finding, SoftwareDecision

REASON_MAX_LENGTH = 500

def decision_for(action_key: str):
    """(decision recorded, whether the match key is the publisher) for an action key."""
    match action_key:
        case "software_approve_title":
            return SoftwareDecision.Decision.APPROVE, False
        case "software_approve_publisher":
            return SoftwareDecision.Decision.APPROVE_PUBLISHER, True
        case "software_reject":
            return SoftwareDecision.Decision.REJECT, False
        case "software_investigate":
            return SoftwareDecision.Decision.INVESTIGATE, False
    return None


def match_values(findings: list, by_publisher: bool) -> tuple[dict[str, str], int]:
    """Distinct title or publisher values (case-insensitive) and how many had none."""
    keys: dict[str, str] = {}
    skipped = 0
    for finding in findings:
        details = finding.finding_details or {}
        value = str(details.get("publisher" if by_publisher else "canonical_name") or "").strip()
        if not value:
            skipped += 1
            continue
        keys.setdefault(value.lower(), value)
    return keys, skipped


@transaction.atomic
def decide_software(request: HttpRequest, ids: list[str], action: FindingAction) -> HttpResponse:
    back = request.POST.get("next") or "findings_queue"
    reason = (request.POST.get("reason") or "").strip()
    if len(reason) > REASON_MAX_LENGTH:
        messages.warning(request, f"Keep the reason to {REASON_MAX_LENGTH} characters or fewer.")
        return redirect(back)
    decision, by_publisher = decision_for(action.key)

    findings = list(Finding.objects.select_related("finding_type").filter(tenant_id=1, id__in=ids))
    if len(findings) != len(ids):
        messages.warning(request, "One or more selected issues are no longer available.")
        return redirect(back)
    if any(f.finding_type.name not in action.finding_types for f in findings):
        messages.warning(request, "That decision can only be made on undecided software.")
        return redirect(back)

    keys, skipped = match_values(findings, by_publisher)
    if not keys:
        messages.warning(
            request,
            "None of the selected issues has a publisher to approve."
            if by_publisher
            else "None of the selected issues names a title.",
        )
        return redirect(back)

    now = timezone.now()
    for value in keys.values():
        obj, _created = SoftwareDecision.objects.update_or_create(
            tenant_id=1,
            canonical_name="" if by_publisher else value,
            publisher=value if by_publisher else "",
            client=None,
            device=None,
            defaults={
                "decision": decision,
                "reason": reason,
                "decided_by": request.user,
                "decided_at": now,
            },
        )
        AuditLog.objects.create(
            tenant_id=1,
            actor=request.user,
            actor_kind=AuditLog.ActorKind.USER,
            source=AuditLog.Source.UI,
            action="software_decision.set",
            entity_type="operations.software_decision",
            entity_id=str(obj.id),
            before_state={},
            after_state={
                "canonical_name": obj.canonical_name,
                "publisher": obj.publisher,
                "scope": "global",
                "decision": str(decision),
                "via": action.key,
            },
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
        )
    with connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        software_review.resolve_decided_prompts(
            cur,
            tenant_id=1,
            canonical_names=[] if by_publisher else list(keys.values()),
            publishers=list(keys.values()) if by_publisher else [],
            decision=str(decision),
            actor=request.user.get_username(),
            decided_at=now.isoformat(),
        )

    # Imported here: views imports this module.
    from .views import _queue_software_rebuild_after_commit, _refresh_software_risk_matview

    transaction.on_commit(_refresh_software_risk_matview)
    _queue_software_rebuild_after_commit(request.user.id)
    message = (
        f"{decision.label} recorded for {len(keys)} "
        f"{'publisher' if by_publisher else 'title'}{'s' if len(keys) != 1 else ''}."
    )
    if skipped:
        message += f" Skipped {skipped} issue{'s' if skipped != 1 else ''} with nothing to match."
    messages.success(request, message)
    return redirect(back)
