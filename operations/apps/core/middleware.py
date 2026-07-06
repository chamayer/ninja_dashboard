from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.db import connection, transaction
from django.http import Http404, HttpRequest, HttpResponse

from .db.tenant import DEFAULT_TENANT_ID, TenantGUCAssertionWrapper, set_local_tenant
from .models import Client

ORG_PATH_PARTS = 2


class TenantMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self._assertion_installed = False

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant_id = self._resolve_tenant_id(request)
        request.tenant_id = tenant_id  # type: ignore[attr-defined]
        self._install_assertion_wrapper()

        if connection.vendor != "postgresql" or request.path_info == "/healthz":
            return self.get_response(request)

        with transaction.atomic():
            set_local_tenant(tenant_id)
            return self.get_response(request)

    def _resolve_tenant_id(self, request: HttpRequest) -> int:
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False) and getattr(user, "tenant_id", None):
            return int(user.tenant_id)
        return DEFAULT_TENANT_ID

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
