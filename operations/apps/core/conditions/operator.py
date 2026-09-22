"""Operator-facing state derived from finding handling and assessments.

The condition engine has more detail than the Issues queue needs to expose.
This module keeps the translation in one place so cards, filters, rows, and
exports use the same vocabulary without changing persisted engine values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

ATTENTION_NEEDS_ACTION = "needs_action"
ATTENTION_BLOCKED = "blocked"
ATTENTION_PENDING = "pending"
ATTENTION_PAUSED = "paused"

OPERATOR_ATTENTION_CHOICES = (
    ("", "All"),
    (ATTENTION_NEEDS_ACTION, "Needs action"),
    (ATTENTION_BLOCKED, "Blocked"),
    (ATTENTION_PENDING, "Pending"),
)
OPERATOR_ATTENTION_LABELS = dict(OPERATOR_ATTENTION_CHOICES)

OPERATOR_STATUS_CHOICES = (
    ("active", "Open"),
    ("acknowledged", "Acknowledged"),
    ("paused", "Paused"),
    ("resolved", "Resolved"),
)
OPERATOR_STATUS_LABELS = dict(OPERATOR_STATUS_CHOICES)

_CLOSED_STATUSES = {"resolved", "suppressed", "wontfix"}
_ACKNOWLEDGED_STATUSES = {"acknowledged", "investigating"}

_REASON_LABELS = {
    "identity:unsettled_group": "Identity unresolved",
    "identity:readiness_not_established": "Identity unresolved",
    "offline:extended_absence": "Computer offline",
    "collection:incomplete_or_stale": "Source unavailable",
    "patch:incomplete": "Patch data incomplete",
}


def is_paused(status: str, snoozed_until: datetime | None, now: datetime) -> bool:
    return status not in _CLOSED_STATUSES and bool(snoozed_until and snoozed_until > now)


def operator_status(status: str, snoozed_until: datetime | None, now: datetime) -> str:
    if status in _CLOSED_STATUSES:
        return "resolved"
    if is_paused(status, snoozed_until, now):
        return "paused"
    if status in _ACKNOWLEDGED_STATUSES:
        return "acknowledged"
    return "active"


def short_reason(assessment: dict[str, Any] | None) -> str:
    if not assessment:
        return "Pending current assessment"
    if assessment.get("may_execute") and assessment.get("disposition") in {"complete", "eligible", "actionable"}:
        return "Ready for action"
    for reason in (*assessment.get("blockers", ()), *assessment.get("reasons", ())):
        if reason in _REASON_LABELS:
            return _REASON_LABELS[reason]
        suffix = reason.split(":", 1)[-1].replace("_", " ").strip()
        if suffix:
            return suffix[:1].upper() + suffix[1:]
    return "Pending current assessment"


def operator_guidance(
    *, attention: str, reason: str, severity: str = ""
) -> dict[str, str]:
    """Give an operator a safe owner and next step without engine details."""
    guidance = {"owner": "", "next_step": "", "route": ""}
    if attention == ATTENTION_BLOCKED:
        if reason == "Critical issue takes priority":
            guidance = {"owner": "Operator", "next_step": "Open critical issue", "route": "critical"}
        elif reason == "Identity unresolved":
            guidance = {"owner": "Operator", "next_step": "Review identity", "route": "subject"}
        elif reason == "Computer offline":
            guidance = {
                "owner": "Platform administrator",
                "next_step": "Review reporting",
                "route": "reporting",
            }
        elif severity == "critical":
            guidance = {"owner": "Operator", "next_step": "Open critical issue", "route": "subject"}
        else:
            guidance = {"owner": "Operator", "next_step": "Review issue", "route": "subject"}
    elif attention == ATTENTION_PENDING:
        if reason == "Source unavailable":
            guidance = {"owner": "Integration", "next_step": "View source health", "route": "sources"}
        elif reason == "Patch data incomplete":
            guidance = {"owner": "Integration", "next_step": "Review patch collection", "route": "patch"}
        else:
            guidance = {
                "owner": "Automatic reevaluation",
                "next_step": "View coverage status",
                "route": "coverage",
            }
    return guidance


def operator_attention(
    *,
    status: str,
    snoozed_until: datetime | None,
    assessment: dict[str, Any] | None,
    now: datetime,
) -> str:
    if is_paused(status, snoozed_until, now):
        return ATTENTION_PAUSED
    if not assessment:
        return ATTENTION_PENDING
    disposition = assessment.get("disposition")
    if disposition == "blocked" or assessment.get("blockers"):
        return ATTENTION_BLOCKED
    if disposition in {"complete", "eligible", "actionable"} and assessment.get("may_execute"):
        return ATTENTION_NEEDS_ACTION
    return ATTENTION_PENDING


def operator_state(
    *,
    status: str,
    snoozed_until: datetime | None,
    assessment: dict[str, Any] | None,
    now: datetime,
) -> dict[str, str]:
    attention = operator_attention(
        status=status,
        snoozed_until=snoozed_until,
        assessment=assessment,
        now=now,
    )
    return {
        "status": operator_status(status, snoozed_until, now),
        "attention": attention,
        "reason": "Paused by operator"
        if attention == ATTENTION_PAUSED
        else short_reason(assessment),
    }
