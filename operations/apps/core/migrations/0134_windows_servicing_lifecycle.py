"""Carry Ninja Windows build evidence into automated servicing lifecycle state."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

NINJA_SOURCE_INSTANCE_ID = "00000000-0000-4000-8000-000000000010"


SEED_SQL = r"""
INSERT INTO operations.attribute_definitions (
    entity_class_id, key, display_name, description, value_type, cardinality,
    sensitivity, validation, canonical_projection_eligible,
    single_value_conflict_policy, set_merge_policy, definition_version, enabled
)
VALUES
    ('device', 'os_build_number', 'OS build number',
     'Source-reported operating-system build number.',
     'text', 'single', 'internal', '{}'::jsonb, FALSE,
     'retain_last_uncontested', 'highest_authority_union', 1, TRUE),
    ('device', 'os_release_id', 'OS release ID',
     'Source-reported operating-system release identifier.',
     'text', 'single', 'internal', '{}'::jsonb, FALSE,
     'retain_last_uncontested', 'highest_authority_union', 1, TRUE)
ON CONFLICT (entity_class_id, key, definition_version) DO NOTHING;

INSERT INTO operations.source_field_mappings (
    source_id, external_namespace, native_record_type, document_kind,
    source_field, attribute_definition_id, mapping_version, enabled
)
SELECT NULL, '', '', 'canonical', mapping.source_field, definition.id, 1, TRUE
FROM (VALUES
    ('os_build_number', 'os_build_number'),
    ('os_release_id', 'os_release_id')
) AS mapping(attribute_key, source_field)
JOIN operations.attribute_definitions definition
  ON definition.entity_class_id = 'device'
 AND definition.key = mapping.attribute_key
 AND definition.enabled
ON CONFLICT (
    source_id, external_namespace, native_record_type, document_kind,
    source_field, mapping_version
) DO NOTHING;

INSERT INTO operations.attribute_authority_policies (
    id, tenant_id, version, source_instance_id, native_record_type,
    attribute_definition_id, eligible, authority_tier, priority, enabled, reason
)
SELECT gen_random_uuid(), observed.tenant_id, 1, observed.source_instance_id,
       observed.entity_type, definition.id,
       observed.entity_type IN (
           'agent.rmm', 'agent.edr', 'agent.remote_access',
           'network.device', 'vm.host', 'vm.guest', 'monitor.target', 'org'
       ),
       CASE
         WHEN observed.entity_type = 'agent.rmm' THEN 300
         WHEN observed.entity_type = 'agent.edr' THEN 250
         WHEN observed.entity_type = 'agent.remote_access' THEN 225
         WHEN observed.entity_type IN ('network.device', 'vm.host', 'org') THEN 200
         WHEN observed.entity_type = 'vm.guest' THEN 150
         WHEN observed.entity_type = 'monitor.target' THEN 100
         ELSE 0
       END,
       0, TRUE, 'system.windows_servicing_lifecycle'
FROM (
    SELECT DISTINCT o.tenant_id, o.source_instance_id, o.entity_type,
           COALESCE(link.entity_class_id, entity_type.entity_class_id)
               AS entity_class_id
    FROM operations.entity_observation_current o
    LEFT JOIN operations.entity_source_links link
      ON link.tenant_id = o.tenant_id
     AND link.source_instance_id = o.source_instance_id
     AND link.external_namespace = o.external_namespace
     AND link.parent_external_namespace = o.parent_external_namespace
     AND link.parent_external_id = o.parent_external_id
     AND link.external_id = o.external_id
    LEFT JOIN operations.entity_types entity_type
      ON entity_type.name = o.entity_type
) observed
JOIN operations.attribute_definitions definition
  ON definition.entity_class_id = observed.entity_class_id
 AND definition.key IN ('os_build_number', 'os_release_id')
 AND definition.enabled
ON CONFLICT (
    tenant_id, source_instance_id, native_record_type, attribute_definition_id
) DO NOTHING;

INSERT INTO operations.finding_types (
    id, name, default_severity, runbook_path, description,
    finding_class, source_module, subject_scope, creates_device_exposure,
    auto_resolvable, category_id
)
SELECT (SELECT COALESCE(MAX(id), 0) FROM operations.finding_types)
           + row_number() OVER (ORDER BY finding.name),
       finding.name, finding.severity, '', finding.description,
       'entity', 'ingest.intel.windows_servicing', 'device', TRUE, TRUE,
       category.id
FROM (VALUES
    ('windows_servicing_eol', 'high',
     'The installed Windows build has passed its base security-support end date. '
     'Extended updates, when listed, require separate entitlement verification.'),
    ('windows_servicing_approaching_eol', 'medium',
     'The installed Windows build reaches end of security support within 180 days.'),
    ('windows_servicing_unknown', 'low',
     'Windows servicing state could not be resolved deterministically from the '
     'reported OS evidence and current lifecycle corpus.')
) AS finding(name, severity, description)
JOIN operations.finding_categories category ON category.name = 'lifecycle'
WHERE NOT EXISTS (
    SELECT 1 FROM operations.finding_types existing
    WHERE existing.name = finding.name
);
"""


DETAIL_VIEW_SQL = f"""
CREATE OR REPLACE VIEW operations.ninja_device_detail_current_shadow
WITH (security_invoker = true) AS
SELECT
    c.observed_at AS snapshot_at,
    c.external_id::integer AS device_id,
    CASE lower(c.canonical_data ->> 'offline')
        WHEN 'true' THEN TRUE WHEN 'false' THEN FALSE ELSE NULL
    END AS offline,
    NULLIF(c.canonical_data ->> 'last_contact_at', '')::timestamptz AS last_contact,
    NULLIF(c.canonical_data ->> 'last_boot_time_at', '')::timestamptz AS last_boot,
    CASE lower(c.canonical_data ->> 'needs_reboot')
        WHEN 'true' THEN TRUE WHEN 'false' THEN FALSE ELSE NULL
    END AS needs_reboot,
    CASE
        WHEN jsonb_typeof(c.canonical_data -> 'needs_reboot_reasons') = 'array'
        THEN ARRAY(SELECT jsonb_array_elements_text(c.canonical_data -> 'needs_reboot_reasons'))
        ELSE NULL::text[]
    END AS needs_reboot_reasons,
    NULLIF(c.canonical_data ->> 'last_user', '') AS last_user,
    NULLIF(c.canonical_data ->> 'maintenance_status', '') AS maintenance_status,
    NULLIF(c.canonical_data ->> 'maintenance_start_at', '')::timestamptz
        AS maintenance_start,
    NULLIF(c.canonical_data ->> 'maintenance_end_at', '')::timestamptz
        AS maintenance_end,
    c.raw_data AS data,
    c.raw_hash,
    c.material_hash,
    c.material_projection_version
FROM operations.entity_observation_current c
WHERE c.active IS TRUE
  AND lower(c.platform) = 'ninja'
  AND c.external_namespace = 'device'
  AND c.external_id ~ '^[0-9]+$'
  AND c.source_instance_id = '{NINJA_SOURCE_INSTANCE_ID}'::uuid
  AND c.snapshot_scope = 'Ninja'
  AND c.material_projection_version IN (3, 4);
"""


DEVICE_READ_MODEL_SQL = f"""
DROP VIEW operations.v_device;
DROP MATERIALIZED VIEW operations.device_session_current;

CREATE MATERIALIZED VIEW operations.device_session_current AS
WITH source_online AS (
    SELECT apc.device_id, apc.platform, apc.entity_type, apc.last_observed_at,
           apc.last_contact_at, apc.last_power_state,
           apc.reported_online AS is_online_now
    FROM operations.device_agent_presence_current apc
), per_device_presence AS (
    SELECT so.device_id, MAX(so.last_contact_at) AS last_contact_at,
           MAX(so.last_observed_at) AS last_observed_at,
           BOOL_OR(so.is_online_now) AS is_online_any,
           ARRAY_AGG(DISTINCT so.platform ORDER BY so.platform)
             FILTER (WHERE so.is_online_now) AS online_sources,
           COUNT(DISTINCT so.platform)
             FILTER (WHERE so.is_online_now) AS source_count_active,
           (ARRAY_AGG(so.last_power_state ORDER BY so.last_observed_at DESC)
             FILTER (WHERE so.entity_type = 'vm.guest'))[1] AS last_power_state
    FROM source_online so
    GROUP BY so.device_id
), device_reboot AS (
    SELECT DISTINCT ON (o.device_id)
           o.device_id AS ops_device_id,
           CASE lower(o.canonical_data ->> 'needs_reboot')
             WHEN 'true' THEN TRUE WHEN 'false' THEN FALSE ELSE NULL
           END AS needs_reboot,
           NULLIF(o.canonical_data ->> 'last_boot_time_at', '')::timestamptz
             AS last_boot
    FROM operations.entity_observation_current o
    WHERE o.tenant_id = 1
      AND o.active IS TRUE
      AND o.device_id IS NOT NULL
      AND o.source_instance_id = '{NINJA_SOURCE_INSTANCE_ID}'::uuid
      AND o.external_namespace = 'device'
      AND o.snapshot_scope = 'Ninja'
      AND o.material_projection_version IN (3, 4)
    ORDER BY o.device_id, o.observed_at DESC,
             (o.entity_type = 'agent.rmm') DESC, o.external_id
)
SELECT d.tenant_id, d.client_id, d.id AS device_id, p.last_contact_at,
       p.last_observed_at, COALESCE(p.is_online_any, FALSE) AS is_online_any,
       COALESCE(p.online_sources, ARRAY[]::text[]) AS online_sources,
       COALESCE(p.source_count_active, 0) AS source_count_active,
       r.needs_reboot, r.last_boot AS last_boot_at, p.last_power_state,
       NOW() AS computed_at
FROM operations.devices d
LEFT JOIN per_device_presence p ON p.device_id = d.id
LEFT JOIN device_reboot r ON r.ops_device_id = d.id
WHERE d.deleted_at IS NULL
WITH DATA;

CREATE UNIQUE INDEX idx_device_session_current_pk
    ON operations.device_session_current (tenant_id, device_id);
CREATE INDEX idx_device_session_current_online
    ON operations.device_session_current (tenant_id, is_online_any);
CREATE INDEX idx_device_session_current_reboot
    ON operations.device_session_current (tenant_id, needs_reboot)
    WHERE needs_reboot;
GRANT SELECT ON operations.device_session_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.device_session_current OWNER TO operations_migrate;

CREATE VIEW operations.v_device WITH (security_invoker = true) AS
SELECT d.tenant_id, d.id AS device_id, d.client_id, d.version,
       d.canonical_hostname, d.canonical_serial, d.canonical_vm_uuid,
       d.device_type, d.device_role, d.lifecycle_status, d.os_name,
       d.os_family, d.os_group, d.created_at, d.created_reason, d.updated_at,
       d.updated_reason, d.stale_since, d.stale_reason, d.deleted_at,
       d.deleted_reason, ds.last_contact_at, ds.last_observed_at,
       COALESCE(ds.is_online_any, FALSE) AS is_online_any,
       COALESCE(ds.online_sources, ARRAY[]::text[]) AS online_sources,
       COALESCE(ds.source_count_active, 0) AS source_count_active,
       ds.needs_reboot, ds.last_boot_at, ds.last_power_state,
       ds.computed_at AS session_computed_at,
       COALESCE(op_exemptions.value, '{{}}'::jsonb) AS exemptions,
       ps.scope_derived AS patching_scope_derived,
       ps.scope_reason AS patching_scope_reason,
       ps.computed_at AS patching_scope_computed_at,
       op_patching.scope AS patching_scope_override,
       op_patching.reason AS patching_scope_override_reason,
       COALESCE(op_patching.scope, ps.scope_derived, 'Unmanaged')
         AS effective_patching_scope
FROM operations.devices d
LEFT JOIN operations.device_session_current ds
  ON ds.tenant_id = d.tenant_id AND ds.device_id = d.id
LEFT JOIN operations.device_operator_decisions op_exemptions
  ON op_exemptions.tenant_id = d.tenant_id
 AND op_exemptions.device_id = d.id
 AND op_exemptions.dimension = 'exemptions'
LEFT JOIN operations.device_patching_scope_current ps
  ON ps.tenant_id = d.tenant_id AND ps.device_id = d.id
LEFT JOIN operations.device_patching_override op_patching
  ON op_patching.tenant_id = d.tenant_id AND op_patching.device_id = d.id
WHERE d.deleted_at IS NULL;
GRANT SELECT ON operations.v_device
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER VIEW operations.v_device OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0133_finding_type_device_exposure")
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(SEED_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(DETAIL_VIEW_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(DEVICE_READ_MODEL_SQL, migrations.RunSQL.noop),
    ]
