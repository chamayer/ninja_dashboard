"""Expand generic observations for Ninja snapshot dual-write.

This migration is additive. Legacy Ninja snapshot tables and readers remain
authoritative until the separately approved read/write cutover.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
ALTER TABLE operations.entity_observation_current
    ADD CONSTRAINT uq_obs_current_tenant_record_namespace
    UNIQUE (tenant_id, observation_id, external_namespace);

ALTER TABLE operations.observation_snapshot_runs
    ADD CONSTRAINT uq_obs_snapshot_tenant_run
    UNIQUE (tenant_id, run_id);

CREATE TABLE operations.source_record_seen_daily (
    tenant_id                 bigint NOT NULL
        REFERENCES operations.tenants(id) ON DELETE RESTRICT,
    source_record_id          uuid NOT NULL,
    external_namespace       varchar(120) NOT NULL,
    rollup_day                date NOT NULL,
    first_snapshot_run_id     uuid,
    backfilled_from_legacy    boolean NOT NULL DEFAULT FALSE,
    PRIMARY KEY (tenant_id, source_record_id, rollup_day),
    CONSTRAINT ck_seen_daily_provenance
        CHECK (
            (backfilled_from_legacy IS FALSE AND first_snapshot_run_id IS NOT NULL)
            OR
            (backfilled_from_legacy IS TRUE AND first_snapshot_run_id IS NULL)
        ),
    CONSTRAINT fk_seen_daily_source_record
        FOREIGN KEY (tenant_id, source_record_id, external_namespace)
        REFERENCES operations.entity_observation_current
            (tenant_id, observation_id, external_namespace)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_seen_daily_snapshot_run
        FOREIGN KEY (tenant_id, first_snapshot_run_id)
        REFERENCES operations.observation_snapshot_runs (tenant_id, run_id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX idx_seen_daily_day_brin
    ON operations.source_record_seen_daily USING BRIN (rollup_day)
    WITH (pages_per_range = 32);

ALTER TABLE operations.source_record_seen_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.source_record_seen_daily FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.source_record_seen_daily
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);

GRANT SELECT ON operations.source_record_seen_daily
    TO operations_app, operations_readonly;
GRANT SELECT, INSERT ON operations.source_record_seen_daily TO ninja_ingest;
ALTER TABLE operations.source_record_seen_daily OWNER TO operations_migrate;

CREATE VIEW operations.ninja_device_detail_current_shadow
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
  AND c.external_id ~ '^[0-9]+$';

CREATE VIEW operations.ninja_device_health_current_shadow
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
    COALESCE(c.canonical_data -> 'products_installation_statuses', '{}'::jsonb)
        AS products_installation_statuses,
    c.raw_data AS data,
    c.raw_hash,
    c.material_hash,
    c.material_projection_version
FROM operations.entity_observation_current c
WHERE c.active IS TRUE
  AND lower(c.platform) = 'ninja'
  AND c.external_namespace = 'device-health'
  AND c.external_id ~ '^[0-9]+$';

CREATE VIEW operations.ninja_device_seen_daily_shadow
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
  AND c.external_id ~ '^[0-9]+$';

GRANT SELECT ON operations.ninja_device_detail_current_shadow,
                operations.ninja_device_health_current_shadow,
                operations.ninja_device_seen_daily_shadow
    TO operations_app, operations_readonly, ninja_ingest;
"""


REVERSE_SQL = r"""
DROP VIEW IF EXISTS operations.ninja_device_seen_daily_shadow;
DROP VIEW IF EXISTS operations.ninja_device_health_current_shadow;
DROP VIEW IF EXISTS operations.ninja_device_detail_current_shadow;
DROP TABLE IF EXISTS operations.source_record_seen_daily;
ALTER TABLE operations.observation_snapshot_runs
    DROP CONSTRAINT IF EXISTS uq_obs_snapshot_tenant_run;
ALTER TABLE operations.entity_observation_current
    DROP CONSTRAINT IF EXISTS uq_obs_current_tenant_record_namespace;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0096_stable_observation_identity_cutover"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="entityobservationcurrent",
            name="material_projection_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="entityobservationhistory",
            name="material_projection_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
