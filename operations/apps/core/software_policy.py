"""Software review policy: the data that tunes software findings, in one page.

User decision 2026-10-13: everything that tunes software findings is data with
an Operations admin surface. This page edits the software finding types'
policy fields, the classifier rules (name, install-path, end-of-life and
junk-publisher patterns) and the suggestion rules. Every change is audited;
only staff may change anything.
"""

from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    AuditLog,
    FindingType,
    SoftwareClassifierRule,
    SoftwareSuggestionRule,
)


def _software_types():
    # The software emitters' registered source modules (code identity, not a
    # domain mapping).
    return FindingType.objects.filter(
        source_module__in=["platform.software_findings", "platform.capability_match"]
    )


def _type_fields() -> list[str]:
    return [
        "default_severity", "suppressed_by_approval", "concern_signal",
        "default_decision_scope", "auto_resolvable",
    ]


def _audit(request: HttpRequest, action: str, entity_type: str, entity_id, before, after) -> None:
    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user if request.user.is_authenticated else None,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before_state=before,
        after_state=after,
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
    )


def _type_state(finding_type: FindingType) -> dict:
    return {field: getattr(finding_type, field) for field in _type_fields()}


def _update_type(request: HttpRequest) -> str:
    finding_type = get_object_or_404(_software_types(), id=request.POST.get("type_id"))
    before = _type_state(finding_type)
    severity = request.POST.get("default_severity") or finding_type.default_severity
    scope = request.POST.get("default_decision_scope") or finding_type.default_decision_scope
    if severity not in FindingType.Severity.values or scope not in FindingType.DecisionScope.values:
        return "Choose a valid severity and decision scope."
    finding_type.default_severity = severity
    finding_type.default_decision_scope = scope
    for flag in ("suppressed_by_approval", "concern_signal", "auto_resolvable"):
        setattr(finding_type, flag, request.POST.get(flag) == "on")
    after = _type_state(finding_type)
    if after != before:
        finding_type.save(update_fields=_type_fields())
        _audit(request, "finding_type.policy_update", "finding_type", finding_type.id, before, after)
    return ""


def _add_rule(request: HttpRequest) -> str:
    rule_type = request.POST.get("rule_type") or ""
    pattern = (request.POST.get("pattern") or "").strip()
    is_regex = request.POST.get("is_regex") == "on"
    if rule_type not in SoftwareClassifierRule.RuleType.values or not pattern:
        return "Choose a rule type and enter a pattern."
    if is_regex:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"The pattern is not a valid regular expression: {exc}."
    rule, created = SoftwareClassifierRule.objects.get_or_create(
        rule_type=rule_type,
        pattern=pattern,
        defaults={"is_regex": is_regex, "note": (request.POST.get("note") or "")[:240]},
    )
    if not created:
        return "That rule already exists."
    _audit(request, "software_rule.add", "software_classifier_rule", rule.id, {},
           {"rule_type": rule_type, "pattern": pattern, "is_regex": is_regex})
    return ""


def _toggle_rule(request: HttpRequest) -> str:
    rule = get_object_or_404(SoftwareClassifierRule, id=request.POST.get("rule_id"))
    rule.enabled = not rule.enabled
    rule.save(update_fields=["enabled"])
    _audit(request, "software_rule.toggle", "software_classifier_rule", rule.id,
           {"enabled": not rule.enabled}, {"enabled": rule.enabled})
    return ""


def _update_suggestion(request: HttpRequest) -> str:
    rule = get_object_or_404(SoftwareSuggestionRule, id=request.POST.get("rule_id"))
    before = {"priority": rule.priority, "adverse": rule.adverse,
              "suggestion": rule.suggestion, "enabled": rule.enabled}
    suggestion = request.POST.get("suggestion") or rule.suggestion
    try:
        priority = max(0, min(int(request.POST.get("priority") or rule.priority), 32767))
    except ValueError:
        return "Priority must be a number."
    if suggestion not in SoftwareSuggestionRule.Suggestion.values:
        return "Choose a valid suggestion."
    rule.priority = priority
    rule.suggestion = suggestion
    rule.adverse = request.POST.get("adverse") == "on"
    rule.enabled = request.POST.get("enabled") == "on"
    after = {"priority": rule.priority, "adverse": rule.adverse,
             "suggestion": rule.suggestion, "enabled": rule.enabled}
    if after != before:
        rule.save(update_fields=["priority", "adverse", "suggestion", "enabled"])
        _audit(request, "software_suggestion_rule.update", "software_suggestion_rule", rule.id,
               before, after)
    return ""


@login_required
def software_policy_config(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        if not request.user.is_staff:
            return HttpResponseForbidden("Only staff can change software policy.")
        handler = {
            "type_update": _update_type,
            "rule_add": _add_rule,
            "rule_toggle": _toggle_rule,
            "suggestion_update": _update_suggestion,
        }.get(request.POST.get("action") or "")
        if handler is None:
            messages.error(request, "Unknown action.")
        else:
            with transaction.atomic():
                error = handler(request)
            if error:
                messages.error(request, error)
            else:
                messages.info(request, "Software policy saved. It applies on the next software run.")
        return redirect("software_policy_config")

    return render(
        request,
        "software_policy_config.html",
        {
            "admin_group": "config",
            "admin_tab": "software_policy",
            "finding_types": _software_types().order_by("name"),
            "rules": SoftwareClassifierRule.objects.order_by("rule_type", "pattern"),
            "suggestion_rules": SoftwareSuggestionRule.objects.order_by("priority", "id"),
            "severity_choices": FindingType.Severity.choices,
            "scope_choices": FindingType.DecisionScope.choices,
            "rule_type_choices": SoftwareClassifierRule.RuleType.choices,
            "suggestion_choices": SoftwareSuggestionRule.Suggestion.choices,
            "can_edit": request.user.is_staff,
        },
    )
