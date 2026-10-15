"""The Finding types page: every configurable property of a finding, in one place.

A row per finding type holds its display name, category, group, order, default
severity, whether it may alert, whether it resolves itself, the software flags,
and which findings cover it. Categories and groups are edited here too: rename,
reorder. Rules a type is subject to are shown read-only; they are behavior and
change only through a policy version. Staff only; every change is audited.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render

from . import finding_registry
from .conditions.live import load_active_profile
from .models import AuditLog, FindingType

_EDITABLE = (
    "display_name",
    "issue_category",
    "issue_group",
    "sort_order",
    "default_severity",
    "alertable",
    "auto_resolvable",
    "suppressed_by_approval",
    "concern_signal",
    "default_decision_scope",
    "covered_by",
    "cover_note",
)


def type_state(finding_type: FindingType) -> dict[str, Any]:
    return {field: getattr(finding_type, field) for field in _EDITABLE}


def _rows() -> list[dict[str, Any]]:
    return [
        {"name": t.name, **type_state(t)}
        for t in FindingType.objects.order_by("sort_order", "name")
    ]


def blocks(rows: list[dict[str, Any]], key: str) -> list[str]:
    """Distinct categories or groups in the order of their first type."""
    seen: list[str] = []
    for row in sorted(rows, key=lambda r: (r["sort_order"], r["name"])):
        if row[key] not in seen:
            seen.append(row[key])
    return seen


def renumber_after_move(
    rows: list[dict[str, Any]], key: str, label: str, direction: int, category: str = ""
) -> dict[str, int]:
    """New ``sort_order`` per type name after moving a category or group one place.

    Types keep their order inside their block; blocks are renumbered 10, 20, ... so
    a move is just two neighbouring blocks swapping. A group moves only among the
    groups of its own category.
    """
    ordered = sorted(rows, key=lambda r: (r["sort_order"], r["name"]))
    pool = [r for r in ordered if not category or r["issue_category"] == category]
    labels = blocks(pool, key)
    if label not in labels:
        return {}
    index = labels.index(label)
    target = index + direction
    if not 0 <= target < len(labels):
        return {}
    labels[index], labels[target] = labels[target], labels[index]
    moved_names = {r["name"] for r in pool}
    # Rebuild the whole order: untouched rows keep their slots in the sequence.
    sequence: list[str] = []
    placed = False
    for row in ordered:
        if row["name"] in moved_names:
            if not placed:
                for block_label in labels:
                    sequence.extend(r["name"] for r in pool if r[key] == block_label)
                placed = True
        else:
            sequence.append(row["name"])
    return {name: 10 * (position + 1) for position, name in enumerate(sequence)}


def _audit(request: HttpRequest, action: str, entity_id: str, before: dict, after: dict) -> None:
    AuditLog.objects.create(
        tenant_id=1,
        actor=request.user if request.user.is_authenticated else None,
        actor_kind=AuditLog.ActorKind.USER,
        source=AuditLog.Source.UI,
        action=action,
        entity_type="finding_type",
        entity_id=entity_id,
        before_state=before,
        after_state=after,
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:2000],
    )


def _flag(request: HttpRequest, name: str) -> bool:
    return request.POST.get(name) == "on"


def _save_type(request: HttpRequest) -> str:
    finding_type = FindingType.objects.select_for_update().filter(
        name=request.POST.get("type_name")
    ).first()
    if finding_type is None:
        return "Unknown finding type."
    before = type_state(finding_type)
    severity = request.POST.get("default_severity") or finding_type.default_severity
    scope = request.POST.get("default_decision_scope") or finding_type.default_decision_scope
    if severity not in FindingType.Severity.values or scope not in FindingType.DecisionScope.values:
        return "Choose a valid severity and decision scope."
    try:
        sort_order = int(request.POST.get("sort_order") or finding_type.sort_order)
    except ValueError:
        return "Order must be a number."
    proposed = {
        "display_name": (request.POST.get("display_name") or "").strip(),
        "issue_category": (request.POST.get("issue_category") or "").strip(),
        "issue_group": (request.POST.get("issue_group") or "").strip(),
        "sort_order": max(0, min(sort_order, 65_000)),
        "default_severity": severity,
        "alertable": _flag(request, "alertable"),
        "auto_resolvable": _flag(request, "auto_resolvable"),
        "suppressed_by_approval": _flag(request, "suppressed_by_approval"),
        "concern_signal": _flag(request, "concern_signal"),
        "default_decision_scope": scope,
        "covered_by": sorted(set(request.POST.getlist("covered_by"))),
        "cover_note": (request.POST.get("cover_note") or "").strip()[:240],
    }
    rows = [r for r in _rows() if r["name"] != finding_type.name]
    rows.append({"name": finding_type.name, **proposed})
    problems = finding_registry.registry_problems(rows)
    if problems:
        return problems[0]
    for field, value in proposed.items():
        setattr(finding_type, field, value)
    finding_type.save(update_fields=list(proposed))
    finding_registry.invalidate()
    if proposed != before:
        covers_changed = proposed["covered_by"] != before["covered_by"]
        _audit(
            request,
            "finding_type.covers_update" if covers_changed else "finding_type.update",
            finding_type.name,
            before,
            proposed,
        )
    return ""


def _rename(request: HttpRequest, key: str, action: str) -> str:
    old = (request.POST.get("old") or "").strip()
    new = (request.POST.get("new") or "").strip()
    if not new:
        return "Enter a name."
    rows = _rows()
    if not any(r[key] == old for r in rows):
        return "That name no longer exists."
    for row in rows:
        if row[key] == old:
            row[key] = new
    problems = finding_registry.registry_problems(rows)
    if problems:
        return problems[0]
    if new != old:
        FindingType.objects.filter(**{key: old}).update(**{key: new})
        finding_registry.invalidate()
        _audit(request, action, old, {key: old}, {key: new})
    return ""


def _move(request: HttpRequest, key: str, action: str) -> str:
    label = request.POST.get("label") or ""
    direction = -1 if request.POST.get("direction") == "up" else 1
    category = request.POST.get("category") or ""
    rows = _rows()
    changes = renumber_after_move(rows, key, label, direction, category)
    if not changes:
        return ""
    for name, order in changes.items():
        FindingType.objects.filter(name=name).update(sort_order=order)
    finding_registry.invalidate()
    _audit(request, action, label, {"direction": direction}, {"moved": label})
    return ""


_HANDLERS = {
    "save_type": _save_type,
    "rename_category": lambda r: _rename(r, "issue_category", "finding_category.rename"),
    "rename_group": lambda r: _rename(r, "issue_group", "finding_group.rename"),
    "move_category": lambda r: _move(r, "issue_category", "finding_category.move"),
    "move_group": lambda r: _move(r, "issue_group", "finding_group.move"),
}


@login_required
def finding_types_config(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        if not request.user.is_staff:
            return HttpResponseForbidden("Only staff can change finding types.")
        handler = _HANDLERS.get(request.POST.get("action") or "")
        if handler is None:
            messages.error(request, "Unknown action.")
        else:
            with transaction.atomic():
                error = handler(request)
            if error:
                messages.error(request, error)
            else:
                messages.info(request, "Saved.")
        return redirect("finding_types_config")

    rows = _rows()
    types = list(FindingType.objects.order_by("sort_order", "name"))
    try:
        definitions = load_active_profile().definitions
    except RuntimeError:  # the policy is shown for reference only
        definitions = {}
    categories = []
    for category in blocks(rows, "issue_category"):
        groups = []
        for group in blocks([r for r in rows if r["issue_category"] == category], "issue_group"):
            groups.append(
                {
                    "label": group,
                    "types": [
                        {
                            "type": t,
                            "policy": definitions.get(t.name, {}),
                            "covers": [r["display_name"] for r in rows if t.name in r["covered_by"]],
                        }
                        for t in types
                        if t.issue_category == category and t.issue_group == group
                    ],
                }
            )
        categories.append({"label": category, "groups": groups})
    return render(
        request,
        "finding_types.html",
        {
            "admin_group": "config",
            "admin_tab": "finding_types",
            "categories": categories,
            "all_types": [{"name": r["name"], "display_name": r["display_name"]} for r in rows],
            "category_names": blocks(rows, "issue_category"),
            "group_names": blocks(rows, "issue_group"),
            "severities": FindingType.Severity.choices,
            "scopes": FindingType.DecisionScope.choices,
            "can_edit": request.user.is_staff,
        },
    )
