from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.db import connection, transaction
from django.http import Http404, HttpRequest, HttpResponse

from .db.tenant import DEFAULT_TENANT_ID, TenantGUCAssertionWrapper, set_local_tenant
from .models import Client

ORG_PATH_PARTS = 2

# Paths that MUST NOT be wrapped in a tenant SET LOCAL. Static asset
# serving, favicon, healthz probe, and API metadata don't need a DB
# transaction. Admin IS tenant-scoped in the sense that the admin user
# lives in tenant 1 and RLS must permit that lookup, so /admin stays IN
# the tenant scope.
TENANT_SCOPE_EXEMPT_PREFIXES = (
    "/healthz",
    "/static/",
    "/favicon.ico",
    "/api/schema/",
    "/api/docs/",
    "/api/redoc/",
)


class TenantMiddleware:
    """Opens a per-request transaction and pins the tenant GUC.

    M0 is single-tenant per BLUEPRINT §2 non-goals — tenant is always
    DEFAULT_TENANT_ID (1). When multi-tenant lands in a later milestone,
    tenant should be resolved from session data or subdomain, NOT from
    ``request.user.tenant_id`` — accessing ``request.user`` here triggers
    Django's session-based user lookup BEFORE the tenant GUC has been
    set, which under RLS + operations_app returns empty and caches the
    result as AnonymousUser, permanently anonymising the request even
    though the user did log in successfully.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self._assertion_installed = False

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant_id = DEFAULT_TENANT_ID
        request.tenant_id = tenant_id  # type: ignore[attr-defined]
        self._install_assertion_wrapper()

        if connection.vendor != "postgresql" or self._is_exempt(request.path_info):
            return self.get_response(request)

        with transaction.atomic():
            set_local_tenant(tenant_id)
            return self.get_response(request)

    @staticmethod
    def _is_exempt(path_info: str) -> bool:
        return any(path_info.startswith(prefix) for prefix in TENANT_SCOPE_EXEMPT_PREFIXES)

    def _install_assertion_wrapper(self) -> None:
        if self._assertion_installed:
            return
        if not (settings.DEBUG or getattr(settings, "OPERATIONS_STRICT_TENANT", False)):
            return

        connection.execute_wrappers.append(TenantGUCAssertionWrapper())
        self._assertion_installed = True


class ClientScopeMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        slug = self._extract_org_slug(request.path_info)
        request.org_slug = slug  # type: ignore[attr-defined]
        request.current_client = None  # type: ignore[attr-defined]
        request.org_mode = "none"  # type: ignore[attr-defined]

        if slug == "all":
            request.org_mode = "all"  # type: ignore[attr-defined]
        elif slug:
            request.org_mode = "client"  # type: ignore[attr-defined]
            try:
                request.current_client = Client.objects.get(  # type: ignore[attr-defined]
                    tenant_id=getattr(request, "tenant_id", DEFAULT_TENANT_ID),
                    slug=slug,
                    deleted_at__isnull=True,
                )
            except Client.DoesNotExist as exc:
                raise Http404("Client not found") from exc

        return self.get_response(request)

    def _extract_org_slug(self, path_info: str) -> str | None:
        parts = [part for part in path_info.split("/") if part]
        if len(parts) >= ORG_PATH_PARTS and parts[0] == "orgs":
            return parts[1]
        return None
