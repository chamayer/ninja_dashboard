"""Registry-driven Operations Admin surfaces for generic entity evidence."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .csv_export import csv_response, wants_csv
from .decorators import require_admin
from .entity_candidate_decisions import attach_candidate, reject_candidate
from .models import Entity, EntityCandidate, EntityCandidateEvent

PAGE_SIZE = 100


def _rows(cursor) -> list[dict]:
    columns = [column.name for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _tenant_id(request: HttpRequest) -> int:
    return int(getattr(request, "tenant_id", 1))


def _page_query(request: HttpRequest) -> str:
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


@login_required
@require_admin
@require_GET
def entity_admin_list(request: HttpRequest) -> HttpResponse:
    tenant_id = _tenant_id(request)
    entity_class = (request.GET.get("class") or "").strip()
    state = (request.GET.get("state") or "current").strip()
    search = (request.GET.get("q") or "").strip()
    clauses = ["tenant_id = %s"]
    params: list[object] = [tenant_id]
    if entity_class:
        clauses.append("entity_class = %s")
        params.append(entity_class)
    if state == "current":
        clauses.extend(("retired_at IS NULL", "deleted_at IS NULL"))
    elif state == "retired":
        clauses.append("retired_at IS NOT NULL")
    elif state == "deleted":
        clauses.append("deleted_at IS NOT NULL")
    elif state != "all":
        state = "current"
        clauses.extend(("retired_at IS NULL", "deleted_at IS NULL"))
    if search:
        clauses.append("(display_label ILIKE %s OR id::text = %s)")
        params.extend((f"%{search}%", search))

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
        cur.execute(
            f"""
            SELECT * FROM operations.v_entity_admin_summary
             WHERE {' AND '.join(clauses)}
             ORDER BY entity_class_display, display_label, id
            """,
            params,
        )
        rows = _rows(cur)
        cur.execute(
            """
            SELECT entity_class, entity_class_display, count(*)::integer
              FROM operations.v_entity_admin_summary
             WHERE tenant_id = %s
             GROUP BY entity_class, entity_class_display
             ORDER BY entity_class_display
            """,
            (tenant_id,),
        )
        class_counts = _rows(cur)

    if wants_csv(request):
        return csv_response(
            rows,
            columns=[
                ("Class", "entity_class_display"),
                ("Entity", "display_label"),
                ("Client", "client_display_name"),
                ("Sources", "source_count"),
                ("Missing sources", "missing_source_count"),
                ("Effective attributes", "effective_attribute_count"),
                ("Conflicts", "conflict_count"),
                ("Retired", lambda row: "yes" if row["retired_at"] else "no"),
            ],
            filename_stem="entity_evidence",
        )

    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "entity_admin_list.html",
        {
            "admin_group": "integrations",
            "admin_tab": "entities",
            "page": page,
            "class_counts": class_counts,
            "entity_class_filter": entity_class,
            "state_filter": state,
            "search": search,
            "page_query": _page_query(request),
        },
    )


@login_required
@require_admin
@require_GET
def entity_admin_detail(request: HttpRequest, entity_id: uuid.UUID) -> HttpResponse:
    tenant_id = _tenant_id(request)
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
        cur.execute(
            "SELECT * FROM operations.v_entity_admin_summary WHERE tenant_id = %s AND id = %s",
            (tenant_id, entity_id),
        )
        entity = cur.fetchone()
        if entity is None:
            raise Http404("Entity not found")
        columns = [column.name for column in cur.description]
        entity_row = dict(zip(columns, entity, strict=True))

        cur.execute(
            """
            SELECT * FROM operations.v_entity_source_evidence
             WHERE tenant_id = %s AND entity_id = %s
             ORDER BY source_name, external_namespace, external_id
            """,
            (tenant_id, entity_id),
        )
        sources = _rows(cur)
        cur.execute(
            """
            SELECT * FROM operations.v_entity_attribute_effective_current
             WHERE tenant_id = %s AND entity_id = %s
             ORDER BY attribute_display_name, attribute_key
            """,
            (tenant_id, entity_id),
        )
        effective = _rows(cur)
        cur.execute(
            """
            SELECT claim.*, source.name AS source_name
              FROM operations.v_entity_attribute_claim_current claim
              JOIN operations.source_instances source_instance
                ON source_instance.tenant_id = claim.tenant_id
               AND source_instance.id = claim.source_instance_id
              JOIN operations.sources source ON source.id = source_instance.source_id
             WHERE claim.tenant_id = %s AND claim.entity_id = %s
             ORDER BY claim.attribute_display_name, source.name, claim.id
            """,
            (tenant_id, entity_id),
        )
        claims = _rows(cur)
        cur.execute(
            """
            SELECT * FROM operations.v_entity_attribute_conflict_admin
             WHERE tenant_id = %s AND entity_id = %s
             ORDER BY attribute_display_name
            """,
            (tenant_id, entity_id),
        )
        conflicts = _rows(cur)
        cur.execute(
            """
            SELECT relationship.*,
                   CASE WHEN relationship.source_entity_id = %s
                        THEN 'outgoing' ELSE 'incoming' END AS direction,
                   other.display_label AS other_entity_label,
                   other.id AS other_entity_id
              FROM operations.v_entity_relationship_admin relationship
              JOIN operations.v_entity_admin_summary other
                ON other.tenant_id = relationship.tenant_id
               AND other.id = CASE WHEN relationship.source_entity_id = %s
                                   THEN relationship.target_entity_id
                                   ELSE relationship.source_entity_id END
             WHERE relationship.tenant_id = %s
               AND (relationship.source_entity_id = %s
                    OR relationship.target_entity_id = %s)
             ORDER BY relationship.relationship_display_name, other.display_label
            """,
            (entity_id, entity_id, tenant_id, entity_id, entity_id),
        )
        relationships = _rows(cur)

    return render(
        request,
        "entity_admin_detail.html",
        {
            "admin_group": "integrations",
            "admin_tab": "entities",
            "entity": entity_row,
            "sources": sources,
            "effective": effective,
            "claims": claims,
            "conflicts": conflicts,
            "relationships": relationships,
        },
    )


@login_required
@require_admin
@require_GET
def entity_candidates_queue(request: HttpRequest) -> HttpResponse:
    tenant_id = _tenant_id(request)
    status = (request.GET.get("status") or "pending").strip()
    entity_class = (request.GET.get("class") or "").strip()
    clauses = ["tenant_id = %s"]
    params: list[object] = [tenant_id]
    if status != "all":
        allowed = {"pending", "observed_only", "rejected", "attached"}
        if status not in allowed:
            status = "pending"
        clauses.append("status = %s")
        params.append(status)
    if entity_class:
        clauses.append("entity_class = %s")
        params.append(entity_class)

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
        cur.execute(
            f"""
            SELECT * FROM operations.v_entity_candidate_admin
             WHERE {' AND '.join(clauses)}
             ORDER BY last_observed_at DESC, id
            """,
            params,
        )
        rows = _rows(cur)
        cur.execute(
            """
            SELECT status, count(*)::integer
              FROM operations.v_entity_candidate_admin
             WHERE tenant_id = %s
             GROUP BY status ORDER BY status
            """,
            (tenant_id,),
        )
        status_counts = {row[0]: row[1] for row in cur.fetchall()}

    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "entity_candidates_queue.html",
        {
            "admin_group": "review",
            "admin_tab": "entities",
            "page": page,
            "status_filter": status,
            "entity_class_filter": entity_class,
            "status_counts": status_counts,
            "page_query": _page_query(request),
        },
    )


@login_required
@require_admin
@require_GET
def entity_candidate_detail(request: HttpRequest, candidate_id: uuid.UUID) -> HttpResponse:
    tenant_id = _tenant_id(request)
    candidate = get_object_or_404(
        EntityCandidate.objects.select_related(
            "proposed_entity_class", "client", "source_instance__source", "resolved_entity"
        ),
        tenant_id=tenant_id,
        id=candidate_id,
    )
    target_search = (request.GET.get("q") or "").strip()
    clauses = ["tenant_id = %s", "entity_class = %s", "deleted_at IS NULL"]
    params: list[object] = [tenant_id, candidate.proposed_entity_class_id]
    if candidate.client_id:
        clauses.append("client_id = %s")
        params.append(candidate.client_id)
    if target_search:
        clauses.append("display_label ILIKE %s")
        params.append(f"%{target_search}%")
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = %s", (tenant_id,))
        cur.execute(
            f"""
            SELECT id, display_label, client_display_name
              FROM operations.v_entity_admin_summary
             WHERE {' AND '.join(clauses)}
             ORDER BY display_label, id LIMIT 100
            """,
            params,
        )
        target_entities = _rows(cur)
    events = list(
        EntityCandidateEvent.objects.filter(tenant_id=tenant_id, candidate=candidate)
        .select_related("actor")
        .order_by("-occurred_at")[:100]
    )
    return render(
        request,
        "entity_candidate_detail.html",
        {
            "admin_group": "review",
            "admin_tab": "entities",
            "candidate": candidate,
            "target_entities": target_entities,
            "target_search": target_search,
            "events": events,
            "can_decide": request.user.has_perm("operations.write_decisions"),
        },
    )


@login_required
@require_admin
@require_POST
def entity_candidate_attach(request: HttpRequest, candidate_id: uuid.UUID) -> HttpResponse:
    tenant_id = _tenant_id(request)
    candidate = get_object_or_404(EntityCandidate, tenant_id=tenant_id, id=candidate_id)
    try:
        entity_id = uuid.UUID((request.POST.get("entity_id") or "").strip())
        entity = Entity.objects.get(tenant_id=tenant_id, id=entity_id)
        attach_candidate(
            actor=request.user,
            candidate=candidate,
            entity=entity,
            reason=request.POST.get("reason") or "",
        )
    except (Entity.DoesNotExist, ValueError, ValidationError) as exc:
        messages.error(request, str(exc) or "Select a valid target entity.")
    else:
        messages.success(request, "Candidate attached to the canonical entity.")
    return redirect("entity_candidate_detail", candidate_id=candidate_id)


@login_required
@require_admin
@require_POST
def entity_candidate_reject(request: HttpRequest, candidate_id: uuid.UUID) -> HttpResponse:
    tenant_id = _tenant_id(request)
    candidate = get_object_or_404(EntityCandidate, tenant_id=tenant_id, id=candidate_id)
    try:
        reject_candidate(
            actor=request.user,
            candidate=candidate,
            reason=request.POST.get("reason") or "",
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Candidate rejected; source evidence remains available.")
    return redirect("entity_candidate_detail", candidate_id=candidate_id)
