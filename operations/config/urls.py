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
    admin_finding_acknowledge,
    client_policy_delete,
    client_policy_edit,
    client_policy_new,
    client_switch,
    device_detail,
    finding_acknowledge,
    findings_admin_health,
    findings_queue,
    fleet_coverage,
    healthz,
    home,
    merge_candidates_queue,
    org_devices,
    org_index,
    org_policies,
    org_software,
    org_software_decide,
    org_software_devices,
    sources_status,
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
    path("orgs/<slug:org_slug>/software/", org_software, name="org_software"),
    path("orgs/<slug:org_slug>/software/devices/", org_software_devices, name="org_software_devices"),
    path("orgs/<slug:org_slug>/software/decide/", org_software_decide, name="org_software_decide"),
    path("findings/", findings_queue, name="findings_queue"),
    path("findings/<uuid:finding_id>/ack/", finding_acknowledge, name="finding_acknowledge"),
    path("admin/findings/health/", findings_admin_health, name="findings_admin_health"),
    path("admin/findings/<uuid:finding_id>/ack/", admin_finding_acknowledge, name="admin_finding_acknowledge"),
    path("coverage/", fleet_coverage, name="fleet_coverage"),
    path("sources/", sources_status, name="sources_status"),
    path("merge-candidates/", merge_candidates_queue, name="merge_candidates_queue"),
    path("switch/", client_switch, name="client_switch"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
