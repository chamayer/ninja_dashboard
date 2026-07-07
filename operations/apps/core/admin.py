from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AuditLog,
    Client,
    ClientLink,
    ClientPolicy,
    ClientUser,
    ClientUserLink,
    Collector,
    CollectorInstance,
    DeadLetterObservation,
    Device,
    DeviceLink,
    EntityObservation,
    Finding,
    FindingType,
    MergeCandidate,
    NotificationRoute,
    RunLog,
    Secret,
    SoftwareCatalog,
    SoftwareDecision,
    Source,
    SourceBinding,
    SourceInstance,
    SuppressionRule,
    Tenant,
    User,
    UserGroup,
    UserPermission,
)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "slug", "created_at")
    search_fields = ("display_name", "slug")
    readonly_fields = ("created_at",)


class UserGroupInline(admin.TabularInline):
    model = UserGroup
    extra = 0


class UserPermissionInline(admin.TabularInline):
    model = UserPermission
    extra = 0


@admin.register(User)
class OperationsUserAdmin(UserAdmin):
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Operations", {"fields": ("tenant", "timezone")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        *UserAdmin.add_fieldsets,
        ("Operations", {"fields": ("tenant", "email", "timezone")}),
    )
    list_display = ("username", "email", "tenant", "is_staff", "is_active")
    list_filter = (*UserAdmin.list_filter, "tenant")
    inlines = (UserGroupInline, UserPermissionInline)
    filter_horizontal = ()


@admin.register(UserGroup)
class UserGroupAdmin(admin.ModelAdmin):
    list_display = ("user", "group", "tenant")
    list_filter = ("tenant", "group")
    search_fields = ("user__username", "user__email", "group__name")


@admin.register(UserPermission)
class UserPermissionAdmin(admin.ModelAdmin):
    list_display = ("user", "permission", "tenant")
    list_filter = ("tenant", "permission__content_type")
    search_fields = ("user__username", "user__email", "permission__codename")


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind")
    search_fields = ("name", "kind")


@admin.register(Collector)
class CollectorAdmin(admin.ModelAdmin):
    list_display = ("name", "kind")
    search_fields = ("name", "kind")


@admin.register(FindingType)
class FindingTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "default_severity", "runbook_path")
    list_filter = ("default_severity",)
    search_fields = ("name", "description", "runbook_path")


class ClientLinkInline(admin.TabularInline):
    model = ClientLink
    extra = 0


class ClientPolicyInline(admin.TabularInline):
    model = ClientPolicy
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("display_name", "slug", "tenant", "timezone", "deleted_at", "version")
    list_filter = ("tenant", "timezone", "deleted_at")
    search_fields = ("display_name", "slug")
    inlines = (ClientLinkInline, ClientPolicyInline)


@admin.register(ClientLink)
class ClientLinkAdmin(admin.ModelAdmin):
    list_display = ("client", "source", "external_id", "external_name", "tenant", "version")
    list_filter = ("tenant", "source")
    search_fields = ("client__display_name", "external_id", "external_name")


@admin.register(ClientPolicy)
class ClientPolicyAdmin(admin.ModelAdmin):
    list_display = ("client", "category", "agent_sla_days", "tenant", "version")
    list_filter = ("tenant", "category")
    search_fields = ("client__display_name", "category")


class DeviceLinkInline(admin.TabularInline):
    model = DeviceLink
    extra = 0


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("canonical_hostname", "client", "device_type", "tenant", "deleted_at", "version")
    list_filter = ("tenant", "device_type", "deleted_at")
    search_fields = ("canonical_hostname", "canonical_serial", "canonical_vm_uuid")
    inlines = (DeviceLinkInline,)


@admin.register(DeviceLink)
class DeviceLinkAdmin(admin.ModelAdmin):
    list_display = ("device", "source", "external_id", "external_name", "tenant", "version")
    list_filter = ("tenant", "source")
    search_fields = ("device__canonical_hostname", "external_id", "external_name")


class ClientUserLinkInline(admin.TabularInline):
    model = ClientUserLink
    extra = 0


@admin.register(ClientUser)
class ClientUserAdmin(admin.ModelAdmin):
    list_display = ("display_name", "client", "canonical_email", "canonical_username", "tenant", "version")
    list_filter = ("tenant", "client", "deleted_at")
    search_fields = ("display_name", "canonical_email", "canonical_username")
    inlines = (ClientUserLinkInline,)


@admin.register(ClientUserLink)
class ClientUserLinkAdmin(admin.ModelAdmin):
    list_display = ("client_user", "source", "external_id", "external_name", "tenant", "version")
    list_filter = ("tenant", "source")
    search_fields = ("client_user__display_name", "external_id", "external_name")


class SourceBindingInline(admin.TabularInline):
    model = SourceBinding
    extra = 0


@admin.register(SourceInstance)
class SourceInstanceAdmin(admin.ModelAdmin):
    list_display = ("source", "client", "tenant", "enabled")
    list_filter = ("tenant", "source", "enabled")
    search_fields = ("client__display_name", "source__name")
    inlines = (SourceBindingInline,)


@admin.register(CollectorInstance)
class CollectorInstanceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "tenant", "last_heartbeat_at", "version")
    list_filter = ("tenant", "kind")
    search_fields = ("name", "kind")


@admin.register(SourceBinding)
class SourceBindingAdmin(admin.ModelAdmin):
    list_display = ("source_instance", "collector_instance", "schedule", "enabled", "tenant", "version")
    list_filter = ("tenant", "enabled")
    search_fields = ("source_instance__source__name", "collector_instance__name", "schedule")


@admin.register(EntityObservation)
class EntityObservationAdmin(admin.ModelAdmin):
    list_display = (
        "entity_type",
        "entity_key",
        "platform",
        "client",
        "device",
        "collector_instance",
        "observed_at",
        "tenant",
    )
    list_filter = ("tenant", "entity_type", "platform", "schema_version")
    search_fields = ("entity_key", "platform", "subplatform", "collector_version")
    readonly_fields = ("observation_id",)


@admin.register(DeadLetterObservation)
class DeadLetterObservationAdmin(admin.ModelAdmin):
    list_display = (
        "reject_reason",
        "collector_instance",
        "source_binding",
        "received_at",
        "resolved_at",
        "tenant",
    )
    list_filter = ("tenant", "collector_instance", "received_at", "resolved_at")
    search_fields = ("reject_reason",)
    readonly_fields = ("id", "received_at")


@admin.register(SoftwareCatalog)
class SoftwareCatalogAdmin(admin.ModelAdmin):
    list_display = ("canonical_name", "tenant", "publisher_hint", "eol_date")
    list_filter = ("tenant", "eol_date")
    search_fields = ("canonical_name", "publisher_hint", "notes")


@admin.register(SoftwareDecision)
class SoftwareDecisionAdmin(admin.ModelAdmin):
    list_display = ("client", "canonical_name", "decision", "decided_by", "decided_at", "tenant", "version")
    list_filter = ("tenant", "decision", "decided_at")
    search_fields = ("client__display_name", "canonical_name", "reason")


@admin.register(MergeCandidate)
class MergeCandidateAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "canonical_key", "client", "status", "confidence", "tenant", "version")
    list_filter = ("tenant", "entity_type", "status")
    search_fields = ("canonical_key", "match_reason")


@admin.register(Finding)
class FindingAdmin(admin.ModelAdmin):
    list_display = (
        "finding_type",
        "subject_type",
        "subject_id",
        "severity",
        "status",
        "owner",
        "last_seen_at",
        "tenant",
        "version",
    )
    list_filter = ("tenant", "finding_type", "subject_type", "severity", "status")
    search_fields = ("subject_id",)


@admin.register(SuppressionRule)
class SuppressionRuleAdmin(admin.ModelAdmin):
    list_display = ("finding_type", "reason", "expires_at", "created_by", "created_at", "tenant")
    list_filter = ("tenant", "finding_type", "expires_at")
    search_fields = ("reason",)
    readonly_fields = ("created_at",)


@admin.register(NotificationRoute)
class NotificationRouteAdmin(admin.ModelAdmin):
    list_display = ("channel", "target", "mode", "severity_min", "client", "finding_type", "tenant")
    list_filter = ("tenant", "channel", "mode", "severity_min")
    search_fields = ("target", "client__display_name", "finding_type__name")


@admin.register(Secret)
class SecretAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "rotated_at", "created_by")
    list_filter = ("tenant", "rotated_at")
    search_fields = ("name",)
    exclude = ("encrypted_value",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "entity_type", "entity_id", "actor_kind", "source", "occurred_at", "tenant")
    list_filter = ("tenant", "actor_kind", "source", "entity_type", "occurred_at")
    search_fields = ("action", "entity_type", "entity_id", "user_agent")
    readonly_fields = ("audit_id", "occurred_at")


@admin.register(RunLog)
class RunLogAdmin(admin.ModelAdmin):
    list_display = ("kind", "started_at", "ended_at", "ok", "rows", "tenant")
    list_filter = ("tenant", "kind", "ok", "started_at")
    search_fields = ("kind", "error")
