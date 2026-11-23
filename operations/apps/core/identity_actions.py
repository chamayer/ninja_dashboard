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
* Still in use (``device_missing_from_source``): records ``in_use_confirmed``
  with ``operations.confirm_computers_in_use``; the Computer returns to the
  coverage check and is not retired automatically until it reports again.
* ``computer_client_conflict`` (ADR-0040): Move to the other client runs
  ``operations.move_computer_to_client``; Keep as is records the evidence with
  ``operations.accept_computer_client_conflict`` (for a shared serial, on both
  Computers); Source is wrong acknowledges the issue, which clears once the
  source is corrected.

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
from shared.identity_evidence import (
    CONFLICT_RULE_REVISION,
    assess_identifier_group,
    current_client_scopes,
    hostname_conflict,
    operator_separated_pairs,
    split_assessment,
    usable_serial,
)

from .computer_naming import name_now
from .finding_actions import (
    COMPUTER_CLIENT_SOURCE_WRONG,
    CONFIRM_COMPUTERS_IN_USE,
    CONFIRM_COMPUTERS_SEPARATE,
    KEEP_COMPUTER_CLIENT,
    MERGE_COMPUTERS,
    MOVE_COMPUTER_CLIENT,
    SPLIT_COMPUTER_RECORDS,
    FindingAction,
)
from .models import Finding

REASON_MAX_LENGTH = 500


class IdentityEvidenceConflict(ValueError):
    """Current evidence conflicts with a proposed Computer grouping."""

    def __init__(self, message: str, observation_ids: list[str]) -> None:
        super().__init__(message)
        self.observation_ids = observation_ids


class IdentityEvidenceIncomplete(ValueError):
    """Current evidence is insufficient for the automatic conflict check."""

    def __init__(self, observation_ids: list[str]) -> None:
        super().__init__("Current identity evidence is incomplete.")
        self.observation_ids = observation_ids


_RESOLVE_SQL = """
UPDATE operations.findings
   SET status = 'resolved',
       closed_at = COALESCE(closed_at, now()),
       last_seen_at = now(),
       finding_details = finding_details || %(resolution)s::jsonb
 WHERE tenant_id = 1 AND id = %(id)s AND status IN ('open', 'acknowledged', 'investigating')
"""

# Fixed at the source: the issue stays visible, acknowledged, until it clears.
_ACKNOWLEDGE_SQL = """
UPDATE operations.findings
   SET status = 'acknowledged',
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
    return _destination_refusal(findings, action)


def _destination_refusal(findings: list[Finding], action: FindingAction) -> str:
    """A Computer moves only to the one other client its evidence names."""
    if action.key == KEEP_COMPUTER_CLIENT.key and any(
        not (f.finding_details or {}).get("evidence") for f in findings
    ):
        return "A selected issue has no evidence to keep; review its source records first."
    if action.key == MOVE_COMPUTER_CLIENT.key and any(
        not (f.finding_details or {}).get("move_to_client_id") for f in findings
    ):
        return (
            "A selected issue's evidence names more than one other client, so it has no "
            "single destination; decide it on its own."
        )
    return ""


def _merge_evidence_rows(rows, device_ids: list[uuid.UUID], rejected: set[str]) -> tuple[dict, list[str]]:
    """Prepare current identity signals without exposing restricted values."""
    evidence = {device_id: {"serials": set(), "vm_uuids": set(), "records": 0}
                for device_id in device_ids}
    observation_ids = []
    reports = []
    for device_id, platform, entity_type, raw_serial, raw_vm_uuid, seen, restricted, name, roaming, observation_id in rows:
        if restricted:
            raise ValueError("Identity evidence is restricted; review the Computers directly.")
        item = evidence[device_id]
        observation_ids.append(str(observation_id))
        if roaming:
            continue
        serial = raw_serial.strip().lower() if usable_serial(raw_serial, rejected) else None
        vm_uuid = (raw_vm_uuid or "").strip().lower() or None
        if serial:
            item["serials"].add(serial)
        if vm_uuid:
            item["vm_uuids"].add(vm_uuid)
        if serial or vm_uuid or (name and name.strip()):
            item["records"] += 1
        reports.append((platform, entity_type, name, serial, vm_uuid, seen))
    if any(not item["records"] for item in evidence.values()):
        raise IdentityEvidenceIncomplete(sorted(observation_ids))
    if hostname_conflict(reports):
        raise IdentityEvidenceConflict("Current source records conflict.", sorted(observation_ids))
    return evidence, observation_ids


def _check_current_merge_evidence(cur, tenant_id: int, device_ids: list[uuid.UUID]) -> dict:
    """Reject a saved Issues merge when current identity evidence conflicts."""
    cur.execute(
        "SELECT normalized_value FROM operations.identity_value_rejections "
        "WHERE value_kind = 'serial' AND enabled"
    )
    rejected = {row[0] for row in cur.fetchall()}
    cur.execute(
        """
        SELECT meta.device_id, meta.platform, meta.entity_type, meta.canonical_serial,
               meta.vm_uuid, meta.last_seen_at, meta.restricted,
               CASE WHEN coalesce(lc.record_lifecycle, '') <> 'archived'
                          AND coalesce(forms.name_key, '') <> ''
                    THEN forms.name_short ELSE '' END,
               (roaming.external_id IS NOT NULL), meta.observation_id
          FROM operations.v_entity_observation_admin_metadata meta
          JOIN operations.entity_types typ ON typ.name = meta.entity_type AND typ.is_identity_signal
          LEFT JOIN operations.identity_roaming_records roaming
            ON roaming.tenant_id = meta.tenant_id
           AND roaming.source_instance_id = meta.source_instance_id
           AND roaming.external_id = meta.external_id
          LEFT JOIN operations.v_device_source_record_lifecycle_current lc
            ON lc.observation_id = meta.observation_id
         CROSS JOIN LATERAL operations.record_name_forms(
             meta.platform, meta.entity_type, meta.reported_name, meta.canonical_domain) forms
         WHERE meta.tenant_id = %s AND meta.device_id = ANY(%s::uuid[]) AND meta.active
        """,
        (tenant_id, device_ids),
    )
    rows = cur.fetchall()
    separated = operator_separated_pairs(cur, tenant_id, device_ids, observation_metadata=True)
    if any((a, b) in separated for a in device_ids for b in device_ids if a != b):
        raise ValueError("An existing separation decision prevents this merge; review that decision first.")
    evidence, observation_ids = _merge_evidence_rows(rows, device_ids, rejected)
    assessment = assess_identifier_group(
        serial_groups=[evidence[device_id]["serials"] for device_id in device_ids],
        vm_uuid_groups=[evidence[device_id]["vm_uuids"] for device_id in device_ids],
    )
    if assessment.outcome == "different":
        raise IdentityEvidenceConflict(
            "Current identity evidence conflicts.", sorted(observation_ids)
        )
    return {
        "observation_ids": sorted(observation_ids),
        "machine_outcome": assessment.outcome,
        "machine_reason": assessment.reason,
    }


def _split_fingerprint(details: dict) -> tuple | None:
    """Capture the dividing values and record memberships of a split proposal."""
    kind = details.get("divided_by")
    machines = details.get("machines")
    if kind not in {"serial", "vm_uuid", "hostname"} or not isinstance(machines, list):
        return None
    try:
        groups = tuple(sorted(
            (str(machine[kind]), bool(machine["keep"]),
             tuple(sorted(str(record["observation_id"]) for record in machine["records"])))
            for machine in machines
        ))
    except (KeyError, TypeError):
        return None
    return kind, groups


def _check_current_split_evidence(cur, finding: Finding, proposed: list) -> None:
    """Reassess the whole Computer before applying a saved split proposal."""
    scopes = current_client_scopes(cur, finding.tenant_id, [finding.subject_id], lock=True, batch=False)
    if scopes is None or scopes.get(finding.subject_id) != finding.client_id:
        raise ValueError("Computer ownership changed or is unresolved; review the issue again.")
    cur.execute(
        "SELECT normalized_value FROM operations.identity_value_rejections "
        "WHERE value_kind = 'serial' AND enabled"
    )
    rejected = {row[0] for row in cur.fetchall()}
    cur.execute(
        """
        SELECT d.canonical_hostname, meta.observation_id, meta.platform, meta.entity_type,
               CASE WHEN roaming.external_id IS NULL AND coalesce(lc.record_lifecycle, '') <> 'archived'
                          AND coalesce(forms.name_key, '') <> ''
                    THEN coalesce(forms.name_short, '') ELSE '' END,
               meta.canonical_serial, meta.vm_uuid, meta.reported_online, meta.last_seen_at,
               meta.restricted, (roaming.external_id IS NOT NULL)
          FROM operations.devices d
          JOIN operations.v_entity_observation_admin_metadata meta
            ON meta.tenant_id = d.tenant_id AND meta.device_id = d.id AND meta.active
          JOIN operations.entity_types typ ON typ.name = meta.entity_type AND typ.is_identity_signal
          LEFT JOIN operations.identity_roaming_records roaming
            ON roaming.tenant_id = meta.tenant_id AND roaming.source_instance_id = meta.source_instance_id
           AND roaming.external_id = meta.external_id
          LEFT JOIN operations.v_device_source_record_lifecycle_current lc
            ON lc.observation_id = meta.observation_id
         CROSS JOIN LATERAL operations.record_name_forms(
             meta.platform, meta.entity_type, meta.reported_name, meta.canonical_domain) forms
         WHERE d.tenant_id = %s AND d.id = %s AND d.deleted_at IS NULL
        """,
        (finding.tenant_id, finding.subject_id),
    )
    rows = cur.fetchall()
    if not rows or any(row[9] for row in rows):
        raise ValueError("Current identity evidence is incomplete or restricted; review the issue again.")
    records = []
    for _, observation_id, platform, entity_type, name, serial, vm_uuid, online, seen, _, roaming in rows:
        records.append({
            "observation_id": observation_id, "platform": platform, "entity_type": entity_type,
            "stream": f"{platform}:{entity_type}", "hostname": name,
            "serial": serial.strip().lower() if not roaming and usable_serial(serial, rejected) else None,
            "vm_uuid": vm_uuid.strip().lower() if not roaming and vm_uuid and vm_uuid.strip() else None,
            "online": bool(online), "last_seen_at": seen, "roaming": roaming,
        })
    current = split_assessment(rows[0][0] or "", records, timezone.now())
    saved = finding.finding_details or {}
    if (
        current is None or _split_fingerprint(saved) is None
        or _split_fingerprint(saved) != _split_fingerprint(current)
        or set(map(str, proposed)) != set(current["proposed_split_observation_ids"])
        or len(proposed) != len(set(map(str, proposed)))
    ):
        raise ValueError("The split evidence changed; review the issue again.")


def _apply(cur, finding: Finding, action: FindingAction, reason: str, actor) -> str:
    """Run the action for one issue; return what was done."""
    if action.key == MERGE_COMPUTERS.key:
        survivor, *others = named_computers(finding)
        if not others:
            raise ValueError("The issue no longer identifies another Computer to merge.")
        scopes = current_client_scopes(
            cur, finding.tenant_id, [survivor, *others], lock=True, batch=False
        )
        if scopes is None or len(set(scopes.values())) != 1:
            raise ValueError("Computer ownership changed or is unresolved; review the issue again.")
        evidence = _check_current_merge_evidence(cur, finding.tenant_id, [survivor, *others])
        for other in others:
            cur.execute(
                """SELECT operations.merge_computers(%s::uuid, %s::uuid, %s::text, %s::jsonb,
                       'operator', %s::bigint, 'operations.ui')""",
                (survivor, other, reason, json.dumps({"finding_id": str(finding.id),
                 "conflict_rule_revision": CONFLICT_RULE_REVISION, **evidence}), actor),
            )
        name_now(cur, [survivor, *others])
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
        _check_current_split_evidence(cur, finding, proposed)
        cur.execute(
            "SELECT operations.split_computer_records(%s::uuid, %s::uuid[], %s::text, %s::bigint)",
            (finding.subject_id, proposed, reason, actor),
        )
        name_now(cur, [finding.subject_id])
        return "Proposed records split off; they are matched again."
    if action.key == CONFIRM_COMPUTERS_IN_USE.key:
        cur.execute(
            "SELECT operations.confirm_computers_in_use(%s::uuid[], %s::text, %s::bigint)",
            ([finding.subject_id], reason, actor),
        )
        return "Confirmed in use; missing agents are reported."
    return _apply_client_conflict(cur, finding, action, reason, actor)


def _apply_client_conflict(cur, finding: Finding, action: FindingAction, reason: str, actor) -> str:
    """Move, keep or mark as a source error a Computer linked to another client."""
    details = finding.finding_details or {}
    if action.key == MOVE_COMPUTER_CLIENT.key:
        cur.execute(
            "SELECT operations.move_computer_to_client(%s::uuid, %s::uuid, %s::text, %s::bigint)",
            (finding.subject_id, details["move_to_client_id"], reason, actor),
        )
        target = next(
            (
                e.get("client")
                for e in details.get("evidence") or []
                if e.get("client_id") == details["move_to_client_id"]
            ),
            "",
        )
        return f"Moved to {target or 'the other client'}."
    if action.key == KEEP_COMPUTER_CLIENT.key:
        evidence = details.get("evidence") or []
        cur.execute(
            "SELECT operations.accept_computer_client_conflict(%s::uuid, %s::text[], %s::text, %s::bigint)",
            (finding.subject_id, [e["key"] for e in evidence], reason, actor),
        )
        # A shared serial is one decision for both Computers.
        for twin in {e["device_id"] for e in evidence if e.get("kind") == "serial"}:
            cur.execute(
                "SELECT operations.accept_computer_client_conflict(%s::uuid, %s::text[], %s::text, %s::bigint)",
                (twin, [f"serial:{finding.subject_id}"], reason, actor),
            )
        return "Kept as is."
    if action.key == COMPUTER_CLIENT_SOURCE_WRONG.key:
        return "Marked as a source filing error; clears when the source is corrected."
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
                    _ACKNOWLEDGE_SQL
                    if action.key == COMPUTER_CLIENT_SOURCE_WRONG.key
                    else _RESOLVE_SQL,
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
    if done:
        from .views import _queue_software_overview

        _queue_software_overview(request.user.id)
    messages.success(request, f"{action.label}: {done} issue{'s' if done != 1 else ''} done.")
    return redirect(back)
