"""Restrict Ninja current shadow views to authoritative record contracts.

Legacy Ninja readers remain authoritative. The daily view intentionally keeps
inactive and earlier-projection records because historical rollups reference
the stable source record rather than the current projection contract.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

NINJA_SOURCE_INSTANCE_ID = "00000000-0000-4000-8000-000000000010"

_DETAIL_VIEW = r"""
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
        THEN ARRAY(
            SELECT jsonb_array_elements_text(
                c.canonical_data -> 'needs_reboot_reasons'
            )
        )
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
  {contract_filter};
"""

_HEALTH_VIEW = r"""
CREATE OR REPLACE VIEW operations.ninja_device_health_current_shadow
WITH (security_invoker = true) AS
SELECT
    c.observed_at AS snapshot_at,
    c.external_id::integer AS device_id,
    NULLIF(c.canonical_data ->> 'pending_reboot_reason', '') AS pending_reboot_reason,
    NULLIF(c.canonical_data ->> 'failed_os_patches_count', '')::integer
        AS failed_os_patches_count,
    NULLIF(c.canonical_data ->> 'pending_os_patches_count', '')::integer
        AS pending_os_patches_count,
    NULLIF(c.canonical_data ->> 'failed_software_patches_count', '')::integer
        AS failed_software_patches_count,
    NULLIF(c.canonical_data ->> 'pending_software_patches_count', '')::integer
        AS pending_software_patches_count,
    NULLIF(c.canonical_data ->> 'alert_count', '')::integer AS alert_count,
    NULLIF(c.canonical_data ->> 'active_job_count', '')::integer AS active_job_count,
    NULLIF(c.canonical_data ->> 'health_status', '') AS health_status,
    NULLIF(c.canonical_data ->> 'active_threats_count', '')::integer
        AS active_threats_count,
    NULLIF(c.canonical_data ->> 'quarantined_threats_count', '')::integer
        AS quarantined_threats_count,
    NULLIF(c.canonical_data ->> 'blocked_threats_count', '')::integer
        AS blocked_threats_count,
    NULLIF(c.canonical_data ->> 'critical_vulnerability_count', '')::integer
        AS critical_vulnerability_count,
    NULLIF(c.canonical_data ->> 'high_vulnerability_count', '')::integer
        AS high_vulnerability_count,
    NULLIF(c.canonical_data ->> 'medium_vulnerability_count', '')::integer
        AS medium_vulnerability_count,
    NULLIF(c.canonical_data ->> 'low_vulnerability_count', '')::integer
        AS low_vulnerability_count,
    NULLIF(c.canonical_data ->> 'installation_issues_count', '')::integer
        AS installation_issues_count,
    CASE lower(c.canonical_data ->> 'offline')
        WHEN 'true' THEN TRUE WHEN 'false' THEN FALSE ELSE NULL
    END AS offline,
    CASE lower(c.canonical_data ->> 'parent_offline')
        WHEN 'true' THEN TRUE WHEN 'false' THEN FALSE ELSE NULL
    END AS parent_offline,
    COALESCE(c.canonical_data -> 'products_installation_statuses', '{{}}'::jsonb)
        AS products_installation_statuses,
    c.raw_data AS data,
    c.raw_hash,
    c.material_hash,
    c.material_projection_version
FROM operations.entity_observation_current c
WHERE c.active IS TRUE
  AND lower(c.platform) = 'ninja'
  AND c.external_namespace = 'device-health'
  AND c.external_id ~ '^[0-9]+$'
  {contract_filter};
"""

_DAILY_VIEW = r"""
CREATE OR REPLACE VIEW operations.ninja_device_seen_daily_shadow
WITH (security_invoker = true) AS
SELECT
    r.rollup_day,
    c.external_id::integer AS device_id,
    r.source_record_id,
    r.first_snapshot_run_id,
    r.backfilled_from_legacy
FROM operations.source_record_seen_daily r
JOIN operations.entity_observation_current c
  ON c.tenant_id = r.tenant_id
 AND c.observation_id = r.source_record_id
 AND c.external_namespace = r.external_namespace
WHERE r.external_namespace = 'device'
  AND lower(c.platform) = 'ninja'
  AND c.external_id ~ '^[0-9]+$'
  {contract_filter};
"""

FORWARD_SQL = (
    _DETAIL_VIEW.format(
        contract_filter=(
            f"AND c.source_instance_id = '{NINJA_SOURCE_INSTANCE_ID}'::uuid\n"
            "  AND c.snapshot_scope = 'Ninja'\n"
            "  AND c.material_projection_version = 3"
        )
    )
    + _HEALTH_VIEW.format(
        contract_filter=(
            f"AND c.source_instance_id = '{NINJA_SOURCE_INSTANCE_ID}'::uuid\n"
            "  AND c.snapshot_scope = 'Ninja.device-health'\n"
            "  AND c.material_projection_version = 1"
        )
    )
    + _DAILY_VIEW.format(
        contract_filter=(f"AND c.source_instance_id = '{NINJA_SOURCE_INSTANCE_ID}'::uuid")
    )
)

REVERSE_SQL = (
    _DETAIL_VIEW.format(contract_filter="")
    + _HEALTH_VIEW.format(contract_filter="")
    + _DAILY_VIEW.format(contract_filter="")
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0098_exclude_health_from_device_presence"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
