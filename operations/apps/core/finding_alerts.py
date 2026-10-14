"""Alert eligibility: which finding types may notify at all.

``finding_types.alertable`` is data with an admin surface. It only permits a
notification (alert or digest line); notification rules and routes still decide
where a finding goes. Every change is audited; only staff may change it.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render

from .models import AuditLog, FindingType


def _audit(request: HttpRequest, finding_type: FindingType, before: bool, after: bool) -> None:
    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user if request.user.is_authenticated else None,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action="finding_type.alertable_update",
        entity_type="finding_type",
        entity_id=str(finding_type.id),
        before_state={"name": finding_type.name, "alertable": before},
        after_state={"name": finding_type.name, "alertable": after},
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
    )


def _save_alertable(request: HttpRequest) -> int:
    """Apply the submitted checkboxes; return how many types changed."""
    wanted = {int(v) for v in request.POST.getlist("alertable") if v.isdigit()}
    changed = 0
    for finding_type in FindingType.objects.select_for_update().all():
        after = finding_type.id in wanted
        if after != finding_type.alertable:
            before = finding_type.alertable
            finding_type.alertable = after
            finding_type.save(update_fields=["alertable"])
            _audit(request, finding_type, before, after)
            changed += 1
    return changed


@login_required
def finding_alert_eligibility(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        if not request.user.is_staff:
            return HttpResponseForbidden("Only staff can change alert eligibility.")
        with transaction.atomic():
            changed = _save_alertable(request)
        messages.info(
            request,
            f"Alert eligibility saved. {changed} finding type(s) changed."
            if changed
            else "No changes.",
        )
        return redirect("finding_alert_eligibility")

    types = list(FindingType.objects.order_by("name"))
    return render(
        request,
        "finding_alert_eligibility.html",
        {
            "admin_group": "config",
            "admin_tab": "alerts",
            "finding_types": types,
            "alertable_count": sum(1 for t in types if t.alertable),
            "can_edit": request.user.is_staff,
        },
    )
