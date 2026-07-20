"""Template context processors."""

from __future__ import annotations

from django.conf import settings
from django.db import connection, transaction
from django.http import HttpRequest

from .models import Client, ClientCandidate, Finding, MergeCandidate

_FINDING_ACTIVE_STATUSES = (
    Finding.Status.OPEN,
    Finding.Status.ACKNOWLEDGED,
    Finding.Status.INVESTIGATING,
)


def brand(request: HttpRequest) -> dict:
    """Expose OPERATIONS_BRAND_* settings + org scope + client list + nav badges."""
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
        "nav_findings_count": 0,
        "nav_pending_merges": 0,
        "nav_pending_client_candidates": 0,
        "nav_pending_software_decisions": 0,
        "nav_pending_review_total": 0,
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
        ctx["nav_pending_merges"] = MergeCandidate.objects.filter(
            tenant_id=tenant_id,
            status="pending",
        ).count()
        ctx["nav_pending_client_candidates"] = ClientCandidate.objects.filter(
            tenant_id=tenant_id,
            status=ClientCandidate.Status.OPEN,
        ).count()
        # Software titles installed somewhere with no decision at any scope.
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = %s", [tenant_id])
            cur.execute(
                """
                SELECT COUNT(DISTINCT si.canonical_name)::int
                FROM operations.software_installations_current si
                WHERE si.tenant_id = %s AND si.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM operations.software_decisions sd
                      WHERE sd.tenant_id = si.tenant_id
                        AND sd.canonical_name = si.canonical_name
                        AND (sd.client_id IS NULL OR sd.client_id = si.client_id)
                  )
                """,
                [tenant_id],
            )
            ctx["nav_pending_software_decisions"] = cur.fetchone()[0]

        ctx["nav_pending_review_total"] = (
            ctx["nav_pending_merges"]
            + ctx["nav_pending_client_candidates"]
            + ctx["nav_pending_software_decisions"]
        )
        ctx["nav_patching_open"] = Finding.objects.filter(
            tenant_id=tenant_id,
            finding_type__category__name="patching",
            status__in=_FINDING_ACTIVE_STATUSES,
        ).count()
    else:
        ctx["clients"] = []

    return ctx
