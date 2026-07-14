from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models
from django.db.models import Q


class Tenant(models.Model):
    slug = models.SlugField(max_length=80, unique=True)
    display_name = models.CharField(max_length=200)
    brand_config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants"
        ordering = ("display_name",)

    def __str__(self) -> str:
        return self.display_name


class User(AbstractUser):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="users")
    timezone = models.CharField(max_length=64, default="UTC")
    email = models.EmailField(blank=False)

    groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="operations_users",
        related_query_name="operations_user",
        through="UserGroup",
    )
    user_permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="operations_users",
        related_query_name="operations_user",
        through="UserPermission",
    )

    REQUIRED_FIELDS: ClassVar[list[str]] = ["email", "tenant_id"]

    class Meta:
        db_table = "users"
        permissions = (
            ("view_clients", "Can view clients"),
            ("view_devices", "Can view devices"),
            ("view_software", "Can view software"),
            ("view_findings", "Can view findings"),
            ("write_decisions", "Can write decisions"),
            ("approve_merges", "Can approve merges"),
            ("manage_findings", "Can manage findings"),
            ("manage_client_policy", "Can manage client policy"),
            ("manage_catalog", "Can manage software catalog"),
            ("manage_collectors", "Can manage collectors"),
            ("manage_sources", "Can manage sources"),
            ("manage_secrets", "Can manage secrets"),
            ("manage_users", "Can manage Operations users"),
            ("manage_taxonomy", "Can manage reference taxonomy"),
            ("run_queries", "Can run saved queries"),
        )

    def __str__(self) -> str:
        return self.get_username()


class TenantScopedModel(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class VersionedTenantScopedModel(TenantScopedModel):
    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True


class UUIDTenantScopedModel(VersionedTenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Source(models.Model):
    id = models.SmallAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=80)
    capabilities = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "sources"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Collector(models.Model):
    id = models.SmallAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=80)
    capabilities = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "collectors"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class FindingCategory(models.Model):
    """Admin-editable classification of finding types (coverage, identity,
    software, lifecycle, platform_health, data_quality, ...). Data-driven;
    operators add new categories without a schema change."""

    id = models.SmallAutoField(primary_key=True)
    name = models.CharField(max_length=32, unique=True)
    description = models.CharField(max_length=240, blank=True, default="")
    display_order = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "finding_categories"
        ordering = ("display_order", "name")

    def __str__(self) -> str:
        return self.name


class FindingType(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class FindingClass(models.TextChoices):
        ENTITY = "entity", "Entity"
        ADMIN = "admin", "Admin"

    id = models.SmallAutoField(primary_key=True)
    name = models.CharField(max_length=120, unique=True)
    default_severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    finding_class = models.CharField(max_length=16, choices=FindingClass.choices, default=FindingClass.ENTITY)
    category = models.ForeignKey(
        FindingCategory, on_delete=models.PROTECT, null=True, blank=True,
        related_name="finding_types",
    )
    source_module = models.CharField(max_length=80, blank=True, default="")
    auto_resolvable = models.BooleanField(default=True)
    runbook_path = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "finding_types"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Client(UUIDTenantScopedModel):
    slug = models.SlugField(max_length=120)
    display_name = models.CharField(max_length=240)
    timezone = models.CharField(max_length=64, default="UTC")
    requirement_profile = models.ForeignKey(
        "RequirementProfile",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="clients",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_reason = models.CharField(max_length=120, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_reason = models.CharField(max_length=120, blank=True, default="")
    stale_since = models.DateTimeField(null=True, blank=True)
    stale_reason = models.CharField(max_length=120, blank=True, default="")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_reason = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "clients"
        ordering = ("display_name",)
        constraints = (
            models.UniqueConstraint(fields=("tenant", "slug"), name="uq_clients_tenant_slug"),
        )

    def __str__(self) -> str:
        return self.display_name


class ClientLink(UUIDTenantScopedModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="links")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="client_links")
    external_id = models.CharField(max_length=240)
    external_name = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_reason = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "client_links"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "source", "external_id"),
                name="uq_client_links_tenant_source_external_id",
            ),
        )

    def __str__(self) -> str:
        return f"{self.source_id}:{self.external_id}"


class ClientNameAlias(UUIDTenantScopedModel):
    class Tier(models.TextChoices):
        MANUAL = "manual", "Manual"
        SEED = "seed", "Seed"
        ALIGNMENT = "alignment", "Alignment"
        SOURCE = "source", "Source"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="name_aliases")
    alias = models.CharField(max_length=240)
    normalized_name = models.CharField(max_length=240)
    tier = models.CharField(max_length=16, choices=Tier.choices, default=Tier.MANUAL)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=120, blank=True, default="")
    created_reason = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "client_name_aliases"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "normalized_name"),
                name="uq_client_name_aliases_tenant_normalized",
            ),
        )

    def __str__(self) -> str:
        return f"{self.alias} -> {self.client_id}"


class ClientOrgExclude(UUIDTenantScopedModel):
    source = models.ForeignKey(
        Source, on_delete=models.PROTECT, null=True, blank=True,
        related_name="org_excludes",
    )
    external_id = models.CharField(max_length=240, blank=True, default="")
    normalized_name = models.CharField(max_length=240, blank=True, default="")
    reason = models.CharField(max_length=240, blank=True, default="")
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "client_org_excludes"

    def __str__(self) -> str:
        return self.normalized_name or self.external_id


class PlaceholderOrgName(UUIDTenantScopedModel):
    normalized_name = models.CharField(max_length=240)
    note = models.CharField(max_length=240, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "placeholder_org_names"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "normalized_name"),
                name="uq_placeholder_org_names_tenant_normalized",
            ),
        )

    def __str__(self) -> str:
        return self.normalized_name


class ClientCandidate(UUIDTenantScopedModel):
    """A source group name that did not resolve to any client.

    Written by the client resolver when rungs 1-2 fail (no id-link, no
    exact-name match). Every candidate needs one of: accept (mint client),
    map (attach to existing client), exclude, fix (rename source-side).
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACCEPTED = "accepted", "Accepted"
        MAPPED = "mapped", "Mapped"
        EXCLUDED = "excluded", "Excluded"

    normalized_name = models.CharField(max_length=240)
    display_name = models.CharField(max_length=240, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    seen_count = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    source_refs = models.JSONField(default=list, blank=True)
    resolved_client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="resolved_candidates",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=120, blank=True, default="")
    resolved_reason = models.CharField(max_length=240, blank=True, default="")

    class Meta:
        db_table = "client_candidates"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "normalized_name"),
                name="uq_client_candidates_tenant_normalized",
            ),
        )

    def __str__(self) -> str:
        return self.display_name or self.normalized_name


class ClientPolicy(UUIDTenantScopedModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="policies")
    category = models.CharField(max_length=80)
    approved_products = models.JSONField(default=list, blank=True)
    agent_sla_days = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "client_policies"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "client", "category"),
                name="uq_client_policies_tenant_client_category",
            ),
        )

    def __str__(self) -> str:
        return f"{self.client_id}:{self.category}"


class Device(UUIDTenantScopedModel):
    class DeviceType(models.TextChoices):
        # Pure form factor. Agent presence is an observation-derived fact
        # (agent_presence_current), never encoded in the canonical device.
        PHYSICAL = "physical", "Physical"
        VM = "vm", "VM"
        HYPERVISOR_HOST = "hypervisor-host", "Hypervisor host"
        NETWORK_DEVICE = "network-device", "Network device"
        UNKNOWN = "unknown", "Unknown"

    class LifecycleStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        OFFLINE_AGING = "offline_aging", "Offline (aging)"
        PENDING_CLEANUP = "pending_cleanup", "Pending cleanup"
        RETIRED = "retired", "Retired"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="devices")
    canonical_hostname = models.CharField(max_length=255)
    canonical_serial = models.CharField(max_length=255, blank=True)
    canonical_vm_uuid = models.CharField(max_length=64, blank=True)
    device_type = models.CharField(
        max_length=32,
        choices=DeviceType.choices,
        default=DeviceType.UNKNOWN,
        verbose_name="Type",
    )
    # server/workstation from explicit source signals only, never guessed.
    # 'unknown' = no source has identified the role; still coverage-
    # evaluated under client defaults (role only matters when a
    # requirement scopes device_scope). Distinct from device_type
    # (form factor).
    device_role = models.CharField(max_length=16, default="unknown")
    # Driven by platform last-contact + operator decisions. Retired stays
    # fully queryable — visible, just out of coverage denominators.
    lifecycle_status = models.CharField(
        max_length=16,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.ACTIVE,
    )
    os_name = models.CharField(max_length=200, blank=True, default="")
    # Abbreviated family (e.g. 'Windows Server 2022', 'Windows 11') —
    # legacy taxonomy, mirrored by operations.os_family(text).
    os_family = models.CharField(max_length=40, blank=True, default="")
    # Coarse family: Windows / macOS / Linux / Other / Unknown.
    # Derived from os_family via OsGroupMapping; agent applicability
    # gates on this rather than the granular os_family value.
    os_group = models.CharField(max_length=16, blank=True, default="Unknown")
    # {entity_type: reason} — evaluator skips requirements whose
    # entity_type is present, e.g. {"agent.edr": "no_av_exempt"}.
    exemptions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_reason = models.CharField(max_length=120, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_reason = models.CharField(max_length=120, blank=True, default="")
    stale_since = models.DateTimeField(null=True, blank=True)
    stale_reason = models.CharField(max_length=120, blank=True, default="")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_reason = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "devices"
        ordering = ("canonical_hostname",)

    def __str__(self) -> str:
        return self.canonical_hostname


class DeviceLink(UUIDTenantScopedModel):
    class MatchMethod(models.TextChoices):
        SERIAL = "serial", "Serial"
        VM_UUID = "vm_uuid", "VM UUID"
        HOSTNAME_STRICT = "hostname_strict", "Hostname strict"
        HOSTNAME_LOOSE = "hostname_loose", "Hostname loose"
        MANUAL = "manual", "Manual"
        PROMOTED = "promoted", "Promoted"
        BOOTSTRAP = "bootstrap", "Bootstrap"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="links")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="device_links")
    external_id = models.CharField(max_length=240)
    external_name = models.CharField(max_length=240, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    missing_since = models.DateTimeField(null=True, blank=True)
    match_method = models.CharField(
        max_length=32,
        choices=MatchMethod.choices,
        default=MatchMethod.BOOTSTRAP,
    )
    match_confidence = models.DecimalField(max_digits=4, decimal_places=3, default=1)

    class Meta:
        db_table = "device_links"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "source", "external_id"),
                name="uq_device_links_tenant_source_external_id",
            ),
        )

    def __str__(self) -> str:
        return f"{self.source_id}:{self.external_id}"


class ClientUser(UUIDTenantScopedModel):
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="client_users")
    canonical_email = models.EmailField(blank=True)
    canonical_username = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=240)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "client_users"
        ordering = ("display_name",)

    def __str__(self) -> str:
        return self.display_name


class ClientUserLink(UUIDTenantScopedModel):
    client_user = models.ForeignKey(ClientUser, on_delete=models.CASCADE, related_name="links")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="client_user_links")
    external_id = models.CharField(max_length=240)
    external_name = models.CharField(max_length=240, blank=True)

    class Meta:
        db_table = "client_user_links"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "source", "external_id"),
                name="uq_client_user_links_tenant_source_external_id",
            ),
        )

    def __str__(self) -> str:
        return f"{self.source_id}:{self.external_id}"


class SourceInstance(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="source_instances")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="instances")
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "source_instances"

    def __str__(self) -> str:
        scope = self.client_id or "tenant"
        return f"{self.source_id}:{scope}"


class CollectorInstance(UUIDTenantScopedModel):
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=255, blank=True)
    capabilities = models.JSONField(default=dict, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "collector_instances"
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint(fields=("tenant", "name"), name="uq_collector_instances_tenant_name"),
        )

    def __str__(self) -> str:
        return self.name


class SourceBinding(UUIDTenantScopedModel):
    source_instance = models.ForeignKey(SourceInstance, on_delete=models.CASCADE, related_name="bindings")
    collector_instance = models.ForeignKey(CollectorInstance, on_delete=models.CASCADE, related_name="source_bindings")
    schedule = models.CharField(max_length=120, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "source_bindings"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "source_instance", "collector_instance"),
                name="uq_source_bindings_tenant_source_collector",
            ),
        )

    def __str__(self) -> str:
        return f"{self.source_instance_id}:{self.collector_instance_id}"


class EntityObservation(TenantScopedModel):
    observation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="observations")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, null=True, blank=True, related_name="observations")
    collector_instance = models.ForeignKey(
        CollectorInstance,
        on_delete=models.PROTECT,
        related_name="entity_observations",
    )
    source_binding = models.ForeignKey(
        SourceBinding,
        on_delete=models.PROTECT,
        related_name="entity_observations",
    )
    entity_type = models.CharField(max_length=80)
    entity_key = models.TextField()
    platform = models.CharField(max_length=80)
    subplatform = models.CharField(max_length=120, blank=True)
    observed_at = models.DateTimeField()
    raw_data = models.JSONField(default=dict)
    canonical_data = models.JSONField(default=dict)
    batch_id = models.UUIDField()
    observation_hash = models.BinaryField()
    collector_version = models.CharField(max_length=80, blank=True)
    schema_version = models.PositiveIntegerField()

    class Meta:
        db_table = "entity_observations"
        indexes = (
            models.Index(fields=("tenant", "entity_type", "entity_key"), name="idx_entity_obs_entity_key"),
            models.Index(fields=("tenant", "client", "device"), name="idx_entity_obs_client_device"),
            models.Index(fields=("tenant", "observed_at"), name="idx_entity_obs_observed_at"),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "collector_instance", "batch_id", "observation_hash"),
                name="uq_entity_obs_tenant_collector_batch_hash",
            ),
        )

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.entity_key}"


class DeadLetterObservation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_binding = models.ForeignKey(
        SourceBinding,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dead_letter_observations",
    )
    collector_instance = models.ForeignKey(
        CollectorInstance,
        on_delete=models.PROTECT,
        related_name="dead_letter_observations",
    )
    received_at = models.DateTimeField(auto_now_add=True)
    envelope = models.JSONField(default=dict)
    reject_reason = models.TextField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolved_dead_letters",
    )

    class Meta:
        db_table = "dead_letter_observations"
        indexes = (
            models.Index(fields=("tenant", "received_at"), name="idx_dead_letter_received_at"),
            models.Index(fields=("tenant", "resolved_at"), name="idx_dead_letter_resolved_at"),
        )

    def __str__(self) -> str:
        return self.reject_reason[:80]


class SoftwareCatalog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, null=True, blank=True)
    canonical_name = models.CharField(max_length=255)
    categories = models.JSONField(default=list, blank=True)
    publisher_hint = models.CharField(max_length=255, blank=True)
    eol_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "software_catalog"
        ordering = ("canonical_name",)
        constraints = (
            models.UniqueConstraint(
                fields=("canonical_name",),
                condition=Q(tenant__isnull=True),
                name="software_catalog_global_unique",
            ),
            models.UniqueConstraint(
                fields=("tenant", "canonical_name"),
                condition=Q(tenant__isnull=False),
                name="software_catalog_tenant_unique",
            ),
        )

    def __str__(self) -> str:
        return self.canonical_name


class SoftwareDecision(UUIDTenantScopedModel):
    class Decision(models.TextChoices):
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        INVESTIGATE = "investigate", "Investigate"
        APPROVE_PUBLISHER = "approve_publisher", "Approve publisher"

    # Scope tier (resolver order):
    #   (device set) → most specific, applies only to that device
    #   (client set, device NULL) → per-client
    #   (client NULL, device NULL) → global (all tenant clients)
    client = models.ForeignKey(
        Client, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="software_decisions",
    )
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="software_decisions",
    )
    canonical_name = models.CharField(max_length=255)
    decision = models.CharField(max_length=32, choices=Decision.choices)
    reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="software_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "software_decisions"
        constraints = (
            # One decision per (scope, canonical_name). Scope key uses
            # COALESCE via distinct constraints — Django doesn't express
            # multi-column-with-nulls cleanly in one UC, so we use
            # three partial constraints keyed by the scope shape.
            models.UniqueConstraint(
                fields=("tenant", "canonical_name"),
                condition=Q(client__isnull=True) & Q(device__isnull=True),
                name="uq_software_decisions_global",
            ),
            models.UniqueConstraint(
                fields=("tenant", "client", "canonical_name"),
                condition=Q(client__isnull=False) & Q(device__isnull=True),
                name="uq_software_decisions_client",
            ),
            models.UniqueConstraint(
                fields=("tenant", "device", "canonical_name"),
                condition=Q(device__isnull=False),
                name="uq_software_decisions_device",
            ),
        )

    def __str__(self) -> str:
        return f"{self.client_id}:{self.canonical_name}:{self.decision}"


class SoftwareClassifierRule(models.Model):
    """Data-driven regex / literal patterns for the software classifier.

    Every rule the classifier applies lives here so operators can add /
    edit / disable rules via the admin UI without a deploy. Global
    (tenant-null) reference data.
    """

    class RuleType(models.TextChoices):
        SUSPICIOUS_NAME = "suspicious_name", "Suspicious name"
        INSTALL_PATH_SUSPICIOUS = "install_path_suspicious", "Suspicious install path"
        EOL_RUNTIME = "eol_runtime", "End-of-life runtime"

    id = models.SmallAutoField(primary_key=True)
    rule_type = models.CharField(max_length=32, choices=RuleType.choices)
    pattern = models.CharField(max_length=255)
    is_regex = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=240, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "software_classifier_rules"
        ordering = ("rule_type", "pattern")
        constraints = (
            models.UniqueConstraint(
                fields=("rule_type", "pattern"),
                name="uq_software_classifier_rules_type_pattern",
            ),
        )

    def __str__(self) -> str:
        return f"{self.rule_type}:{self.pattern}"


class MergeCandidate(UUIDTenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        MERGED = "merged", "Merged"
        SPLIT = "split", "Split"
        REJECTED = "rejected", "Rejected"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="merge_candidates")
    entity_type = models.CharField(max_length=80)
    canonical_key = models.TextField()
    member_snapshots = models.JSONField(default=list)
    member_observation_ids = models.JSONField(null=True, blank=True)
    match_reason = models.TextField(blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    class Meta:
        db_table = "merge_candidates"
        indexes = (
            models.Index(fields=("tenant", "client", "entity_type", "status"), name="idx_merge_candidates_scope"),
        )

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.canonical_key}"


class Finding(UUIDTenantScopedModel):
    class SubjectType(models.TextChoices):
        CLIENT = "client", "Client"
        DEVICE = "device", "Device"
        CLIENT_USER = "client_user", "Client user"
        SOURCE_BINDING = "source_binding", "Source binding"
        COLLECTOR_INSTANCE = "collector_instance", "Collector instance"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"
        INFO = "info", "Info"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        INVESTIGATING = "investigating", "Investigating"
        SUPPRESSED = "suppressed", "Suppressed"
        RESOLVED = "resolved", "Resolved"
        WONTFIX = "wontfix", "Won't fix"

    class Confidence(models.TextChoices):
        POSSIBLE = "possible", "Possible"
        PROBABLE = "probable", "Probable"
        CONFIRMED = "confirmed", "Confirmed"

    finding_type = models.ForeignKey(FindingType, on_delete=models.PROTECT, related_name="findings")
    client = models.ForeignKey("Client", on_delete=models.PROTECT, null=True, blank=True, related_name="findings")
    subject_type = models.CharField(max_length=32, choices=SubjectType.choices)
    subject_id = models.UUIDField()
    finding_details = models.JSONField(default=dict, blank=True)
    condition_key = models.CharField(max_length=255, blank=True, default="", db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    confidence = models.CharField(max_length=16, choices=Confidence.choices, blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_findings",
    )
    sla_due_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    last_detected_at = models.DateTimeField(null=True, blank=True)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "findings"
        indexes = (
            models.Index(fields=("tenant", "status", "severity"), name="idx_findings_status_severity"),
            models.Index(fields=("tenant", "subject_type", "subject_id"), name="idx_findings_subject"),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "condition_key"),
                condition=Q(condition_key__gt="") & Q(status__in=["open", "acknowledged"]),
                name="uq_findings_active_condition_key",
            ),
        )

    def __str__(self) -> str:
        return f"{self.finding_type_id}:{self.subject_type}:{self.subject_id}"


class RequirementProfile(UUIDTenantScopedModel):
    """A named template of coverage requirements.

    Client acceptance (Track C.4) instantiates a profile's items as
    per-client coverage_requirements rows. The tenant-default profile is
    a data row (marked is_tenant_default), not code — the operator can
    change it in the admin.
    """

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=240, blank=True, default="")
    is_tenant_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "requirement_profiles"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "name"),
                name="uq_requirement_profiles_tenant_name",
            ),
            models.UniqueConstraint(
                fields=("tenant",),
                condition=Q(is_tenant_default=True),
                name="uq_requirement_profiles_tenant_default",
            ),
        )

    def __str__(self) -> str:
        return self.name


class Agent(models.Model):
    """Reference data: an agent product (Ninja / SentinelOne / etc).

    Encodes the technical ceiling — which OS groups the agent CAN run on
    (physics) — plus default severity/gap thresholds. Requirement rows
    point to an Agent instead of hardcoding entity_type + platform.
    Global reference data (not tenant-scoped).
    """

    id = models.SmallAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    entity_type = models.CharField(max_length=80)
    # OS groups this agent supports installing on (Windows/macOS/Linux/…).
    # A device whose os_group is not in this list cannot receive the agent —
    # coverage skips it for this agent regardless of client policy.
    supported_os_groups = models.JSONField(default=list)
    default_severity = models.CharField(max_length=16, default="high")
    default_gap_after_hours = models.PositiveIntegerField(default=24)
    default_confidence_probable = models.PositiveIntegerField(default=48)
    default_confidence_confirmed = models.PositiveIntegerField(default=168)

    class Meta:
        db_table = "agents"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class OsGroupMapping(models.Model):
    """Maps os_family patterns to a coarse os_group.

    Data-driven so operators can adjust groupings without a deploy.
    First match wins by ascending `priority`.
    """

    id = models.SmallAutoField(primary_key=True)
    pattern = models.CharField(max_length=80)  # SQL LIKE-style, e.g. "Windows Server %"
    os_group = models.CharField(max_length=16)
    priority = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "os_group_mappings"
        ordering = ("priority", "pattern")

    def __str__(self) -> str:
        return f"{self.pattern} → {self.os_group}"


class RequirementProfileItem(UUIDTenantScopedModel):
    """One row within a profile — 'this client requires this agent for
    this device scope.'

    Points to an Agent (agent physics: which OS it supports, default
    thresholds). Operator can override severity / gap / applicable OS
    groups per item.
    """

    profile = models.ForeignKey(
        RequirementProfile, on_delete=models.CASCADE, related_name="items"
    )
    agent = models.ForeignKey(
        Agent, on_delete=models.PROTECT, null=True, blank=True,
        related_name="profile_items",
    )
    # Deprecated pair — retained through migration transition, will be
    # dropped once every row has agent_id populated.
    entity_type = models.CharField(max_length=80, blank=True, default="")
    platform = models.CharField(max_length=80, blank=True, default="")
    device_scope = models.CharField(max_length=40, default="all")
    # NULL = use Agent.supported_os_groups. A list narrows it (client
    # policy override — e.g. "we only require Ninja on Windows even
    # though it also runs on Linux").
    applicable_os_groups = models.JSONField(null=True, blank=True)
    severity = models.CharField(max_length=16, default="high")
    gap_after_hours = models.PositiveIntegerField(default=24)
    confidence_probable = models.PositiveIntegerField(default=48)
    confidence_confirmed = models.PositiveIntegerField(default=168)

    class Meta:
        db_table = "requirement_profile_items"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "profile", "entity_type", "platform", "device_scope"),
                name="uq_requirement_profile_items_shape",
            ),
        )

    def __str__(self) -> str:
        return f"{self.profile_id}:{self.entity_type}:{self.platform or '*'}"


class CoverageRequirement(VersionedTenantScopedModel):
    """Declarative policy: what platform/entity_type should exist per org/device scope."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        "Client", on_delete=models.PROTECT, null=True, blank=True,
        related_name="coverage_requirements",
    )
    agent = models.ForeignKey(
        Agent, on_delete=models.PROTECT, null=True, blank=True,
        related_name="coverage_requirements",
    )
    # Deprecated pair — retained through migration transition.
    entity_type = models.CharField(max_length=80, blank=True, default="")
    platform = models.CharField(max_length=80, blank=True, default="")
    device_scope = models.CharField(max_length=40, default="all")
    applicable_os_groups = models.JSONField(null=True, blank=True)
    severity = models.CharField(max_length=16, choices=Finding.Severity.choices, default="high")
    gap_after_hours = models.PositiveIntegerField(default=24)
    confidence_probable = models.PositiveIntegerField(default=48)
    confidence_confirmed = models.PositiveIntegerField(default=168)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "coverage_requirements"
        ordering = ("entity_type", "platform")

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.platform or '*'}:{self.device_scope}"


class AdminFinding(VersionedTenantScopedModel):
    """Platform health findings — about the Operations platform itself, not devices."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding_type = models.ForeignKey(
        FindingType, on_delete=models.PROTECT, related_name="admin_findings"
    )
    condition_key = models.CharField(max_length=255)
    severity = models.CharField(max_length=16, choices=Finding.Severity.choices, default="medium")
    status = models.CharField(max_length=24, choices=Finding.Status.choices, default="open")
    subject_ref = models.JSONField(default=dict)
    details = models.JSONField(default=dict)
    first_detected_at = models.DateTimeField()
    last_detected_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "admin_findings"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "condition_key"),
                condition=Q(status__in=["open", "acknowledged"]),
                name="uq_admin_findings_active_condition_key",
            ),
        )
        indexes = (
            models.Index(fields=("tenant", "status", "severity"), name="idx_admin_findings_status"),
        )

    def __str__(self) -> str:
        return f"{self.finding_type_id}:{self.condition_key[:40]}"


class QueueRegistry(models.Model):
    """Registry of all known queues. No tenant isolation — global operator view."""

    queue_key = models.CharField(max_length=120, primary_key=True)
    queue_type = models.CharField(max_length=16)
    table_name = models.CharField(max_length=120)
    owner = models.CharField(max_length=80)
    enabled = models.BooleanField(default=True)
    max_pending_age_m = models.PositiveIntegerField(default=60)
    max_failure_count = models.PositiveIntegerField(default=5)
    max_depth = models.PositiveIntegerField(default=1000)
    description = models.TextField(blank=True)

    class Meta:
        app_label = "operations"
        db_table = "queue_registry"
        ordering = ("queue_key",)

    def __str__(self) -> str:
        return self.queue_key


class IdentityCandidate(VersionedTenantScopedModel):
    """Uncertain cross-source device matches awaiting operator review."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_a = models.ForeignKey(
        "Device", on_delete=models.PROTECT, related_name="identity_candidates_a"
    )
    device_b = models.ForeignKey(
        "Device", on_delete=models.PROTECT, related_name="identity_candidates_b"
    )
    confidence = models.CharField(max_length=16)
    signals = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "identity_candidates"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "device_a", "device_b"),
                condition=Q(status="pending"),
                name="uq_identity_candidates_pending_pair",
            ),
        )

    def __str__(self) -> str:
        return f"{self.device_a_id}↔{self.device_b_id}:{self.confidence}"


class NotificationRule(VersionedTenantScopedModel):
    """Rule engine: maps finding types to delivery routes with filters."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding_type = models.ForeignKey(
        FindingType, on_delete=models.PROTECT, related_name="notification_rules"
    )
    finding_class = models.CharField(max_length=16, default="entity")
    min_severity = models.CharField(max_length=16, blank=True, default="")
    min_confidence = models.CharField(max_length=16, blank=True, default="")
    client = models.ForeignKey(
        "Client", on_delete=models.PROTECT, null=True, blank=True,
        related_name="notification_rules",
    )
    match_criteria = models.JSONField(default=dict)
    route = models.ForeignKey("NotificationRoute", on_delete=models.PROTECT, related_name="rules")
    urgency_hours = models.PositiveIntegerField(null=True, blank=True)
    cooldown_hours = models.PositiveIntegerField(default=24)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "notification_rules"

    def __str__(self) -> str:
        return f"{self.finding_type_id}→{self.route_id}"


class NotificationState(TenantScopedModel):
    """Dedup + cooldown tracking per fingerprint + rule pair."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fingerprint = models.CharField(max_length=255)
    rule = models.ForeignKey(
        NotificationRule, on_delete=models.PROTECT, related_name="state_entries"
    )
    last_sent_at = models.DateTimeField()
    next_allowed_at = models.DateTimeField()
    send_count = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "notification_state"
        constraints = (
            models.UniqueConstraint(
                fields=("tenant", "fingerprint", "rule"),
                name="uq_notification_state_fingerprint_rule",
            ),
        )

    def __str__(self) -> str:
        return f"{self.fingerprint[:40]}:{self.rule_id}"


class NotificationEvent(TenantScopedModel):
    """Delivery audit trail for all notification attempts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(
        NotificationRule, on_delete=models.PROTECT, null=True, blank=True,
        related_name="events",
    )
    fingerprint = models.CharField(max_length=255)
    channel = models.CharField(max_length=16)
    status = models.CharField(max_length=16)
    payload_ref = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_events"
        indexes = (
            models.Index(fields=("tenant", "sent_at"), name="idx_notif_events_sent_at"),
        )

    def __str__(self) -> str:
        return f"{self.channel}:{self.status}:{self.fingerprint[:32]}"


class SuppressionRule(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding_type = models.ForeignKey(FindingType, on_delete=models.PROTECT, related_name="suppression_rules")
    subject_match = models.JSONField(default=dict)
    reason = models.TextField()
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="suppression_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "suppression_rules"
        indexes = (
            models.Index(fields=("tenant", "finding_type"), name="idx_suppression_rules_type"),
        )

    def __str__(self) -> str:
        return self.reason[:80]


class NotificationRoute(TenantScopedModel):
    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"
        INFO = "info", "Info"

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SLACK = "slack", "Slack"
        TEAMS = "teams", "Teams"
        WEBHOOK = "webhook", "Webhook"
        ZENDESK = "zendesk", "Zendesk"

    class Mode(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate"
        DIGEST = "digest", "Digest"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="notification_routes")
    finding_type = models.ForeignKey(FindingType, on_delete=models.PROTECT, null=True, blank=True, related_name="notification_routes")
    severity_min = models.CharField(max_length=16, choices=Severity.choices)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    target = models.TextField()
    mode = models.CharField(max_length=16, choices=Mode.choices)

    class Meta:
        db_table = "notification_routes"

    def __str__(self) -> str:
        return f"{self.channel}:{self.target}"


class Secret(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    encrypted_value = models.BinaryField()
    rotated_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_secrets",
    )

    class Meta:
        db_table = "secrets"
        constraints = (
            models.UniqueConstraint(fields=("tenant", "name"), name="uq_secrets_tenant_name"),
        )

    def __str__(self) -> str:
        return self.name


class AuditLog(TenantScopedModel):
    class ActorKind(models.TextChoices):
        USER = "user", "User"
        COLLECTOR = "collector", "Collector"
        SYSTEM = "system", "System"

    class Source(models.TextChoices):
        UI = "ui", "UI"
        API = "api", "API"
        INGEST = "ingest", "Ingest"
        MANAGEMENT_COMMAND = "management_command", "Management command"
        BACKGROUND_JOB = "background_job", "Background job"
        CELERY = "celery", "Celery"

    audit_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_kind = models.CharField(max_length=16, choices=ActorKind.choices)
    source = models.CharField(max_length=32, choices=Source.choices)
    action = models.CharField(max_length=120)
    entity_type = models.CharField(max_length=80)
    entity_id = models.UUIDField(null=True, blank=True)
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        indexes = (
            models.Index(fields=("tenant", "occurred_at"), name="idx_audit_log_occurred_at"),
            models.Index(fields=("tenant", "entity_type", "entity_id"), name="idx_audit_log_entity"),
        )

    def __str__(self) -> str:
        return f"{self.action}:{self.entity_type}:{self.entity_id}"


class RunLog(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=80)
    subject_ref = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    rows = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "run_log"
        indexes = (
            models.Index(fields=("tenant", "kind", "started_at"), name="idx_run_log_kind_started"),
        )

    def __str__(self) -> str:
        return f"{self.kind}:{self.started_at}"


class UserGroup(TenantScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    class Meta:
        db_table = "user_groups"
        constraints = (
            models.UniqueConstraint(fields=["tenant", "user", "group"], name="uq_user_groups_tenant_user_group"),
        )

    def __str__(self) -> str:
        return f"{self.user_id}:{self.group_id}"


class UserPermission(TenantScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        db_table = "user_permissions"
        constraints = (
            models.UniqueConstraint(
                fields=["tenant", "user", "permission"],
                name="uq_user_permissions_tenant_user_permission",
            ),
        )

    def __str__(self) -> str:
        return f"{self.user_id}:{self.permission_id}"
