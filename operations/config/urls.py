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
    client_policy_delete,
    client_policy_edit,
    client_policy_new,
    client_switch,
    device_detail,
    findings_queue,
    healthz,
    home,
    merge_candidates_queue,
    org_devices,
    org_index,
    org_policies,
)

urlpatterns = [
    path("", home, name="home"),
    path("healthz", healthz, name="healthz"),
    path("orgs/<slug:org_slug>/", org_index, name="org_index"),
    path("orgs/<slug:org_slug>/devices/", org_devices, name="org_devices"),
    path("orgs/<slug:org_slug>/devices/<uuid:device_id>/", device_detail, name="device_detail"),
    path("orgs/<slug:org_slug>/policies/", org_policies, name="org_policies"),
    path("orgs/<slug:org_slug>/policies/new/", client_policy_new, name="client_policy_new"),
    path("orgs/<slug:org_slug>/policies/<uuid:policy_id>/edit/", client_policy_edit, name="client_policy_edit"),
    path("orgs/<slug:org_slug>/policies/<uuid:policy_id>/delete/", client_policy_delete, name="client_policy_delete"),
    path("findings/", findings_queue, name="findings_queue"),
    path("merge-candidates/", merge_candidates_queue, name="merge_candidates_queue"),
    path("switch/", client_switch, name="client_switch"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
