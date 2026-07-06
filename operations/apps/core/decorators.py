from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse


def require_client_scope(
    view_func: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    @wraps(view_func)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if getattr(request, "org_mode", None) != "client" or getattr(request, "current_client", None) is None:
            raise Http404("Client scope required")
        return view_func(request, *args, **kwargs)

    return wrapped


def require_admin(
    view_func: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    @wraps(view_func)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            raise PermissionDenied
        if getattr(user, "is_superuser", False) or user.has_perm("operations.manage_catalog"):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied

    return wrapped
