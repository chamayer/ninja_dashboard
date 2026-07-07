from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .forms import ClientPolicyForm
from .models import Client, ClientPolicy, Device, Finding, FindingType, MergeCandidate

DEVICE_PAGE_SIZE = 100


@require_GET
@transaction.non_atomic_requests
def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@login_required
def home(request: HttpRequest) -> HttpResponse:
    return render(request, "home.html")


def _type_summary_from_counts(counts: dict[str, int]) -> list[tuple[str, str, int]]:
    """(type_value, type_label, count) for device types present in a count map."""
    return [
        (device_type, label, counts.get(device_type, 0))
        for device_type, label in Device.DeviceType.choices
        if counts.get(device_type, 0) > 0
    ]


def _type_summary(devices: list) -> list[tuple[str, str, int]]:
    counts: dict[str, int] = {}
    for d in devices:
        counts[d.device_type] = counts.get(d.device_type, 0) + 1
    return _type_summary_from_counts(counts)


@login_required
def org_index(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Summary hub for a client or the fleet."""
    ctx: dict = {}
    if getattr(request, "current_client", None):
        client = request.current_client
        devices = list(
            Device.objects.filter(
                tenant_id=1, client=client, deleted_at__isnull=True
            ).only("device_type")
        )
        ctx["device_count"] = len(devices)
        ctx["type_summary"] = _type_summary(devices)
        ctx["client_links"] = list(
            client.links.select_related("source").order_by("source__name")
        )
        ctx["policy_count"] = ClientPolicy.objects.filter(
            tenant_id=1, client=client
        ).count()
        ctx["policy_categories"] = list(
            ClientPolicy.objects.filter(tenant_id=1, client=client)
            .values_list("category", flat=True)
            .order_by("category")
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
def org_devices(request: HttpRequest, org_slug: str) -> HttpResponse:
    """Device list for a specific client with server-side search/filter."""
    client = _get_client_by_slug(org_slug)
    base_qs = Device.objects.filter(
        tenant_id=1, client=client, deleted_at__isnull=True
    )
    type_counts = {
        row["device_type"]: row["count"]
        for row in base_qs.values("device_type").annotate(count=Count("id"))
    }
    total_count = sum(type_counts.values())

    search_query = request.GET.get("q", "").strip()
    active_type = request.GET.get("type", "").strip()
    valid_types = {value for value, _label in Device.DeviceType.choices}

    devices_qs = base_qs
    if search_query:
        devices_qs = devices_qs.filter(
            Q(canonical_hostname__icontains=search_query)
            | Q(canonical_serial__icontains=search_query)
        )
    if active_type in valid_types:
        devices_qs = devices_qs.filter(device_type=active_type)
    else:
        active_type = ""

    devices_qs = devices_qs.order_by("canonical_hostname").only(
        "id",
        "canonical_hostname",
        "canonical_serial",
        "device_type",
    )
    paginator = Paginator(devices_qs, DEVICE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    page_query = request.GET.copy()
    page_query.pop("page", None)
    type_query = request.GET.copy()
    type_query.pop("page", None)
    type_query.pop("type", None)

    return render(
        request,
        "org_devices.html",
        {
            "client": client,
            "devices": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "device_count": total_count,
            "filtered_count": paginator.count,
            "type_summary": _type_summary_from_counts(type_counts),
            "active_type": active_type,
            "search_query": search_query,
            "page_query": page_query.urlencode(),
            "type_query": type_query.urlencode(),
            "page_size": DEVICE_PAGE_SIZE,
        },
    )


@login_required
def org_policies(request: HttpRequest, org_slug: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    policies = list(
        ClientPolicy.objects.filter(tenant_id=1, client=client).order_by("category")
    )
    return render(
        request,
        "org_policies.html",
        {"client": client, "policies": policies},
    )


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


def _get_client_by_slug(slug: str) -> Client:
    return get_object_or_404(
        Client, tenant_id=1, slug=slug, deleted_at__isnull=True
    )


@login_required
def client_policy_new(request: HttpRequest, org_slug: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    if request.method == "POST":
        form = ClientPolicyForm(request.POST)
        if form.is_valid():
            policy = form.save(commit=False)
            policy.tenant_id = 1
            policy.client = client
            try:
                policy.save()
            except Exception as exc:
                form.add_error("category", f"Could not save: {exc}")
            else:
                messages.success(request, f"Policy '{policy.category}' created.")
                return redirect("org_index", org_slug=org_slug)
    else:
        form = ClientPolicyForm()
    return render(
        request,
        "client_policy_form.html",
        {"form": form, "client": client, "mode": "new"},
    )


@login_required
def client_policy_edit(request: HttpRequest, org_slug: str, policy_id: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    policy = get_object_or_404(ClientPolicy, tenant_id=1, client=client, id=policy_id)
    if request.method == "POST":
        form = ClientPolicyForm(request.POST, instance=policy)
        if form.is_valid():
            form.save()
            messages.success(request, f"Policy '{policy.category}' updated.")
            return redirect("org_index", org_slug=org_slug)
    else:
        form = ClientPolicyForm(instance=policy)
    return render(
        request,
        "client_policy_form.html",
        {"form": form, "client": client, "policy": policy, "mode": "edit"},
    )


@login_required
@require_POST
def client_policy_delete(request: HttpRequest, org_slug: str, policy_id: str) -> HttpResponse:
    client = _get_client_by_slug(org_slug)
    policy = get_object_or_404(ClientPolicy, tenant_id=1, client=client, id=policy_id)
    category = policy.category
    policy.delete()
    messages.success(request, f"Policy '{category}' deleted.")
    return redirect("org_index", org_slug=org_slug)


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
