"""Managed source-record pages (PLAN-004 R4, ADR-0049).

Reads go through ``v_entity_observation_admin_metadata`` so restricted records
show no names or identifiers, and every query is tenant scoped.
"""

from __future__ import annotations

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
    "record.role": "Record role",
    "identifier.validity": "Identifier is usable",
    "identity.association": "Attached to one Computer",
    "case.duplicate": "Duplicate entries",
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
          LEFT JOIN operations.clients c ON c.tenant_id = d.tenant_id AND c.id = d.client_id
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
    return subject


@login_required
def source_record_detail(request: HttpRequest, subject_id: uuid.UUID) -> HttpResponse:
    tenant_id = int(getattr(request, "tenant_id", 1))
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        subject = load_subject(cur, tenant_id, subject_id)
        if subject is None:
            raise Http404("Source record not found")
        cur.execute(
            """
            SELECT rule_key, dimension, result, evidence, missing_facts, work_owner,
                   finding_id, rule_revision, assessed_at
              FROM operations.source_record_assessment_current
             WHERE tenant_id = %s AND target_kind = 'source_record' AND target_id = %s
             ORDER BY rule_key, dimension
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
    for row in assessments:
        row["rule_label"] = RULE_LABELS.get(row["rule_key"], row["rule_key"])
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
        },
    )


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
