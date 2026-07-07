from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from django.db.models import Count, Q

from .models import Client, Device, Finding, FindingType, MergeCandidate


@require_GET
@transaction.non_atomic_requests
def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@login_required
def home(request: HttpRequest) -> HttpResponse:
    return render(request, "home.html")


@login_required
def org_index(request: HttpRequest, org_slug: str) -> HttpResponse:
    ctx: dict = {}
    if getattr(request, "current_client", None):
        client = request.current_client
        devices = (
            Device.objects.filter(
                tenant_id=1,
                client=client,
                deleted_at__isnull=True,
            )
            .order_by("canonical_hostname")
        )
        ctx["devices"] = devices
        ctx["device_count"] = devices.count()
        ctx["client_links"] = list(
            client.links.select_related("source").order_by("source__name")
        )
    else:
        # All-clients view: per-client device counts + fleet totals.
        clients_with_counts = list(
            Client.objects.filter(tenant_id=1, deleted_at__isnull=True)
            .annotate(
                device_count=Count(
                    "devices",
                    filter=Q(devices__deleted_at__isnull=True),
                )
            )
            .order_by("-device_count", "display_name")
        )
        ctx["clients_with_counts"] = clients_with_counts
        ctx["all_device_count"] = sum(c.device_count for c in clients_with_counts)
        ctx["all_client_count"] = len(clients_with_counts)
    return render(request, "org_index.html", ctx)


@login_required
def device_detail(request: HttpRequest, org_slug: str, device_id: str) -> HttpResponse:
    device = get_object_or_404(
        Device.objects.select_related("client"),
        tenant_id=1,
        id=device_id,
        client__slug=org_slug,
        deleted_at__isnull=True,
    )
    links = device.links.select_related("source").order_by("source__name")
    return render(
        request,
        "device_detail.html",
        {"device": device, "links": links},
    )


@login_required
def client_switch(request: HttpRequest) -> HttpResponse:
    slug = request.GET.get("slug", "all")
    return redirect("org_index", org_slug=slug)


_FINDING_ACTIVE_STATUSES = (
    Finding.Status.OPEN,
    Finding.Status.ACKNOWLEDGED,
    Finding.Status.INVESTIGATING,
)


@login_required
def findings_queue(request: HttpRequest) -> HttpResponse:
    """Findings queue landing page. Empty until M2 classification lands."""
    status_filter = request.GET.get("status", "active")
    severity_filter = request.GET.get("severity", "")
    type_filter = request.GET.get("type", "")

    qs = Finding.objects.filter(tenant_id=1).select_related("finding_type", "owner")

    if status_filter == "active":
        qs = qs.filter(status__in=_FINDING_ACTIVE_STATUSES)
    elif status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    if severity_filter:
        qs = qs.filter(severity=severity_filter)

    if type_filter:
        qs = qs.filter(finding_type__name=type_filter)

    qs = qs.order_by("-severity", "-last_seen_at")[:200]

    finding_types = FindingType.objects.order_by("name")

    return render(
        request,
        "findings_queue.html",
        {
            "findings": qs,
            "finding_types": finding_types,
            "status_choices": Finding.Status.choices,
            "severity_choices": Finding.Severity.choices,
            "active_status": status_filter,
            "active_severity": severity_filter,
            "active_type": type_filter,
        },
    )


@login_required
def merge_candidates_queue(request: HttpRequest) -> HttpResponse:
    """Cross-source merge candidate review queue. Empty until multi-source ingest lands."""
    status_filter = request.GET.get("status", MergeCandidate.Status.OPEN)
    entity_filter = request.GET.get("entity", "")

    qs = MergeCandidate.objects.filter(tenant_id=1).select_related("client")

    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)
    if entity_filter:
        qs = qs.filter(entity_type=entity_filter)

    qs = qs.order_by("-confidence", "canonical_key")[:200]

    entity_types = (
        MergeCandidate.objects.filter(tenant_id=1)
        .values_list("entity_type", flat=True)
        .distinct()
    )

    return render(
        request,
        "merge_candidates_queue.html",
        {
            "candidates": qs,
            "status_choices": MergeCandidate.Status.choices,
            "entity_types": sorted(set(entity_types)),
            "active_status": status_filter,
            "active_entity": entity_filter,
        },
    )
