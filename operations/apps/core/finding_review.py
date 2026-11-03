"""Read-only issue explanations and bounded, safe review evidence."""

from __future__ import annotations

import json
import uuid

from django.db import connection
from django.urls import reverse

from apps.core.finding_actions import available_finding_actions
from apps.core.computer_reads import effectively_owned_device_ids
from apps.core.models import Device
from apps.core.source_record_views import _rows, load_subject
from apps.core.templatetags.human_labels import finding_detail_text

MAX_COMPUTERS = 10
MAX_RECORDS = 50
IDENTIFIERS = {"serial": "Serial number", "vm_uuid": "VM UUID", "mac": "MAC address"}


def _object(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _uuid(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def review_context(finding, user, *, tenant_id: int) -> dict:
    """Use existing action handlers; GET never decides or refreshes anything."""
    details = _object(finding.finding_details)
    name = finding.finding_type.name
    actions = [
        action
        for action in available_finding_actions(user)
        if name in action.finding_types
        and finding.status in {"open", "acknowledged", "investigating"}
    ]
    context = {
        "summary": finding_detail_text(finding)
        if isinstance(finding.finding_details, dict)
        else "",
        "explanation": finding.finding_type.description or "",
        "facts": [],
        "computers": [],
        "actions": actions,
        "reason_required": any(action.requires_reason for action in actions),
        "steps": [],
    }
    if name == "computer_client_conflict" and details.get("ownership_state"):
        context["explanation"] = (
            "The Computer's client is determined from its current source records and any "
            "recorded client decision. Review the source records and decision before changing it."
        )
        if finding.subject_id:
            context["computers"] = _comparison_computers(
                {str(finding.subject_id): ["Computer to review"]}, {}, tenant_id
            )
        if not details.get("evidence"):
            context["actions"] = []
            context["reason_required"] = False
            context["steps"] = [
                "Check whether the source records are current and assigned to the correct client.",
                "Review any earlier client decision before changing the Computer's ownership.",
            ]
    # Show known useful facts, never an arbitrary raw payload or internal IDs.
    for key, label in (
        ("publisher", "Publisher"),
        ("version", "Version"),
        ("platform", "Source"),
        ("last_seen_at", "Last source evidence"),
        ("last_contact_at", "Last contact"),
        ("last_patch_seen_at", "Last patch activity"),
        ("backlog_count", "Updates awaiting installation"),
    ):
        value = details.get(key)
        if value is not None and value != "" and isinstance(value, str | int | float):
            context["facts"].append({"label": label, "value": value})
    if finding.subject_type == "source_record":
        context.update(_source_record_review(finding, details, tenant_id))
    elif finding.subject_type == "source_record_case":
        context["subject_url"] = reverse(
            "source_record_case_detail", kwargs={"case_id": finding.subject_id}
        )
        context["subject_label"] = "Source-record investigation"
        context["steps"] = [
            "Compare the source records in the investigation and check whether they describe the same machine.",
            "Use the investigation's duplicate decision only after comparing its members and related cases.",
        ]
    if not context["summary"]:
        context["summary"] = context["explanation"] or "The recorded condition needs review."
    if not context["steps"]:
        context["steps"] = [
            "Check the affected subject and the evidence recorded at last detection.",
            "Use an available decision below, or correct the condition in the linked system. A later assessment checks whether it has cleared.",
        ]
    return context


def _source_record_review(finding, details: dict, tenant_id: int) -> dict:
    context = {
        "subject_url": reverse("source_record_detail", kwargs={"subject_id": finding.subject_id}),
        "subject_label": "Source record",
        "facts": [],
        "computers": [],
        "steps": [],
        "summary": "The source record needs review.",
        "explanation": "",
        "record_limited": False,
    }
    with connection.cursor() as cur:
        subject = load_subject(cur, tenant_id, finding.subject_id)
    # Fail closed when the safe metadata is absent, not just explicitly restricted.
    if subject is None or subject.get("restricted") is not False:
        context.update(
            subject_label="Restricted or unavailable source record",
            record_limited=True,
            explanation="Names, identifiers, and comparison evidence are unavailable for this record.",
            steps=["Open the source record to check its availability and access restrictions."],
        )
        return context

    context["subject_label"] = subject.get("reported_name") or "Unnamed source record"
    for key, label in (
        ("platform", "Source"),
        ("entity_type", "Record type"),
        ("canonical_serial", "Reported serial number"),
        ("vm_uuid", "Reported VM UUID"),
        ("presence", "Current source presence"),
        ("reported_state_label", "Current source-reported state"),
        ("reported_last_contact_at", "Current source-reported last contact"),
    ):
        if subject.get(key) is not None and subject.get(key) != "":
            context["facts"].append({"label": label, "value": subject[key]})

    evidence = _object(details.get("evidence"))
    name = finding.finding_type.name
    if name == "source_record_identity_review":
        proposed = _uuid(evidence.get("proposed_device_id"))
        recorded = _uuid(evidence.get("device_id"))
        current = _uuid(subject.get("device_id"))
        candidates = _object(evidence.get("candidates"))
        roles: dict[str, list[str]] = {}

        def add_role(value, label):
            if key := _uuid(value):
                roles.setdefault(key, []).append(label)

        add_role(current, "Attached now")
        add_role(recorded, "Attached at detection")
        add_role(proposed, "Matched at detection")
        for candidate in list(candidates)[:MAX_COMPUTERS]:
            add_role(candidate, "Candidate at detection")
        context["comparison_limited"] = (
            len(roles) > MAX_COMPUTERS or len(candidates) > MAX_COMPUTERS
        )
        roles = dict(list(roles.items())[:MAX_COMPUTERS])
        context["attachment_changed"] = bool(recorded and current != recorded)
        context["currently_unattached"] = current is None
        if proposed:
            context["summary"] = (
                "Strong identity evidence pointed to a different Computer from the one holding this record."
            )
            context["explanation"] = (
                "At last detection, another Computer matched a corroborated serial number or VM UUID. This calls the record's attachment into question; it does not prove the two Computers should be merged."
            )
            matcher = IDENTIFIERS.get(evidence.get("matcher"))
            if matcher:
                context["facts"].append({"label": "Match at detection", "value": matcher})
        else:
            context["summary"] = (
                "This source record's identifiers matched more than one Computer."
                if candidates
                else "This record needs identity review, but no candidate comparison was recorded."
            )
            context["explanation"] = (
                "Compare the available source records before choosing an attachment. A shared identifier alone is not a decision to merge."
            )
        context["computers"] = _comparison_computers(roles, candidates, tenant_id)
        context["steps"] = [
            "Compare this record's serial number and VM UUID with the current source records on each Computer below. Check source names and reported machine names as supporting context.",
            "Decide which machine the record describes. Check for an incorrect source identifier or records from different machines grouped on one Computer.",
            "Correct incorrect identifiers in their source. An attachment correction requires a separately reviewed record move; this issue has no move or merge action on this page.",
            "The source-record assessment closes the issue when it no longer finds an attachment contradiction or ambiguous identity match.",
        ]
    else:
        context["summary"] = finding.finding_type.description or finding.finding_type.display_name
        for key, label in (
            ("days_since_contact", "Days since contact at detection"),
            ("threshold_days", "Review threshold in days"),
            ("member_count", "Source records at detection"),
        ):
            value = evidence.get(key)
            if isinstance(value, int | float):
                context["facts"].append({"label": label, "value": value})
    return context


def _comparison_computers(roles: dict, candidates: dict, tenant_id: int) -> list[dict]:
    if not roles:
        return []
    devices = {
        str(device.id): device
        for device in Device.objects.filter(
            tenant_id=tenant_id, id__in=list(roles), deleted_at__isnull=True
        ).select_related("client")
    }
    owned_ids = {
        str(device_id)
        for device_id in Device.objects.filter(tenant_id=tenant_id, id__in=list(devices))
        .filter(id__in=effectively_owned_device_ids(tenant_id))
        .values_list("id", flat=True)
    }
    # Read from the same restricted metadata surface as the source-record page.
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT link.entity_id AS device_id, subject.id,
                   meta.reported_name, meta.platform, meta.canonical_serial,
                   meta.vm_uuid, meta.restricted, subject.presence
              FROM operations.entity_source_links link
              JOIN operations.source_record_subjects subject
                ON subject.tenant_id = link.tenant_id AND subject.id = link.source_subject_id
              LEFT JOIN operations.v_entity_observation_admin_metadata meta
                ON meta.tenant_id = subject.tenant_id AND meta.observation_id = subject.observation_id
             WHERE link.tenant_id = %s AND link.entity_class_id = 'device'
               AND link.entity_id = ANY(%s::uuid[])
             ORDER BY link.entity_id, subject.id
             LIMIT %s
            """,
            (tenant_id, list(devices), MAX_RECORDS + 1),
        )
        records = _rows(cur)
    result = []
    for device_id, labels in roles.items():
        device = devices.get(device_id)
        rows = []
        for record in records[:MAX_RECORDS]:
            if str(record["device_id"]) != device_id:
                continue
            restricted = record.get("restricted") is not False
            rows.append(
                {
                    "label": "Restricted or unavailable record"
                    if restricted
                    else record.get("reported_name") or "Unnamed record",
                    "url": reverse("source_record_detail", kwargs={"subject_id": record["id"]}),
                    "platform": "" if restricted else record.get("platform") or "",
                    "serial": "" if restricted else record.get("canonical_serial") or "",
                    "vm_uuid": "" if restricted else record.get("vm_uuid") or "",
                    "presence": record["presence"],
                }
            )
        families = candidates.get(device_id)
        result.append(
            {
                "label": device.canonical_hostname or "Unnamed Computer"
                if device
                else "Computer no longer available",
                "url": reverse(
                    "device_detail", kwargs={"org_slug": device.client.slug, "device_id": device.id}
                )
                if device and device.client and device_id in owned_ids
                else "",
                "roles": labels,
                "families": [IDENTIFIERS[family] for family in families if family in IDENTIFIERS]
                if isinstance(families, list)
                else [],
                "records": rows,
                "records_limited": len(records) > MAX_RECORDS,
            }
        )
    return result
