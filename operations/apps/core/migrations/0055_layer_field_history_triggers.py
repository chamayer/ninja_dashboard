"""Migration 0055 — activate layer-entity field-history audit triggers.

Per ADR-0006. The `asset_field_history`, `os_instance_field_history`,
and `agent_instance_field_history` audit tables were scaffolded in
ADR-0005 slice 1 (migration 0050) but never wired. This migration
adds AFTER UPDATE triggers on each layer table that write one audit
row per changed significant field, filtered by a WHEN clause so
heartbeat / last_seen churn doesn't generate noise.

**Significant fields (audited):**

- `assets`: form_factor, serial, vm_uuid, chassis
- `os_instances`: os_name, os_family, os_group, os_version
- `agent_instances`: agent_version

**Explicitly NOT audited:**

- Timestamps (updated_at, last_seen_at, first_seen_at)
- Heartbeat / presence metadata
- Effective window columns (effective_from / effective_to) —
  ADR-0006 documents these as escape-hatch, not lifecycle events
- JSON state blobs (virtualization, patch_state, config_state,
  coverage_state) — noisy diff semantics; audit at operator-visible
  granularity if that ever matters
- `install_token` on AgentInstance — documented as unused per ADR-0006

**Change context:** trigger writes `change_reason = 'trigger.audit'`
and leaves `change_source_id` NULL. Adding richer context (per-writer
source binding, transaction reason) would require SET LOCAL plumbing
from every writer; v1 skips that. `changed_at` is populated by the
table's `auto_now_add` default (equivalent to NOW() on INSERT).

**Payoff:** the audit tables become queryable timelines for
per-layer trends and forensics — e.g., "how often does os_version
change on Windows devices" or "what was agent_version on device X on
date D." This is the history mechanism under ADR-0006's
attribute-bucket frame.
"""

from __future__ import annotations

from django.db import migrations


_ASSET_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION operations.audit_asset_significant_fields()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.form_factor IS DISTINCT FROM OLD.form_factor THEN
        INSERT INTO operations.asset_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'form_factor',
             to_jsonb(OLD.form_factor), to_jsonb(NEW.form_factor),
             'trigger.audit');
    END IF;
    IF NEW.serial IS DISTINCT FROM OLD.serial THEN
        INSERT INTO operations.asset_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'serial',
             to_jsonb(OLD.serial), to_jsonb(NEW.serial),
             'trigger.audit');
    END IF;
    IF NEW.vm_uuid IS DISTINCT FROM OLD.vm_uuid THEN
        INSERT INTO operations.asset_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'vm_uuid',
             to_jsonb(OLD.vm_uuid), to_jsonb(NEW.vm_uuid),
             'trigger.audit');
    END IF;
    IF NEW.chassis IS DISTINCT FROM OLD.chassis THEN
        INSERT INTO operations.asset_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'chassis',
             to_jsonb(OLD.chassis), to_jsonb(NEW.chassis),
             'trigger.audit');
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_asset_fields
    AFTER UPDATE ON operations.assets
    FOR EACH ROW
    WHEN (
        NEW.form_factor IS DISTINCT FROM OLD.form_factor
        OR NEW.serial IS DISTINCT FROM OLD.serial
        OR NEW.vm_uuid IS DISTINCT FROM OLD.vm_uuid
        OR NEW.chassis IS DISTINCT FROM OLD.chassis
    )
    EXECUTE FUNCTION operations.audit_asset_significant_fields();
"""

_ASSET_TRIGGER_REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_asset_fields ON operations.assets;
DROP FUNCTION IF EXISTS operations.audit_asset_significant_fields();
"""

_OS_INSTANCE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION operations.audit_os_instance_significant_fields()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.os_name IS DISTINCT FROM OLD.os_name THEN
        INSERT INTO operations.os_instance_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'os_name',
             to_jsonb(OLD.os_name), to_jsonb(NEW.os_name),
             'trigger.audit');
    END IF;
    IF NEW.os_family IS DISTINCT FROM OLD.os_family THEN
        INSERT INTO operations.os_instance_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'os_family',
             to_jsonb(OLD.os_family), to_jsonb(NEW.os_family),
             'trigger.audit');
    END IF;
    IF NEW.os_group IS DISTINCT FROM OLD.os_group THEN
        INSERT INTO operations.os_instance_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'os_group',
             to_jsonb(OLD.os_group), to_jsonb(NEW.os_group),
             'trigger.audit');
    END IF;
    IF NEW.os_version IS DISTINCT FROM OLD.os_version THEN
        INSERT INTO operations.os_instance_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'os_version',
             to_jsonb(OLD.os_version), to_jsonb(NEW.os_version),
             'trigger.audit');
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_os_instance_fields
    AFTER UPDATE ON operations.os_instances
    FOR EACH ROW
    WHEN (
        NEW.os_name IS DISTINCT FROM OLD.os_name
        OR NEW.os_family IS DISTINCT FROM OLD.os_family
        OR NEW.os_group IS DISTINCT FROM OLD.os_group
        OR NEW.os_version IS DISTINCT FROM OLD.os_version
    )
    EXECUTE FUNCTION operations.audit_os_instance_significant_fields();
"""

_OS_INSTANCE_TRIGGER_REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_os_instance_fields ON operations.os_instances;
DROP FUNCTION IF EXISTS operations.audit_os_instance_significant_fields();
"""

_AGENT_INSTANCE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION operations.audit_agent_instance_significant_fields()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.agent_version IS DISTINCT FROM OLD.agent_version THEN
        INSERT INTO operations.agent_instance_field_history
            (id, tenant_id, version, layer_entity_id, field_name,
             old_value, new_value, change_reason)
        VALUES
            (gen_random_uuid(), NEW.tenant_id, 1, NEW.id, 'agent_version',
             to_jsonb(OLD.agent_version), to_jsonb(NEW.agent_version),
             'trigger.audit');
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_agent_instance_fields
    AFTER UPDATE ON operations.agent_instances
    FOR EACH ROW
    WHEN (NEW.agent_version IS DISTINCT FROM OLD.agent_version)
    EXECUTE FUNCTION operations.audit_agent_instance_significant_fields();
"""

_AGENT_INSTANCE_TRIGGER_REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_agent_instance_fields ON operations.agent_instances;
DROP FUNCTION IF EXISTS operations.audit_agent_instance_significant_fields();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0054_retire_identity_candidates"),
    ]

    operations = [
        migrations.RunSQL(_ASSET_TRIGGER_SQL, _ASSET_TRIGGER_REVERSE_SQL),
        migrations.RunSQL(_OS_INSTANCE_TRIGGER_SQL, _OS_INSTANCE_TRIGGER_REVERSE_SQL),
        migrations.RunSQL(_AGENT_INSTANCE_TRIGGER_SQL, _AGENT_INSTANCE_TRIGGER_REVERSE_SQL),
    ]
