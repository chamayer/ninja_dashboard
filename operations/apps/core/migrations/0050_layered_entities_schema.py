"""Migration 0050 — layered entities schema (ADR-0005 slice 1a).

Per `operations/docs/decisions/0005-device-identity-and-layered-entities.md`.
Adds three canonical layer entities that together describe a Device:

- `assets` — hardware / virtual asset (form factor, serial, vm_uuid,
  chassis, virtualization). Effective-windowed; one open row per Device.
- `os_instances` — OS install (os_name, os_family, os_group, os_version,
  patch/config state). Effective-windowed; one open row per Device.
- `agent_instances` — per-(Device, Agent product) install lifetime
  (version, install token, coverage state). Effective-windowed; one open
  row per (Device, Agent).

Plus per-layer significant-field audit tables:

- `asset_field_history`
- `os_instance_field_history`
- `agent_instance_field_history`

Plus `findings.subject_layer` + `findings.subject_layer_entity_id`
back-reference columns.

**Scope of this migration (v1, slice 1a):**

- Schema only. No backfill (0051) and no view refresh (0052).
- Additive — flat `Device` attribute columns (`device_type`, `os_name`,
  `os_family`, `os_group`, `canonical_serial`, `canonical_vm_uuid`) are
  untouched and stay as a denormalized current-state cache until the
  ingest write path populates the layer entities. Consumers keep reading
  the existing surface.
- RLS enabled per the standard `tenant_isolation` pattern; grants match
  existing per-role conventions from migrations 0006 / 0041 / 0043.

**Constraints:**

- Partial unique index on (tenant, device_id) WHERE effective_to IS NULL
  for `assets` and `os_instances` — at most one open window per Device
  per layer.
- Partial unique index on (tenant, device_id, agent_id) WHERE
  effective_to IS NULL for `agent_instances` — multiple concurrent open
  AgentInstances per Device (one per agent product), but only one open
  per product.
- CHECK effective_from < effective_to OR effective_to IS NULL on all
  three layer tables.
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


_RLS_SQL = """
-- Asset layer -------------------------------------------------------------
ALTER TABLE operations.assets ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.assets
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.assets TO operations_app;
GRANT SELECT ON operations.assets TO operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.assets TO ninja_ingest;

ALTER TABLE operations.asset_field_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.asset_field_history
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT ON operations.asset_field_history TO operations_app;
GRANT SELECT ON operations.asset_field_history TO operations_readonly, metabase_ro;
GRANT INSERT ON operations.asset_field_history TO ninja_ingest;

-- OS instance layer -------------------------------------------------------
ALTER TABLE operations.os_instances ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.os_instances
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.os_instances TO operations_app;
GRANT SELECT ON operations.os_instances TO operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.os_instances TO ninja_ingest;

ALTER TABLE operations.os_instance_field_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.os_instance_field_history
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT ON operations.os_instance_field_history TO operations_app;
GRANT SELECT ON operations.os_instance_field_history TO operations_readonly, metabase_ro;
GRANT INSERT ON operations.os_instance_field_history TO ninja_ingest;

-- Agent instance layer ----------------------------------------------------
ALTER TABLE operations.agent_instances ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.agent_instances
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.agent_instances TO operations_app;
GRANT SELECT ON operations.agent_instances TO operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.agent_instances TO ninja_ingest;

ALTER TABLE operations.agent_instance_field_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.agent_instance_field_history
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
GRANT SELECT, INSERT ON operations.agent_instance_field_history TO operations_app;
GRANT SELECT ON operations.agent_instance_field_history TO operations_readonly, metabase_ro;
GRANT INSERT ON operations.agent_instance_field_history TO ninja_ingest;
"""

_RLS_REVERSE_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON operations.assets;
DROP POLICY IF EXISTS tenant_isolation ON operations.asset_field_history;
DROP POLICY IF EXISTS tenant_isolation ON operations.os_instances;
DROP POLICY IF EXISTS tenant_isolation ON operations.os_instance_field_history;
DROP POLICY IF EXISTS tenant_isolation ON operations.agent_instances;
DROP POLICY IF EXISTS tenant_isolation ON operations.agent_instance_field_history;
"""


_EFFECTIVE_WINDOW_CHECK_SQL = """
ALTER TABLE operations.assets
    ADD CONSTRAINT ck_assets_effective_window
    CHECK (effective_to IS NULL OR effective_from < effective_to);

ALTER TABLE operations.os_instances
    ADD CONSTRAINT ck_os_inst_effective_window
    CHECK (effective_to IS NULL OR effective_from < effective_to);

ALTER TABLE operations.agent_instances
    ADD CONSTRAINT ck_agent_inst_effective_window
    CHECK (effective_to IS NULL OR effective_from < effective_to);
"""

_EFFECTIVE_WINDOW_CHECK_REVERSE_SQL = """
ALTER TABLE operations.assets DROP CONSTRAINT IF EXISTS ck_assets_effective_window;
ALTER TABLE operations.os_instances DROP CONSTRAINT IF EXISTS ck_os_inst_effective_window;
ALTER TABLE operations.agent_instances DROP CONSTRAINT IF EXISTS ck_agent_inst_effective_window;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0049_client_health_trend_current"),
    ]

    operations = [
        # ── Asset layer ──────────────────────────────────────────────
        # Broad asset entity — `asset_type` distinguishes endpoint
        # hardware (the v1 populated case) from future peripherals,
        # licenses, network appliances, and services. Only the
        # endpoint_hardware case is Device-bound in v1.
        migrations.CreateModel(
            name="Asset",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("asset_type", models.CharField(
                    max_length=32,
                    choices=[
                        ("endpoint_hardware", "Endpoint hardware"),
                        ("peripheral", "Peripheral"),
                        ("network_appliance", "Network appliance"),
                        ("license", "License"),
                        ("service", "Service"),
                        ("other", "Other"),
                    ],
                    default="endpoint_hardware",
                )),
                ("form_factor", models.CharField(
                    max_length=32,
                    choices=[
                        ("physical", "Physical"),
                        ("vm", "VM"),
                        ("hypervisor-host", "Hypervisor host"),
                        ("network-device", "Network device"),
                        ("unknown", "Unknown"),
                    ],
                    default="unknown",
                )),
                ("serial", models.CharField(max_length=255, blank=True, default="")),
                ("vm_uuid", models.CharField(max_length=64, blank=True, default="")),
                ("chassis", models.CharField(max_length=120, blank=True, default="")),
                ("virtualization", models.JSONField(default=dict, blank=True)),
                ("effective_from", models.DateTimeField()),
                ("effective_to", models.DateTimeField(null=True, blank=True)),
                ("first_seen_at", models.DateTimeField()),
                ("last_seen_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("device", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    null=True, blank=True,
                    related_name="assets",
                    to="operations.device",
                )),
                ("first_observed_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="first_observed_assets",
                    to="operations.source",
                )),
                ("last_observed_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="last_observed_assets",
                    to="operations.source",
                )),
            ],
            options={"db_table": "assets"},
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(fields=["tenant", "device"], name="idx_assets_tenant_device"),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(fields=["tenant", "asset_type"], name="idx_assets_tenant_type"),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(fields=["tenant", "effective_to"], name="idx_assets_effective_to"),
        ),
        migrations.AddConstraint(
            model_name="asset",
            constraint=models.UniqueConstraint(
                fields=("tenant", "device"),
                condition=Q(effective_to__isnull=True)
                & Q(device__isnull=False)
                & Q(asset_type="endpoint_hardware"),
                name="uq_assets_one_open_endpoint_per_device",
            ),
        ),

        # ── OS instance layer ────────────────────────────────────────
        migrations.CreateModel(
            name="OSInstance",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("os_name", models.CharField(max_length=200, blank=True, default="")),
                ("os_family", models.CharField(max_length=40, blank=True, default="")),
                ("os_group", models.CharField(max_length=16, blank=True, default="Unknown")),
                ("os_version", models.CharField(max_length=80, blank=True, default="")),
                ("install_identifier", models.CharField(max_length=120, blank=True, default="")),
                ("patch_state", models.JSONField(default=dict, blank=True)),
                ("config_state", models.JSONField(default=dict, blank=True)),
                ("effective_from", models.DateTimeField()),
                ("effective_to", models.DateTimeField(null=True, blank=True)),
                ("first_seen_at", models.DateTimeField()),
                ("last_seen_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("device", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="os_instances",
                    to="operations.device",
                )),
                ("first_observed_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="first_observed_os_instances",
                    to="operations.source",
                )),
                ("last_observed_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="last_observed_os_instances",
                    to="operations.source",
                )),
            ],
            options={"db_table": "os_instances"},
        ),
        migrations.AddIndex(
            model_name="osinstance",
            index=models.Index(fields=["tenant", "device"], name="idx_os_inst_tenant_device"),
        ),
        migrations.AddIndex(
            model_name="osinstance",
            index=models.Index(fields=["tenant", "effective_to"], name="idx_os_inst_effective_to"),
        ),
        migrations.AddConstraint(
            model_name="osinstance",
            constraint=models.UniqueConstraint(
                fields=("tenant", "device"),
                condition=Q(effective_to__isnull=True),
                name="uq_os_inst_one_open_per_device",
            ),
        ),

        # ── Agent instance layer ─────────────────────────────────────
        migrations.CreateModel(
            name="AgentInstance",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("install_token", models.CharField(max_length=240, blank=True, default="")),
                ("agent_version", models.CharField(max_length=80, blank=True, default="")),
                ("coverage_state", models.JSONField(default=dict, blank=True)),
                ("effective_from", models.DateTimeField()),
                ("effective_to", models.DateTimeField(null=True, blank=True)),
                ("first_seen_at", models.DateTimeField()),
                ("last_seen_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("device", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="agent_instances",
                    to="operations.device",
                )),
                ("agent", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="instances",
                    to="operations.agent",
                )),
                ("first_observed_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="first_observed_agent_instances",
                    to="operations.source",
                )),
                ("last_observed_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="last_observed_agent_instances",
                    to="operations.source",
                )),
            ],
            options={"db_table": "agent_instances"},
        ),
        migrations.AddIndex(
            model_name="agentinstance",
            index=models.Index(fields=["tenant", "device"], name="idx_agent_inst_tenant_device"),
        ),
        migrations.AddIndex(
            model_name="agentinstance",
            index=models.Index(fields=["tenant", "agent"], name="idx_agent_inst_tenant_agent"),
        ),
        migrations.AddIndex(
            model_name="agentinstance",
            index=models.Index(fields=["tenant", "effective_to"], name="idx_agent_inst_effective_to"),
        ),
        migrations.AddConstraint(
            model_name="agentinstance",
            constraint=models.UniqueConstraint(
                fields=("tenant", "device", "agent"),
                condition=Q(effective_to__isnull=True),
                name="uq_agent_inst_one_open_per_device_agent",
            ),
        ),

        # ── Per-layer field-history (significant fields only) ───────
        migrations.CreateModel(
            name="AssetFieldHistory",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("layer_entity_id", models.UUIDField()),
                ("field_name", models.CharField(max_length=80)),
                ("old_value", models.JSONField(null=True, blank=True)),
                ("new_value", models.JSONField(null=True, blank=True)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("change_reason", models.CharField(max_length=120, blank=True, default="")),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("change_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    to="operations.source",
                )),
            ],
            options={"db_table": "asset_field_history"},
        ),
        migrations.AddIndex(
            model_name="assetfieldhistory",
            index=models.Index(fields=["tenant", "layer_entity_id"], name="idx_asset_fh_entity"),
        ),
        migrations.AddIndex(
            model_name="assetfieldhistory",
            index=models.Index(fields=["tenant", "changed_at"], name="idx_asset_fh_changed_at"),
        ),

        migrations.CreateModel(
            name="OSInstanceFieldHistory",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("layer_entity_id", models.UUIDField()),
                ("field_name", models.CharField(max_length=80)),
                ("old_value", models.JSONField(null=True, blank=True)),
                ("new_value", models.JSONField(null=True, blank=True)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("change_reason", models.CharField(max_length=120, blank=True, default="")),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("change_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    to="operations.source",
                )),
            ],
            options={"db_table": "os_instance_field_history"},
        ),
        migrations.AddIndex(
            model_name="osinstancefieldhistory",
            index=models.Index(fields=["tenant", "layer_entity_id"], name="idx_os_inst_fh_entity"),
        ),
        migrations.AddIndex(
            model_name="osinstancefieldhistory",
            index=models.Index(fields=["tenant", "changed_at"], name="idx_os_inst_fh_changed_at"),
        ),

        migrations.CreateModel(
            name="AgentInstanceFieldHistory",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("layer_entity_id", models.UUIDField()),
                ("field_name", models.CharField(max_length=80)),
                ("old_value", models.JSONField(null=True, blank=True)),
                ("new_value", models.JSONField(null=True, blank=True)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("change_reason", models.CharField(max_length=120, blank=True, default="")),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to="operations.tenant",
                )),
                ("change_source", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    to="operations.source",
                )),
            ],
            options={"db_table": "agent_instance_field_history"},
        ),
        migrations.AddIndex(
            model_name="agentinstancefieldhistory",
            index=models.Index(fields=["tenant", "layer_entity_id"], name="idx_agent_inst_fh_entity"),
        ),
        migrations.AddIndex(
            model_name="agentinstancefieldhistory",
            index=models.Index(fields=["tenant", "changed_at"], name="idx_agent_inst_fh_changed_at"),
        ),

        # ── Finding layer back-reference ────────────────────────────
        migrations.AddField(
            model_name="finding",
            name="subject_layer",
            field=models.CharField(
                max_length=16,
                choices=[("asset", "Asset"), ("os", "OS instance"), ("agent", "Agent instance")],
                blank=True, default="",
            ),
        ),
        migrations.AddField(
            model_name="finding",
            name="subject_layer_entity_id",
            field=models.UUIDField(null=True, blank=True),
        ),
        migrations.AddIndex(
            model_name="finding",
            index=models.Index(
                fields=["tenant", "subject_layer", "subject_layer_entity_id"],
                name="idx_findings_layer_entity",
                condition=Q(subject_layer_entity_id__isnull=False),
            ),
        ),

        # ── RLS + grants + effective-window checks ──────────────────
        migrations.RunSQL(_RLS_SQL, _RLS_REVERSE_SQL),
        migrations.RunSQL(_EFFECTIVE_WINDOW_CHECK_SQL, _EFFECTIVE_WINDOW_CHECK_REVERSE_SQL),
    ]
