"""Root URL configuration."""

from __future__ import annotations

from django.contrib import admin
from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.core.views import client_switch, healthz, home, org_index

urlpatterns = [
    path("", home, name="home"),
    path("healthz", healthz, name="healthz"),
    path("orgs/<slug:org_slug>/", org_index, name="org_index"),
    path("switch/", client_switch, name="client_switch"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
