"""Template context processors."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest

from .models import Client


def brand(request: HttpRequest) -> dict:
    """Expose OPERATIONS_BRAND_* settings + org scope + client list to templates."""
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
    }

    if getattr(request, "user", None) and request.user.is_authenticated:
        ctx["clients"] = list(
            Client.objects.filter(
                tenant_id=getattr(request, "tenant_id", 1),
                deleted_at__isnull=True,
            ).order_by("display_name")
        )
    else:
        ctx["clients"] = []

    return ctx
