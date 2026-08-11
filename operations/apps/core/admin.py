from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AttributeAuthorityPolicy,
    AttributeDefinition,
    AuditLog,
    Client,
    ClientPolicy,
    ClientSourceLink,
    ClientUser,
    ClientUserLink,
    Collector,
    CollectorInstance,
    DeadLetterObservation,
    Device,
    DeviceSourceLink,
    Entity,
    EntityAttributeClaimEvidence,
    EntityAttributeClaimStorageStatus,
    EntityAttributeEffectiveEvidence,
    EntityAttributeProjectionState,
    EntityAttributeWithheldCurrent,
    EntityClass,
    EntityClassScope,
    EntitySourceLink,
    EntitySourceLinkHistory,
    EntityType,
    EolProductMap,
    Finding,
    FindingType,
    IdentityAuthorityPolicy,
    IntelMatcherHint,
    MergeCandidate,
    NotificationRoute,
    PublisherAlias,
    PublisherCategory,
    RunLog,
    Secret,
    SoftwareCatalog,
    SoftwareDecision,
    Source,
    SourceBinding,
    SourceFieldMapping,
    SourceInstance,
    SuppressionRule,
    Tenant,
    User,
    UserGroup,
    UserPermission,
)


class ReadOnlyEvidenceAdmin(admin.ModelAdmin):
    """Admin inspection without introducing a second mutation authority."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.register(EntityClass)
class EntityClassAdmin(ReadOnlyEvidenceAdmin):
    list_display = ("name", "display_name")
    search_fields = ("name", "display_name", "description")


@admin.register(EntityClassScope)
class EntityClassScopeAdmin(ReadOnlyEvidenceAdmin):
    list_display = ("entity_class", "scope_kind")
    list_filter = ("scope_kind",)


@admin.register(EntityType)
class EntityTypeAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "name",
        "entity_class",
        "is_identity_signal",
        "lifecycle_evidence_mode",
        "consumes_license",
        "requirement_eligible",
    )
    list_filter = (
        "entity_class",
        "is_identity_signal",
        "lifecycle_evidence_mode",
        "consumes_license",
        "requirement_eligible",
    )
    search_fields = ("name", "description")


@admin.register(Entity)
class EntityAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "id",
        "entity_class",
        "scope_kind",
        "client",
        "tenant",
        "retired_at",
        "deleted_at",
    )
    list_filter = ("tenant", "entity_class", "scope_kind", "retired_at", "deleted_at")
    search_fields = ("id", "client__display_name")


@admin.register(EntitySourceLink)
class EntitySourceLinkAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "entity",
        "entity_class",
        "source_instance",
        "external_namespace",
        "last_seen_at",
        "missing_since",
        "tenant",
    )
    list_filter = ("tenant", "entity_class", "external_namespace", "missing_since")
    search_fields = ("entity__id", "external_id")


@admin.register(EntitySourceLinkHistory)
class EntitySourceLinkHistoryAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "entity",
        "entity_class",
        "source_instance",
        "external_namespace",
        "effective_from",
        "effective_to",
        "tenant",
    )
    list_filter = ("tenant", "entity_class", "external_namespace", "actor_kind")
    search_fields = ("entity__id", "external_id", "reason", "actor_process")


@admin.register(AttributeDefinition)
class AttributeDefinitionAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "key",
        "entity_class",
        "value_type",
        "cardinality",
        "sensitivity",
        "definition_version",
        "enabled",
    )
    list_filter = ("entity_class", "value_type", "cardinality", "sensitivity", "enabled")
    search_fields = ("key", "display_name", "description")


@admin.register(SourceFieldMapping)
class SourceFieldMappingAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "source",
        "external_namespace",
        "native_record_type",
        "document_kind",
        "source_field",
        "attribute_definition",
        "mapping_version",
        "enabled",
    )
    list_filter = ("source", "document_kind", "enabled")
    search_fields = ("source_field", "external_namespace", "native_record_type")


@admin.register(IdentityAuthorityPolicy)
class IdentityAuthorityPolicyAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "source_instance",
        "native_record_type",
        "resulting_entity_type",
        "may_establish_identity",
        "may_create_canonical",
        "enabled",
        "tenant",
    )
    list_filter = ("tenant", "may_establish_identity", "may_create_canonical", "enabled")
    search_fields = ("native_record_type", "reason")


@admin.register(AttributeAuthorityPolicy)
class AttributeAuthorityPolicyAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "source_instance",
        "native_record_type",
        "attribute_definition",
        "eligible",
        "authority_tier",
        "priority",
        "enabled",
        "tenant",
    )
    list_filter = ("tenant", "eligible", "authority_tier", "enabled")
    search_fields = ("native_record_type", "attribute_definition__key", "reason")


@admin.register(EntityAttributeClaimEvidence)
class EntityAttributeClaimEvidenceAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "entity_id",
        "entity_class",
        "attribute_key",
        "value_display",
        "sensitivity",
        "authority_eligible",
        "authority_tier",
        "last_observed_at",
        "tenant",
    )
    list_filter = ("tenant", "entity_class", "sensitivity", "authority_eligible")
    search_fields = ("entity_id", "attribute_key", "value_display")


@admin.register(EntityAttributeWithheldCurrent)
class EntityAttributeWithheldCurrentAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "observation",
        "source_instance",
        "observed_field_count",
        "mapped_field_count",
        "unmapped_field_count",
        "restricted_field_count",
        "invalid_field_count",
        "projected_claim_count",
        "active",
        "tenant",
    )
    list_filter = ("tenant", "active")
    search_fields = ("observation__observation_id",)


@admin.register(EntityAttributeProjectionState)
class EntityAttributeProjectionStateAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "observation",
        "source_instance",
        "entity",
        "observation_active",
        "projection_contract_version",
        "projected_at",
        "tenant",
    )
    list_filter = ("tenant", "observation_active", "projection_contract_version")
    search_fields = ("observation__observation_id", "entity__id")


@admin.register(EntityAttributeClaimStorageStatus)
class EntityAttributeClaimStorageStatusAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "tenant",
        "current_claim_rows",
        "active_claim_rows",
        "history_claim_rows",
        "changed_members_1d",
        "partition_review_required",
    )
    list_filter = ("partition_review_required",)


@admin.register(EntityAttributeEffectiveEvidence)
class EntityAttributeEffectiveEvidenceAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "entity_id",
        "entity_class",
        "attribute_key",
        "value_display",
        "status",
        "selection_reason",
        "conflict",
        "projected_at",
        "tenant",
    )
    list_filter = (
        "tenant",
        "entity_class",
        "sensitivity",
        "status",
        "selection_reason",
        "conflict",
    )
    search_fields = ("entity_id", "attribute_key", "attribute_display_name")


@admin.register(Collector)
class CollectorAdmin(admin.ModelAdmin):
    list_display = ("name", "kind")
    search_fields = ("name", "kind")


@admin.register(FindingType)
class FindingTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "default_severity", "runbook_path")
    list_filter = ("default_severity",)
    search_fields = ("name", "description", "runbook_path")


# Read-only: v_client_source_link is a view (migration 0123).
class ClientSourceLinkInline(admin.TabularInline):
    model = ClientSourceLink
    extra = 0
    can_delete = False
    fields = ("source", "external_id", "external_namespace",
              "first_seen_at", "last_seen_at", "missing_since")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


class ClientPolicyInline(admin.TabularInline):
    model = ClientPolicy
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("display_name", "slug", "tenant", "timezone", "deleted_at", "version")
    list_filter = ("tenant", "timezone", "deleted_at")
    search_fields = ("display_name", "slug")
    inlines = (ClientSourceLinkInline, ClientPolicyInline)


@admin.register(ClientSourceLink)
class ClientSourceLinkAdmin(admin.ModelAdmin):
    list_display = ("client", "source", "external_id", "external_namespace",
                    "last_seen_at", "missing_since")
    list_filter = ("source", "external_namespace")
    search_fields = ("client__display_name", "external_id")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ClientPolicy)
class ClientPolicyAdmin(admin.ModelAdmin):
    list_display = ("client", "category", "agent_sla_days", "tenant", "version")
    list_filter = ("tenant", "category")
    search_fields = ("client__display_name", "category")


# `v_device_source_link` is a read-only view over `entity_source_links`
# (migration 0121), so both admin surfaces below are read-only. Postgres would
# reject a write anyway; declaring it here means the admin renders without
# add/change/delete controls instead of offering forms that fail on save.
class DeviceSourceLinkInline(admin.TabularInline):
    model = DeviceSourceLink
    extra = 0
    can_delete = False
    fields = (
        "source", "external_id", "external_namespace",
        "first_seen_at", "last_seen_at", "missing_since",
        "match_method", "match_confidence",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "canonical_hostname",
        "client",
        "device_type",
        "tenant",
        "deleted_at",
        "version",
    )
    list_filter = ("tenant", "device_type", "deleted_at")
    search_fields = ("canonical_hostname", "canonical_serial", "canonical_vm_uuid")
    inlines = (DeviceSourceLinkInline,)


@admin.register(DeviceSourceLink)
class DeviceSourceLinkAdmin(admin.ModelAdmin):
    list_display = (
        "device", "source", "external_id", "external_namespace",
        "last_seen_at", "missing_since",
    )
    list_filter = ("source", "external_namespace")
    search_fields = ("device__canonical_hostname", "external_id")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ClientUserLinkInline(admin.TabularInline):
    model = ClientUserLink
    extra = 0


@admin.register(ClientUser)
class ClientUserAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "client",
        "canonical_email",
        "canonical_username",
        "tenant",
        "version",
    )
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
    list_display = (
        "source_instance",
        "collector_instance",
        "schedule",
        "enabled",
        "tenant",
        "version",
    )
    list_filter = ("tenant", "enabled")
    search_fields = ("source_instance__source__name", "collector_instance__name", "schedule")


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


@admin.register(PublisherAlias)
class PublisherAliasAdmin(admin.ModelAdmin):
    list_display = ("raw_pattern", "canonical_publisher", "enabled", "is_regex", "created_at")
    list_filter = ("enabled", "is_regex")
    search_fields = ("raw_pattern", "canonical_publisher", "note")


@admin.register(PublisherCategory)
class PublisherCategoryAdmin(admin.ModelAdmin):
    list_display = ("publisher_pattern", "categories", "priority", "enabled", "created_at")
    list_filter = ("enabled",)
    search_fields = ("publisher_pattern", "note")


@admin.register(IntelMatcherHint)
class IntelMatcherHintAdmin(admin.ModelAdmin):
    list_display = ("kind", "pattern", "enabled", "created_at")
    list_filter = ("kind", "enabled")
    search_fields = ("pattern", "note")


@admin.register(EolProductMap)
class EolProductMapAdmin(admin.ModelAdmin):
    list_display = (
        "raw_pattern", "version_pattern", "eol_product", "eol_cycle",
        "priority", "updated_at",
    )
    list_filter = ("eol_product",)
    search_fields = ("raw_pattern", "version_pattern", "eol_product", "notes")
    ordering = ("priority", "raw_pattern")
    readonly_fields = (
        "tenant_id", "raw_pattern", "version_pattern", "eol_product",
        "eol_cycle", "priority", "notes", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SoftwareDecision)
class SoftwareDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "canonical_name",
        "decision",
        "decided_by",
        "decided_at",
        "tenant",
        "version",
    )
    list_filter = ("tenant", "decision", "decided_at")
    search_fields = ("client__display_name", "canonical_name", "reason")


@admin.register(MergeCandidate)
class MergeCandidateAdmin(admin.ModelAdmin):
    list_display = (
        "entity_type",
        "canonical_key",
        "client",
        "status",
        "confidence",
        "tenant",
        "version",
    )
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
    list_display = (
        "action",
        "entity_type",
        "entity_id",
        "actor_kind",
        "source",
        "occurred_at",
        "tenant",
    )
    list_filter = ("tenant", "actor_kind", "source", "entity_type", "occurred_at")
    search_fields = ("action", "entity_type", "entity_id", "user_agent")
    readonly_fields = ("audit_id", "occurred_at")


@admin.register(RunLog)
class RunLogAdmin(admin.ModelAdmin):
    list_display = ("kind", "started_at", "ended_at", "ok", "rows", "tenant")
    list_filter = ("tenant", "kind", "ok", "started_at")
    search_fields = ("kind", "error")
