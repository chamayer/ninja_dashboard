"""Root URL configuration."""

from __future__ import annotations

from django.contrib import admin
from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.core.views import (
    client_switch,
    device_detail,
    findings_queue,
    healthz,
    home,
    org_index,
)

urlpatterns = [
    path("", home, name="home"),
    path("healthz", healthz, name="healthz"),
    path("orgs/<slug:org_slug>/", org_index, name="org_index"),
    path("orgs/<slug:org_slug>/devices/<uuid:device_id>/", device_detail, name="device_detail"),
    path("findings/", findings_queue, name="findings_queue"),
    path("switch/", client_switch, name="client_switch"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
