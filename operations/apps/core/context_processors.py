"""Template context processors."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest

from .models import Client, ClientCandidate, EntityCandidate, Finding, MergeCandidate

_FINDING_ACTIVE_STATUSES = (
    Finding.Status.OPEN,
    Finding.Status.ACKNOWLEDGED,
    Finding.Status.INVESTIGATING,
)


def _active_section(request: HttpRequest) -> str:
    """Return the top-level nav section for the current URL."""
    url_name = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
    if url_name == "home":
        return "home"
    if any(x in url_name for x in ("software",)):
        return "software"
    if any(x in url_name for x in ("patch",)):
        return "patching"
    if url_name in ("devices_page", "device_detail", "device_merge", "org_devices"):
        return "devices"
    if "finding" in url_name:
        return "issues"
    if "org" in url_name or url_name in ("client_requirements_config", "client_policy_form"):
        return "clients"
    return ""


def brand(request: HttpRequest) -> dict:
    """Expose brand, scope, and lightweight navigation context."""
    ctx = {
        "brand": {
            "name": settings.OPERATIONS_BRAND_NAME,
            "short": settings.OPERATIONS_BRAND_SHORT,
            "tagline": settings.OPERATIONS_BRAND_TAGLINE,
            "support_url": settings.OPERATIONS_SUPPORT_URL,
            "privacy_url": settings.OPERATIONS_PRIVACY_URL,
        },
        "org_mode": getattr(request, "org_mode", "none"),
        "current_client": getattr(request, "current_client", None),
        "active_section": _active_section(request),
        "nav_findings_count": 0,
        "nav_pending_merges": 0,
        "nav_pending_client_candidates": 0,
        "nav_pending_entity_candidates": 0,
        # Software-decision counts are intentionally not calculated here.
        # The former fleet-wide anti-join took several seconds on production
        # data and ran for every authenticated page render. Reintroduce this
        # badge only from a derived, refreshable summary surface.
        "nav_pending_software_decisions": 0,
        "nav_patching_open": 0,
    }

    if getattr(request, "user", None) and request.user.is_authenticated:
        tenant_id = getattr(request, "tenant_id", 1)
        ctx["clients"] = list(
            Client.objects.filter(
                tenant_id=tenant_id,
                deleted_at__isnull=True,
            ).order_by("display_name")
        )
        ctx["nav_findings_count"] = Finding.objects.filter(
            tenant_id=tenant_id,
            status__in=_FINDING_ACTIVE_STATUSES,
        ).count()
        # These badges are rendered only in the application admin tabs, so
        # avoid even their small count queries on ordinary operator pages.
        if request.path_info.startswith("/admin/"):
            ctx["nav_pending_merges"] = MergeCandidate.objects.filter(
                tenant_id=tenant_id,
                status="pending",
            ).count()
            ctx["nav_pending_client_candidates"] = ClientCandidate.objects.filter(
                tenant_id=tenant_id,
                status=ClientCandidate.Status.OPEN,
            ).count()
            ctx["nav_pending_entity_candidates"] = EntityCandidate.objects.filter(
                tenant_id=tenant_id,
                status=EntityCandidate.Status.PENDING,
            ).count()
        ctx["nav_patching_open"] = Finding.objects.filter(
            tenant_id=tenant_id,
            finding_type__category__name="patching",
            status__in=_FINDING_ACTIVE_STATUSES,
        ).count()
    else:
        ctx["clients"] = []

    return ctx
