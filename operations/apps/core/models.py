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


class FindingType(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    id = models.SmallAutoField(primary_key=True)
    name = models.CharField(max_length=120, unique=True)
    default_severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
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
    deleted_at = models.DateTimeField(null=True, blank=True)

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
    class DeviceKind(models.TextChoices):
        PHYSICAL = "physical", "Physical"
        VM_WITH_AGENT = "vm-with-agent", "VM with agent"
        VM_AGENTLESS = "vm-agentless", "VM agentless"
        HYPERVISOR_HOST = "hypervisor-host", "Hypervisor host"
        NETWORK_DEVICE = "network-device", "Network device"
        UNKNOWN = "unknown", "Unknown"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="devices")
    canonical_hostname = models.CharField(max_length=255)
    canonical_serial = models.CharField(max_length=255, blank=True)
    canonical_vm_uuid = models.CharField(max_length=64, blank=True)
    device_kind = models.CharField(
        max_length=32,
        choices=DeviceKind.choices,
        default=DeviceKind.UNKNOWN,
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "devices"
        ordering = ("canonical_hostname",)

    def __str__(self) -> str:
        return self.canonical_hostname


class DeviceLink(UUIDTenantScopedModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="links")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="device_links")
    external_id = models.CharField(max_length=240)
    external_name = models.CharField(max_length=240, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

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

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="software_decisions")
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
            models.UniqueConstraint(
                fields=("tenant", "client", "canonical_name"),
                name="uq_software_decisions_tenant_client_name",
            ),
        )

    def __str__(self) -> str:
        return f"{self.client_id}:{self.canonical_name}:{self.decision}"


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

    finding_type = models.ForeignKey(FindingType, on_delete=models.PROTECT, related_name="findings")
    subject_type = models.CharField(max_length=32, choices=SubjectType.choices)
    subject_id = models.UUIDField()
    finding_details = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
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
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "findings"
        indexes = (
            models.Index(fields=("tenant", "status", "severity"), name="idx_findings_status_severity"),
            models.Index(fields=("tenant", "subject_type", "subject_id"), name="idx_findings_subject"),
        )

    def __str__(self) -> str:
        return f"{self.finding_type_id}:{self.subject_type}:{self.subject_id}"


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
