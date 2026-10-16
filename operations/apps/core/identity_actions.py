"""Computer identity actions from the Issues queue (ADR-0032).

* Merge these Computers (``duplicate_device_records``): every Computer the
  issue names is merged into the issue's subject (the most recently active
  one) with ``operations.merge_computers``; each merge is recorded and can be
  split again. Refused when the issue names Computers proven to be different
  machines.
* Confirm separate machines (``duplicate_device_records``,
  ``identity_conflict``, ``shared_serial``): records the operator decision
  ``identity_separate`` with ``operations.confirm_computers_separate``; they are
  never proposed as duplicates of each other or merged automatically again.
* Split as proposed (``two_machines_on_one_computer``): detaches the records
  the issue proposes with ``operations.split_computer_records``; the resolver
  matches them again, never to this Computer.

Each database function opens its own recorded change action. The issue is
closed with the resolution; the producer raises it again if the condition is
still there on its next run.
"""

from __future__ import annotations

import json
import uuid

from django.contrib import messages
from django.db import DatabaseError, connection, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from .finding_actions import (
    CONFIRM_COMPUTERS_SEPARATE,
    MERGE_COMPUTERS,
    SPLIT_COMPUTER_RECORDS,
    FindingAction,
)
from .models import Finding

REASON_MAX_LENGTH = 500

_RESOLVE_SQL = """
UPDATE operations.findings
   SET status = 'resolved',
       closed_at = COALESCE(closed_at, now()),
       last_seen_at = now(),
       finding_details = finding_details || %(resolution)s::jsonb
 WHERE tenant_id = 1 AND id = %(id)s AND status IN ('open', 'acknowledged', 'investigating')
"""


def named_computers(finding: Finding) -> list[uuid.UUID]:
    """The Computers an identity issue names, subject first."""
    details = finding.finding_details or {}
    raw = (
        [item.get("device_id") for item in details.get("computers") or []]
        or details.get("candidate_device_ids")
        or details.get("device_ids")
        or []
    )
    ids = [finding.subject_id]
    for value in raw:
        try:
            device_id = uuid.UUID(str(value))
        except ValueError:
            continue
        if device_id not in ids:
            ids.append(device_id)
    return ids


def _refusal(findings: list[Finding], ids: list[str], action: FindingAction, reason: str) -> str:
    """Why the selection cannot be acted on, or an empty string."""
    if not reason:
        return "A reason is required."
    if len(reason) > REASON_MAX_LENGTH:
        return f"Keep the reason to {REASON_MAX_LENGTH} characters or fewer."
    if len(findings) != len(ids):
        return "One or more selected issues are no longer available."
    if any(f.finding_type.name not in action.finding_types for f in findings):
        return f"“{action.label}” does not apply to every selected issue."
    if action.key == MERGE_COMPUTERS.key and any(
        (f.finding_details or {}).get("different_machines") for f in findings
    ):
        return (
            "A selected issue names Computers proven to be different machines; "
            "confirm them separate or merge from the Computer page instead."
        )
    return ""


def _apply(cur, finding: Finding, action: FindingAction, reason: str, actor) -> str:
    """Run the action for one issue; return what was done."""
    if action.key == MERGE_COMPUTERS.key:
        survivor, *others = named_computers(finding)
        for other in others:
            cur.execute(
                """SELECT operations.merge_computers(%s::uuid, %s::uuid, %s::text, %s::jsonb,
                       'operator', %s::bigint, 'operations.ui')""",
                (survivor, other, reason, json.dumps({"finding_id": str(finding.id)}), actor),
            )
        return f"Merged {len(others)} Computer{'s' if len(others) != 1 else ''}."
    if action.key == CONFIRM_COMPUTERS_SEPARATE.key:
        cur.execute(
            "SELECT operations.confirm_computers_separate(%s::uuid[], %s::text, %s::bigint)",
            (named_computers(finding), reason, actor),
        )
        return "Confirmed as separate machines."
    if action.key == SPLIT_COMPUTER_RECORDS.key:
        proposed = (finding.finding_details or {}).get("proposed_split_observation_ids") or []
        if not proposed:
            raise ValueError("A selected issue proposes no records to split off.")
        cur.execute(
            "SELECT operations.split_computer_records(%s::uuid, %s::uuid[], %s::text, %s::bigint)",
            (finding.subject_id, proposed, reason, actor),
        )
        return "Proposed records split off; they are matched again."
    raise ValueError("That action is not available.")


@transaction.atomic
def run_identity_action(request: HttpRequest, ids: list[str], action: FindingAction) -> HttpResponse:
    back = request.POST.get("next") or "findings_queue"
    reason = (request.POST.get("reason") or "").strip()
    findings = list(
        Finding.objects.select_for_update()
        .select_related("finding_type")
        .filter(tenant_id=1, id__in=ids)
    )
    refusal = _refusal(findings, ids, action, reason)
    if refusal:
        messages.warning(request, refusal)
        return redirect(back)

    done = 0
    try:
        with connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            for finding in findings:
                outcome = _apply(cur, finding, action, reason, request.user.id)
                cur.execute(
                    _RESOLVE_SQL,
                    {
                        "id": finding.id,
                        "resolution": json.dumps(
                            {
                                "resolution": {
                                    "reason": action.key,
                                    "detail": outcome,
                                    "comment": reason,
                                    "resolved_by": request.user.get_username(),
                                    "resolved_at": timezone.now().isoformat(),
                                }
                            }
                        ),
                    },
                )
                done += 1
    except (DatabaseError, ValueError) as exc:
        transaction.set_rollback(True)
        messages.error(request, f"Nothing was changed: {str(exc).splitlines()[0]}")
        return redirect(back)
    messages.success(request, f"{action.label}: {done} issue{'s' if done != 1 else ''} done.")
    return redirect(back)
