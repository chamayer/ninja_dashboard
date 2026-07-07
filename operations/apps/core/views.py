from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from .models import Client, Device


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
        ctx["all_device_count"] = Device.objects.filter(
            tenant_id=1, deleted_at__isnull=True
        ).count()
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
