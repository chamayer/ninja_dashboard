"""Cut Operations readers to generic Ninja evidence and compact Software state."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

NINJA_SOURCE_INSTANCE_ID = "00000000-0000-4000-8000-000000000010"

FORWARD_SQL = f"""
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
      AND o.material_projection_version = 3
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
ALTER MATERIALIZED VIEW operations.device_session_current
    OWNER TO operations_migrate;

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

CREATE MATERIALIZED VIEW operations.software_title_current AS
SELECT sic.tenant_id,
       sic.canonical_name,
       MAX(sic.publisher) AS publisher,
       COUNT(*)::integer AS installations,
       COUNT(DISTINCT sic.device_id)::integer AS device_count,
       COUNT(DISTINCT sic.client_id)::integer AS client_count,
       MIN(sic.first_observed_at) AS first_observed_at,
       MAX(sic.last_observed_at) AS last_observed_at,
       MAX(sic.first_observed_at) AS latest_install
FROM operations.software_installations_current sic
WHERE sic.deleted_at IS NULL AND sic.stale_since IS NULL
GROUP BY sic.tenant_id, sic.canonical_name
WITH DATA;
CREATE UNIQUE INDEX software_title_current_pk
    ON operations.software_title_current (tenant_id, canonical_name);
CREATE INDEX software_title_current_publisher_idx
    ON operations.software_title_current (tenant_id, LOWER(publisher));
GRANT SELECT ON operations.software_title_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.software_title_current
    OWNER TO operations_migrate;

DROP MATERIALIZED VIEW operations.v_software_safety;
CREATE MATERIALIZED VIEW operations.v_software_safety AS
WITH per_title_cves AS (
    SELECT cm.tenant_id, cm.canonical_name,
           COUNT(DISTINCT cm.cve_id) AS cve_count,
           COUNT(DISTINCT cm.cve_id) FILTER (WHERE c.kev_flag) AS kev_count,
           COUNT(DISTINCT cm.cve_id) FILTER (
             WHERE c.kev_flag OR c.last_modified_at > NOW() - INTERVAL '3 years'
           ) AS cve_count_recent,
           MAX(c.cvss_v3) FILTER (
             WHERE c.kev_flag OR c.last_modified_at > NOW() - INTERVAL '3 years'
           ) AS max_cvss_recent,
           MAX(c.cvss_v3) AS max_cvss,
           MAX(c.epss_score) FILTER (
             WHERE c.kev_flag OR c.last_modified_at > NOW() - INTERVAL '3 years'
           ) AS max_epss_recent,
           MAX(c.epss_score) AS max_epss
    FROM operations.cve_match cm
    LEFT JOIN intel.cves c ON c.cve_id = cm.cve_id
    GROUP BY cm.tenant_id, cm.canonical_name
), per_title_osint AS (
    SELECT tenant_id, canonical_name,
           COUNT(*) FILTER (WHERE signal_type = 'threat_hit') AS threat_hits
    FROM operations.safety_signal
    WHERE canonical_name <> ''
    GROUP BY tenant_id, canonical_name
), per_publisher_osint AS (
    SELECT tenant_id, LOWER(publisher) AS publisher_lc,
           COUNT(*) FILTER (WHERE signal_type = 'threat_hit') AS pub_threat_hits
    FROM operations.safety_signal
    WHERE publisher <> ''
    GROUP BY tenant_id, LOWER(publisher)
), title_decisions AS (
    SELECT tenant_id, LOWER(canonical_name) AS canonical_lc,
           BOOL_OR(decision IN ('approve','approve_publisher')) AS is_approved,
           BOOL_OR(decision = 'reject') AS is_rejected
    FROM operations.software_decisions
    WHERE canonical_name <> ''
    GROUP BY tenant_id, LOWER(canonical_name)
), publisher_decisions AS (
    SELECT tenant_id, LOWER(publisher) AS publisher_lc,
           BOOL_OR(decision IN ('approve','approve_publisher')) AS is_approved,
           BOOL_OR(decision = 'reject') AS is_rejected
    FROM operations.software_decisions
    WHERE publisher <> ''
    GROUP BY tenant_id, LOWER(publisher)
), publisher_alias_resolved AS (
    SELECT ft.tenant_id, ft.canonical_name,
           COALESCE(pa.canonical_publisher, ft.publisher) AS resolved_publisher
    FROM operations.software_title_current ft
    LEFT JOIN LATERAL (
        SELECT canonical_publisher
        FROM operations.publisher_aliases
        WHERE enabled AND ft.publisher IS NOT NULL
          AND ft.publisher ILIKE raw_pattern
        LIMIT 1
    ) pa ON TRUE
)
SELECT ft.tenant_id, ft.canonical_name, ft.publisher,
       par.resolved_publisher, ft.installations, ft.device_count,
       ft.client_count, COALESCE(cve.cve_count, 0) AS cve_count,
       COALESCE(cve.kev_count, 0) AS kev_count,
       COALESCE(cve.cve_count_recent, 0) AS cve_count_recent,
       cve.max_cvss, cve.max_cvss_recent, cve.max_epss,
       cve.max_epss_recent, COALESCE(osint.threat_hits, 0) AS osint_hits,
       COALESCE(pub_osint.pub_threat_hits, 0) AS publisher_osint_hits,
       COALESCE(td.is_approved, FALSE) AS title_approved,
       COALESCE(td.is_rejected, FALSE) AS title_rejected,
       COALESCE(pd.is_approved, FALSE) AS publisher_approved,
       COALESCE(pd.is_rejected, FALSE) AS publisher_rejected,
       LEAST(100, GREATEST(0,
            CASE WHEN COALESCE(cve.kev_count, 0) > 0 THEN 100 ELSE 0 END
          + COALESCE(cve.max_cvss_recent, cve.max_cvss, 0) * 10
          + COALESCE(cve.max_epss_recent, cve.max_epss, 0) * 40
          + LEAST(30, COALESCE(osint.threat_hits, 0) * 10
                    + COALESCE(pub_osint.pub_threat_hits, 0) * 5)
          + CASE WHEN COALESCE(td.is_rejected, FALSE) THEN 50 ELSE 0 END
          + CASE WHEN COALESCE(pd.is_rejected, FALSE) THEN 30 ELSE 0 END
          - CASE WHEN COALESCE(td.is_approved, FALSE) THEN 100 ELSE 0 END
          - CASE WHEN COALESCE(pd.is_approved, FALSE) THEN 100 ELSE 0 END
       ))::int AS safety_score,
       CASE
         WHEN COALESCE(td.is_approved, FALSE)
           OR COALESCE(pd.is_approved, FALSE) THEN 'clean'
         WHEN COALESCE(cve.kev_count, 0) > 0 THEN 'high'
         WHEN COALESCE(cve.max_cvss_recent, 0) >= 7.0 THEN 'high'
         WHEN COALESCE(cve.max_cvss_recent, 0) >= 4.0 THEN 'medium'
         WHEN COALESCE(osint.threat_hits, 0) >= 3 THEN 'medium'
         WHEN COALESCE(osint.threat_hits, 0) > 0
           OR COALESCE(pub_osint.pub_threat_hits, 0) > 0 THEN 'low'
         ELSE 'unknown'
       END AS safety_band
FROM operations.software_title_current ft
LEFT JOIN publisher_alias_resolved par
  ON par.tenant_id = ft.tenant_id
 AND par.canonical_name = ft.canonical_name
LEFT JOIN per_title_cves cve
  ON cve.tenant_id = ft.tenant_id AND cve.canonical_name = ft.canonical_name
LEFT JOIN per_title_osint osint
  ON osint.tenant_id = ft.tenant_id
 AND LOWER(osint.canonical_name) = LOWER(ft.canonical_name)
LEFT JOIN per_publisher_osint pub_osint
  ON pub_osint.tenant_id = ft.tenant_id
 AND pub_osint.publisher_lc = LOWER(COALESCE(par.resolved_publisher, ft.publisher, ''))
LEFT JOIN title_decisions td
  ON td.tenant_id = ft.tenant_id AND td.canonical_lc = LOWER(ft.canonical_name)
LEFT JOIN publisher_decisions pd
  ON pd.tenant_id = ft.tenant_id
 AND pd.publisher_lc = LOWER(COALESCE(par.resolved_publisher, ft.publisher, ''));
CREATE UNIQUE INDEX v_software_safety_pk
    ON operations.v_software_safety (tenant_id, canonical_name);
CREATE INDEX v_software_safety_band_idx
    ON operations.v_software_safety (tenant_id, safety_band);
CREATE INDEX v_software_safety_publisher_idx
    ON operations.v_software_safety (tenant_id, LOWER(resolved_publisher));
GRANT SELECT ON operations.v_software_safety
    TO operations_app, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.v_software_safety
    OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0099_ninja_shadow_scope_correction"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
