"""Managed source-record pages (PLAN-004 R4, ADR-0049).

Reads go through ``v_entity_observation_admin_metadata`` so restricted records
show no names or identifiers, and every query is tenant scoped.
"""

from __future__ import annotations

import json
import uuid

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

RESULT_LABELS = {
    "supported": "Supported",
    "contradicted": "Contradicted",
    "unknown": "Unknown",
    "not_applicable": "Not applicable",
}
RULE_LABELS = {
    "record.presence": "Present at the source",
    "record.reported_status": "Source-reported connectivity",
    "record.reported_contact": "Source-reported last contact",
    "record.role": "Record role",
    "record.reference": "Source reference validity",
    "identifier.validity": "Identifier validity",
    "identity.association": "Attached to one Computer",
    "case.duplicate": "Duplicate entries",
    "software.vulnerability": "Vulnerable software",
    "software.decision": "Software policy",
    "software.suspicious_name": "Suspicious software name",
    "software.threat_intel": "Software threat signals",
    "software.capability": "Software capability policy",
}


def _rows(cur) -> list[dict]:
    columns = [c.name for c in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def load_subject(cur, tenant_id: int, subject_id: uuid.UUID) -> dict | None:
    cur.execute(
        """
        SELECT s.id, s.subject_kind, s.record_role, s.presence, s.platform, s.entity_type,
               s.input_version, s.association_version, s.admitted_at, s.updated_at,
               s.intake_error, s.source_instance_id,
               meta.reported_name, meta.canonical_serial, meta.vm_uuid, meta.restricted,
               meta.last_seen_at, meta.withdrawn_at, meta.external_id,
               meta.reported_online, meta.reported_last_contact_at,
               link.entity_id AS device_id, link.match_method,
               d.canonical_hostname AS device_name, c.slug AS client_slug,
               c.display_name AS client_name
          FROM operations.source_record_subjects s
          LEFT JOIN operations.v_entity_observation_admin_metadata meta
            ON meta.tenant_id = s.tenant_id AND meta.observation_id = s.observation_id
          LEFT JOIN operations.entity_source_links link
            ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
           AND link.external_namespace = s.external_namespace
           AND link.parent_external_namespace = s.parent_external_namespace
           AND link.parent_external_id = s.parent_external_id
           AND link.external_id = s.external_id AND link.entity_class_id = 'device'
          LEFT JOIN operations.devices d
            ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
          LEFT JOIN operations.computer_client_ownership owner
            ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
           AND owner.effective_client_id = d.client_id
           AND owner.state IN ('resolved', 'decision_protected')
          LEFT JOIN operations.clients c
            ON c.tenant_id = owner.tenant_id AND c.id = owner.effective_client_id
         WHERE s.tenant_id = %s AND s.id = %s
        """,
        (tenant_id, subject_id),
    )
    rows = _rows(cur)
    if not rows:
        return None
    subject = rows[0]
    if subject["restricted"]:
        subject["reported_name"] = subject["canonical_serial"] = subject["vm_uuid"] = None
        subject["external_id"] = None
    subject["reported_state_label"] = (
        "Online"
        if subject["reported_online"] is True
        else "Offline"
        if subject["reported_online"] is False
        else "Unknown"
    )
    return subject


def _undo_disposition(request: HttpRequest, tenant_id: int, subject_id: uuid.UUID):
    """Put back the attachment a reassessment move replaced (one click, audited)."""
    from django.contrib import messages
    from django.db import DatabaseError, transaction
    from django.shortcuts import redirect

    from apps.core.finding_actions import can_manage_lifecycle

    back = redirect("source_record_detail", subject_id=subject_id)
    if not can_manage_lifecycle(request.user):
        messages.error(request, "You do not have permission to undo this change.")
        return back
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
            cur.execute(
                """
                SELECT d.id, d.previous_device_id, s.association_version, dev.entity_id
                  FROM operations.source_record_dispositions d
                  JOIN operations.source_record_subjects s
                    ON s.tenant_id = d.tenant_id AND s.id = d.subject_id
                  LEFT JOIN operations.devices dev
                    ON dev.tenant_id = d.tenant_id AND dev.id = d.previous_device_id
                   AND dev.deleted_at IS NULL
                 WHERE d.tenant_id = %s AND d.subject_id = %s AND d.outcome = 'move'
                   AND d.applied AND d.undone_at IS NULL
                 ORDER BY d.decided_at DESC LIMIT 1
                   FOR UPDATE OF d
                """,
                (tenant_id, subject_id),
            )
            row = cur.fetchone()
            if row is None:
                messages.warning(request, "There is no reassessment change to undo.")
                return back
            disposition_id, previous_device, version, previous_entity = row
            if previous_device is not None and previous_entity is None:
                messages.error(request, "The previous Computer no longer exists.")
                return back
            cur.execute(
                "SELECT operations.set_source_association(%s, %s, 'device', 'operator', 1,"
                " 'undo reassessment', %s, 'user', %s, 'operations.ui', %s::jsonb)",
                (
                    subject_id,
                    previous_entity,
                    version,
                    request.user.id,
                    json.dumps({"undone_disposition_id": str(disposition_id)}),
                ),
            )
            cur.execute(
                "UPDATE operations.source_record_dispositions"
                " SET undone_at = now(), undone_by_id = %s WHERE id = %s",
                (request.user.id, disposition_id),
            )
    except DatabaseError as exc:
        messages.error(request, f"Nothing was changed: {str(exc).splitlines()[0]}")
        return back
    messages.success(request, "The previous attachment is restored.")
    return back


@login_required
def source_record_detail(request: HttpRequest, subject_id: uuid.UUID) -> HttpResponse:
    tenant_id = int(getattr(request, "tenant_id", 1))
    if request.method == "POST" and request.POST.get("action") == "undo_disposition":
        return _undo_disposition(request, tenant_id, subject_id)
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        subject = load_subject(cur, tenant_id, subject_id)
        if subject is None:
            raise Http404("Source record not found")
        cur.execute(
            """
            SELECT assessment.rule_key, assessment.dimension, assessment.result,
                   assessment.evidence, assessment.missing_facts, assessment.work_owner,
                   assessment.finding_id, assessment.rule_revision, assessment.assessed_at,
                   assessment.target_version,
                   EXISTS (SELECT 1 FROM operations.source_record_assessment_queue queue
                            WHERE queue.tenant_id = assessment.tenant_id
                              AND queue.target_kind = assessment.target_kind
                              AND queue.target_id = assessment.target_id
                              AND (queue.status <> 'done' OR queue.dirty_revision > queue.processed_revision)) AS pending,
                   EXISTS (SELECT 1 FROM operations.source_record_assessment_queue queue
                            WHERE queue.tenant_id = assessment.tenant_id
                              AND queue.target_kind = assessment.target_kind
                              AND queue.target_id = assessment.target_id
                              AND queue.status = 'failed') AS reassessment_failed
              FROM operations.source_record_assessment_current assessment
             WHERE assessment.tenant_id = %s AND assessment.target_kind = 'source_record'
               AND assessment.target_id = %s
             ORDER BY assessment.rule_key, assessment.dimension
            """,
            (tenant_id, subject_id),
        )
        assessments = _rows(cur)
        cur.execute(
            """
            SELECT f.id, t.display_name, f.severity, f.status, f.first_seen_at, f.last_detected_at
              FROM operations.findings f
              JOIN operations.finding_types t ON t.id = f.finding_type_id
             WHERE f.tenant_id = %s AND f.subject_type = 'source_record' AND f.subject_id = %s
             ORDER BY f.last_detected_at DESC NULLS LAST
             LIMIT 50
            """,
            (tenant_id, subject_id),
        )
        findings = _rows(cur)
        cases = case_memberships(cur, tenant_id, subject_id)
        cur.execute(
            """
            SELECT outcome, disposition_class, reason, applied, undone_at, decided_at
              FROM operations.source_record_dispositions
             WHERE tenant_id = %s AND subject_id = %s
             ORDER BY decided_at DESC LIMIT 5
            """,
            (tenant_id, subject_id),
        )
        dispositions = _rows(cur)
        companions = companion_details(cur, subject_id)
    from apps.core.finding_actions import can_manage_lifecycle

    undoable = bool(
        dispositions
        and dispositions[0]["outcome"] == "move"
        and dispositions[0]["applied"]
        and dispositions[0]["undone_at"] is None
        and can_manage_lifecycle(request.user)
    )
    for row in assessments:
        row["rule_label"] = RULE_LABELS.get(row["rule_key"], row["rule_key"])
        current_version = subject["input_version"] * 1_000_000 + subject["association_version"]
        if row["pending"] or row["target_version"] != current_version:
            row["result_label"] = "Reassessment failed" if row["reassessment_failed"] else "Pending reassessment"
            row["missing_facts"] = []
            row["work_owner"] = ""
            row["evidence"] = {}
        else:
            row["result_label"] = RESULT_LABELS.get(row["result"], row["result"])
        if subject["restricted"]:
            row["evidence"] = {}
    return render(
        request,
        "source_record_detail.html",
        {
            "subject": subject,
            "assessments": assessments,
            "findings": findings,
            "cases": cases,
            "dispositions": dispositions,
            "undoable": undoable,
            "companions": companions,
        },
    )


# Fields of a companion data set that only describe where it came from.
_COMPANION_CONTEXT_FIELDS = {"platform", "entity_type"}


def companion_details(cur, subject_id: uuid.UUID) -> list[dict]:
    """Data sets that are detail of this record (PLAN-038), e.g. Ninja device health."""
    cur.execute("SELECT to_regclass('operations.v_source_record_companion_detail') IS NOT NULL")
    if not cur.fetchone()[0]:
        return []
    cur.execute(
        """
        SELECT external_namespace, description, active, observed_at, last_seen_at,
               withdrawn_at, canonical_data
          FROM operations.v_source_record_companion_detail
         WHERE owner_subject_id = %s
         ORDER BY external_namespace
        """,
        (subject_id,),
    )
    companions = _rows(cur)
    for companion in companions:
        data = companion.pop("canonical_data") or {}
        # Django's raw cursor returns JSONB as text; other cursors may decode it.
        if isinstance(data, str):
            data = json.loads(data)
        companion["fields"] = [
            (key.replace("_", " ").capitalize(), value)
            for key, value in sorted(data.items())
            if key not in _COMPANION_CONTEXT_FIELDS and not isinstance(value, dict | list)
        ]
    return companions


def case_memberships(cur, tenant_id: int, subject_id: uuid.UUID) -> list[dict]:
    """The cases this record is an active member of (empty before Stage C)."""
    cur.execute("SELECT to_regclass('operations.source_record_case_members') IS NOT NULL")
    if not cur.fetchone()[0]:
        return []
    cur.execute(
        """
        SELECT c.id, c.key_family, c.state, c.member_count
          FROM operations.source_record_case_members m
          JOIN operations.source_record_cases c
            ON c.tenant_id = m.tenant_id AND c.id = m.case_id
         WHERE m.tenant_id = %s AND m.subject_id = %s AND m.released_at IS NULL
         ORDER BY c.key_family, c.id
        """,
        (tenant_id, subject_id),
    )
    return _rows(cur)


CASE_PAGE_SIZE = 50
FAMILY_LABELS = {"serial": "serial number", "vm_uuid": "VM UUID", "mac": "MAC address"}


@login_required
def source_record_cases(request: HttpRequest) -> HttpResponse:
    """One-key cases: open questions and duplicate dispositions, paged (§6.1)."""
    tenant_id = int(getattr(request, "tenant_id", 1))
    state = request.GET.get("state", "open")
    if state not in ("open", "duplicate", "closed"):
        state = "open"
    family = request.GET.get("family", "")
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1
    where = ["c.tenant_id = %s", "c.state = %s"]
    params: list[object] = [tenant_id, state]
    if family in FAMILY_LABELS:
        where.append("c.key_family = %s")
        params.append(family)
    where_sql = " AND ".join(where)
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        cur.execute(
            "SELECT c.state, count(*) FROM operations.source_record_cases c"
            " WHERE c.tenant_id = %s GROUP BY 1",
            (tenant_id,),
        )
        counts = dict(cur.fetchall())
        cur.execute(
            f"SELECT count(*) FROM operations.source_record_cases c WHERE {where_sql}", params
        )
        total = cur.fetchone()[0]
        cur.execute(
            f"""
            SELECT c.id, c.key_family, c.key_value, c.member_count, c.state, c.opened_at,
                   c.closed_at, c.duplicate_of_id, src.name AS source_name,
                   f.status AS finding_status, a.work_owner
              FROM operations.source_record_cases c
              JOIN operations.source_instances si
                ON si.tenant_id = c.tenant_id AND si.id = c.source_instance_id
              JOIN operations.sources src ON src.id = si.source_id
              LEFT JOIN operations.source_record_assessment_current a
                ON a.tenant_id = c.tenant_id AND a.target_kind = 'source_record_case'
               AND a.target_id = c.id AND a.rule_key = 'case.duplicate' AND a.dimension = ''
              LEFT JOIN operations.findings f
                ON f.tenant_id = a.tenant_id AND f.id = a.finding_id
             WHERE {where_sql}
             ORDER BY c.member_count DESC, c.opened_at, c.id
             LIMIT %s OFFSET %s
            """,
            [*params, CASE_PAGE_SIZE, (page - 1) * CASE_PAGE_SIZE],
        )
        cases = _rows(cur)
    for case in cases:
        case["family_label"] = FAMILY_LABELS.get(case["key_family"], case["key_family"])
    pages = max(1, (total + CASE_PAGE_SIZE - 1) // CASE_PAGE_SIZE)
    return render(
        request,
        "source_record_cases.html",
        {
            "cases": cases,
            "counts": counts,
            "state": state,
            "family": family,
            "families": FAMILY_LABELS,
            "total": total,
            "page": page,
            "pages": pages,
            "previous_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < pages else None,
        },
    )


def _case(cur, tenant_id: int, case_id: uuid.UUID) -> dict | None:
    cur.execute(
        """
        SELECT c.*, src.name AS source_name
          FROM operations.source_record_cases c
          JOIN operations.source_instances si
            ON si.tenant_id = c.tenant_id AND si.id = c.source_instance_id
          JOIN operations.sources src ON src.id = si.source_id
         WHERE c.tenant_id = %s AND c.id = %s
        """,
        (tenant_id, case_id),
    )
    rows = _rows(cur)
    return rows[0] if rows else None


_CASE_MEMBERS_SQL = """
SELECT s.id, s.platform, s.entity_type, s.presence, m.joined_at, m.released_at,
       meta.reported_name, meta.canonical_serial, meta.vm_uuid, meta.restricted,
       meta.last_seen_at, link.entity_id AS device_id,
       d.canonical_hostname AS device_name, cl.slug AS client_slug
  FROM operations.source_record_case_members m
  JOIN operations.source_record_subjects s
    ON s.tenant_id = m.tenant_id AND s.id = m.subject_id
  LEFT JOIN operations.v_entity_observation_admin_metadata meta
    ON meta.tenant_id = s.tenant_id AND meta.observation_id = s.observation_id
  LEFT JOIN operations.entity_source_links link
    ON link.tenant_id = s.tenant_id AND link.source_instance_id = s.source_instance_id
   AND link.external_namespace = s.external_namespace
   AND link.parent_external_namespace = s.parent_external_namespace
   AND link.parent_external_id = s.parent_external_id
   AND link.external_id = s.external_id AND link.entity_class_id = 'device'
  LEFT JOIN operations.devices d
    ON d.tenant_id = link.tenant_id AND d.id = link.entity_id AND d.deleted_at IS NULL
  LEFT JOIN operations.computer_client_ownership owner
    ON owner.tenant_id = d.tenant_id AND owner.device_id = d.id
   AND owner.effective_client_id = d.client_id
   AND owner.state IN ('resolved', 'decision_protected')
  LEFT JOIN operations.clients cl
    ON cl.tenant_id = owner.tenant_id AND cl.id = owner.effective_client_id
 WHERE m.tenant_id = %s AND m.case_id = %s
 ORDER BY m.released_at NULLS FIRST, meta.last_seen_at DESC NULLS LAST, s.id
 LIMIT 500
"""

_RELATED_CASES_SQL = """
SELECT other.id, other.key_family, other.key_value, other.state, other.member_count,
       count(*) AS shared_members
  FROM operations.source_record_case_members mine
  JOIN operations.source_record_case_members theirs
    ON theirs.tenant_id = mine.tenant_id AND theirs.subject_id = mine.subject_id
   AND theirs.case_id <> mine.case_id AND theirs.released_at IS NULL
  JOIN operations.source_record_cases other
    ON other.tenant_id = theirs.tenant_id AND other.id = theirs.case_id
 WHERE mine.tenant_id = %s AND mine.case_id = %s AND mine.released_at IS NULL
 GROUP BY other.id, other.key_family, other.key_value, other.state, other.member_count
 ORDER BY count(*) DESC, other.id
 LIMIT 50
"""


def _record_duplicate(request: HttpRequest, tenant_id: int, case_id: uuid.UUID) -> HttpResponse:
    from django.contrib import messages
    from django.db import DatabaseError, transaction
    from django.shortcuts import redirect

    from apps.core.findings_guard import guard_findings

    back = redirect("source_record_case_detail", case_id=case_id)
    try:
        target = uuid.UUID(request.POST.get("duplicate_of", ""))
        expected = int(request.POST.get("version", ""))
    except ValueError:
        messages.error(request, "Choose the case this one duplicates.")
        return back
    reason = (request.POST.get("reason") or "").strip()
    try:
        with transaction.atomic():
            guard_findings(tenant_id)
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT operations.mark_source_record_case_duplicate(%s, %s, %s, %s, %s)",
                    (case_id, target, reason, request.user.id, expected),
                )
    except DatabaseError as exc:
        messages.error(request, f"Nothing was changed: {str(exc).splitlines()[0]}")
        return back
    messages.success(
        request,
        "Recorded as duplicate work. This does not mean the records were corrected;"
        " the case reopens if its records or the other case change.",
    )
    return back


@login_required
def source_record_case_detail(request: HttpRequest, case_id: uuid.UUID) -> HttpResponse:
    """Members side by side, related cases and the duplicate disposition."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from apps.core.finding_actions import LIFECYCLE_PERMISSION

    tenant_id = int(getattr(request, "tenant_id", 1))
    may_decide = request.user.is_superuser or request.user.has_perm(LIFECYCLE_PERMISSION)
    if request.method == "POST":
        if not may_decide:
            messages.error(request, "You do not have permission to record a duplicate.")
            return redirect("source_record_case_detail", case_id=case_id)
        return _record_duplicate(request, tenant_id, case_id)

    with connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        case = _case(cur, tenant_id, case_id)
        if case is None:
            raise Http404("Case not found")
        cur.execute(_CASE_MEMBERS_SQL, (tenant_id, case_id))
        members = _rows(cur)
        cur.execute(_RELATED_CASES_SQL, (tenant_id, case_id))
        related = _rows(cur)
        cur.execute(
            """
            SELECT f.id, f.status, f.severity, f.first_seen_at, f.closed_at, f.finding_details
              FROM operations.findings f
             WHERE f.tenant_id = %s AND f.subject_type = 'source_record_case'
               AND f.subject_id = %s
             ORDER BY f.first_seen_at DESC
            """,
            (tenant_id, case_id),
        )
        findings = _rows(cur)
    for member in members:
        if member["restricted"]:
            member["reported_name"] = member["canonical_serial"] = member["vm_uuid"] = None
    for row in related:
        row["family_label"] = FAMILY_LABELS.get(row["key_family"], row["key_family"])
    case["family_label"] = FAMILY_LABELS.get(case["key_family"], case["key_family"])
    return render(
        request,
        "source_record_case_detail.html",
        {
            "case": case,
            "members": [m for m in members if m["released_at"] is None],
            "released": [m for m in members if m["released_at"] is not None],
            "related": related,
            "duplicate_targets": [r for r in related if r["state"] != "closed"],
            "findings": findings,
            "may_decide": may_decide and case["state"] == "open",
        },
    )
