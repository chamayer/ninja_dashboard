"""Rebuild active presence readers on the ADR-0007 current observation store.

The legacy ``entity_observations`` relation is intentionally retained as an
empty compatibility shell, but ``device_agent_presence_current`` still read
from it.  That made every presence refresh silently produce no rows.

The presence matview has two PostgreSQL OID dependents: device session and
current source health. `v_device` in turn depends on device session. Rebuild
those current derived objects in the same transaction so they bind to the
replacement presence matview. The existing ``source_health_current_legacy``
safety-net view remains bound to the renamed legacy presence matview for
rollback comparison.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

DROP_CURRENT_DEPENDENTS_SQL = """
DROP VIEW operations.v_device;
DROP MATERIALIZED VIEW operations.source_health_current;
DROP MATERIALIZED VIEW operations.device_session_current;
"""

RENAME_LEGACY_PRESENCE_SQL = """
ALTER MATERIALIZED VIEW operations.device_agent_presence_current
    RENAME TO device_agent_presence_current_legacy;
ALTER INDEX operations.idx_device_agent_presence_current_pk
    RENAME TO idx_device_agent_presence_current_legacy_pk;
ALTER INDEX operations.idx_device_agent_presence_current_client
    RENAME TO idx_device_agent_presence_current_legacy_client;
"""

CREATE_CURRENT_PRESENCE_SQL = """
CREATE MATERIALIZED VIEW operations.device_agent_presence_current AS
SELECT
    o.tenant_id,
    d.client_id,
    o.device_id,
    d.device_type,
    o.entity_type,
    o.platform,
    o.subplatform,
    MAX(o.observed_at) AS last_observed_at,
    MIN(o.observed_at) AS first_observed_at,
    MAX((o.canonical_data ->> 'last_seen_at')::timestamptz) AS last_contact_at,
    (ARRAY_AGG(o.canonical_data ->> 'power_state' ORDER BY o.observed_at DESC))[1]
        AS last_power_state,
    COUNT(*) AS observation_count
FROM operations.entity_observation_current o
JOIN operations.devices d
  ON d.id = o.device_id
 AND d.deleted_at IS NULL
WHERE o.active
  AND o.device_id IS NOT NULL
  AND o.entity_type <> 'software'
GROUP BY
    o.tenant_id, d.client_id, o.device_id, d.device_type,
    o.entity_type, o.platform, o.subplatform
WITH DATA;

CREATE UNIQUE INDEX idx_device_agent_presence_current_pk
    ON operations.device_agent_presence_current
       (tenant_id, device_id, entity_type, platform);
CREATE INDEX idx_device_agent_presence_current_client
    ON operations.device_agent_presence_current
       (tenant_id, client_id, platform, device_type);
GRANT SELECT ON operations.device_agent_presence_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.device_agent_presence_current
    OWNER TO operations_migrate;
"""

CREATE_CURRENT_SESSION_SQL = """
CREATE MATERIALIZED VIEW operations.device_session_current AS
WITH source_online AS (
    SELECT
        apc.device_id,
        apc.platform,
        apc.entity_type,
        apc.last_observed_at,
        apc.last_contact_at,
        apc.last_power_state,
        (
            (apc.entity_type LIKE 'agent.%'
             AND COALESCE(apc.last_contact_at, apc.last_observed_at)
                 > NOW() - INTERVAL '24 hours')
            OR
            (apc.entity_type IN ('vm.guest', 'vm.host')
             AND apc.last_power_state = 'poweredon')
        ) AS is_online_now
    FROM operations.device_agent_presence_current apc
),
per_device_presence AS (
    SELECT
        so.device_id,
        MAX(so.last_contact_at) AS last_contact_at,
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
),
latest_ninja_snapshot AS (
    SELECT DISTINCT ON (ns.device_id)
        ns.device_id AS ninja_device_id,
        ns.needs_reboot,
        ns.last_boot,
        ns.snapshot_at
    FROM ninja_core.device_snapshots ns
    ORDER BY ns.device_id, ns.snapshot_at DESC
),
device_reboot AS (
    SELECT DISTINCT ON (dl.device_id)
        dl.device_id AS ops_device_id,
        lns.needs_reboot,
        lns.last_boot
    FROM operations.device_links dl
    JOIN operations.sources s
      ON s.id = dl.source_id AND s.name = 'Ninja'
    JOIN latest_ninja_snapshot lns
      ON lns.ninja_device_id = dl.external_id::int
    ORDER BY dl.device_id, lns.snapshot_at DESC
)
SELECT
    d.tenant_id,
    d.client_id,
    d.id AS device_id,
    p.last_contact_at,
    p.last_observed_at,
    COALESCE(p.is_online_any, FALSE) AS is_online_any,
    COALESCE(p.online_sources, ARRAY[]::text[]) AS online_sources,
    COALESCE(p.source_count_active, 0) AS source_count_active,
    ls.needs_reboot,
    ls.last_boot AS last_boot_at,
    p.last_power_state,
    NOW() AS computed_at
FROM operations.devices d
LEFT JOIN per_device_presence p ON p.device_id = d.id
LEFT JOIN device_reboot ls ON ls.ops_device_id = d.id
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
"""

CREATE_CURRENT_V_DEVICE_SQL = """
CREATE VIEW operations.v_device
WITH (security_invoker = true) AS
SELECT
    d.tenant_id,
    d.id AS device_id,
    d.client_id,
    d.version,
    d.canonical_hostname,
    d.canonical_serial,
    d.canonical_vm_uuid,
    d.device_type,
    d.device_role,
    d.lifecycle_status,
    d.os_name,
    d.os_family,
    d.os_group,
    d.created_at,
    d.created_reason,
    d.updated_at,
    d.updated_reason,
    d.stale_since,
    d.stale_reason,
    d.deleted_at,
    d.deleted_reason,
    ds.last_contact_at,
    ds.last_observed_at,
    COALESCE(ds.is_online_any, FALSE) AS is_online_any,
    COALESCE(ds.online_sources, ARRAY[]::text[]) AS online_sources,
    COALESCE(ds.source_count_active, 0) AS source_count_active,
    ds.needs_reboot,
    ds.last_boot_at,
    ds.last_power_state,
    ds.computed_at AS session_computed_at,
    COALESCE(op_exemptions.value, '{}'::jsonb) AS exemptions,
    ps.scope_derived AS patching_scope_derived,
    ps.scope_reason AS patching_scope_reason,
    ps.computed_at AS patching_scope_computed_at,
    op_patching.scope AS patching_scope_override,
    op_patching.reason AS patching_scope_override_reason,
    COALESCE(op_patching.scope, ps.scope_derived, 'Unmanaged')
        AS effective_patching_scope
FROM operations.devices d
LEFT JOIN operations.device_session_current ds
       ON ds.tenant_id = d.tenant_id
      AND ds.device_id = d.id
LEFT JOIN operations.device_operator_decisions op_exemptions
       ON op_exemptions.tenant_id = d.tenant_id
      AND op_exemptions.device_id = d.id
      AND op_exemptions.dimension = 'exemptions'
LEFT JOIN operations.device_patching_scope_current ps
       ON ps.tenant_id = d.tenant_id
      AND ps.device_id = d.id
LEFT JOIN operations.device_patching_override op_patching
       ON op_patching.tenant_id = d.tenant_id
      AND op_patching.device_id = d.id
WHERE d.deleted_at IS NULL;

GRANT SELECT ON operations.v_device
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER VIEW operations.v_device OWNER TO operations_migrate;
"""

CREATE_CURRENT_SOURCE_HEALTH_SQL = """
CREATE MATERIALIZED VIEW operations.source_health_current AS
WITH observation_rollup AS (
    SELECT tenant_id, platform,
           MAX(observed_at) AS last_observed_at,
           MAX(observed_at) FILTER (WHERE entity_type LIKE 'agent.%')
             AS last_agent_observed_at
      FROM operations.entity_observation_current
     WHERE active
     GROUP BY tenant_id, platform
), latest_run AS (
    SELECT DISTINCT ON (tenant_id, split_part(kind, '.', 2))
           tenant_id, split_part(kind, '.', 2) AS platform, ok AS last_run_ok,
           ended_at AS last_run_ended_at, rows AS last_run_rows, error AS last_run_error
      FROM operations.run_log WHERE kind LIKE 'source.%'
       AND split_part(kind, '.', 2) <> ''
     ORDER BY tenant_id, split_part(kind, '.', 2), started_at DESC
), latest_success AS (
    SELECT DISTINCT ON (tenant_id, split_part(kind, '.', 2))
           tenant_id, split_part(kind, '.', 2) AS platform,
           ended_at AS last_success_at, rows AS last_success_rows
      FROM operations.run_log WHERE kind LIKE 'source.%' AND ok
       AND split_part(kind, '.', 2) <> ''
     ORDER BY tenant_id, split_part(kind, '.', 2), started_at DESC
), agent_reach AS (
    SELECT tenant_id, platform, COUNT(DISTINCT client_id)::int AS client_count,
           COUNT(DISTINCT device_id)::int AS device_count
      FROM operations.device_agent_presence_current
     GROUP BY tenant_id, platform
), platforms AS (
    SELECT tenant_id, platform FROM observation_rollup
    UNION SELECT tenant_id, platform FROM latest_run
    UNION SELECT tenant_id, platform FROM agent_reach
)
SELECT p.tenant_id, p.platform, o.last_observed_at, o.last_agent_observed_at,
       r.last_run_ok, r.last_run_ended_at, r.last_run_rows, r.last_run_error,
       s.last_success_at, s.last_success_rows,
       COALESCE(a.client_count, 0) AS client_count,
       COALESCE(a.device_count, 0) AS device_count, NOW() AS computed_at
  FROM platforms p
  LEFT JOIN observation_rollup o USING (tenant_id, platform)
  LEFT JOIN latest_run r USING (tenant_id, platform)
  LEFT JOIN latest_success s USING (tenant_id, platform)
  LEFT JOIN agent_reach a USING (tenant_id, platform)
WITH DATA;

CREATE UNIQUE INDEX idx_source_health_current_pk
    ON operations.source_health_current (tenant_id, platform);
GRANT SELECT ON operations.source_health_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.source_health_current OWNER TO operations_migrate;
"""

DROP_REPLACEMENT_SQL = """
DROP VIEW operations.v_device;
DROP MATERIALIZED VIEW operations.source_health_current;
DROP MATERIALIZED VIEW operations.device_session_current;
DROP MATERIALIZED VIEW operations.device_agent_presence_current;
"""

RESTORE_LEGACY_PRESENCE_SQL = """
ALTER INDEX operations.idx_device_agent_presence_current_legacy_client
    RENAME TO idx_device_agent_presence_current_client;
ALTER INDEX operations.idx_device_agent_presence_current_legacy_pk
    RENAME TO idx_device_agent_presence_current_pk;
ALTER MATERIALIZED VIEW operations.device_agent_presence_current_legacy
    RENAME TO device_agent_presence_current;
"""

RESTORE_SOURCE_HEALTH_SQL = """
ALTER MATERIALIZED VIEW operations.source_health_current_legacy
    RENAME TO source_health_current;
ALTER INDEX operations.idx_source_health_current_legacy_pk
    RENAME TO idx_source_health_current_pk;
"""

FORWARD_SQL = (
    DROP_CURRENT_DEPENDENTS_SQL
    + RENAME_LEGACY_PRESENCE_SQL
    + CREATE_CURRENT_PRESENCE_SQL
    + CREATE_CURRENT_SESSION_SQL
    + CREATE_CURRENT_V_DEVICE_SQL
    + CREATE_CURRENT_SOURCE_HEALTH_SQL
)

REVERSE_SQL = (
    DROP_REPLACEMENT_SQL
    + RESTORE_LEGACY_PRESENCE_SQL
    + CREATE_CURRENT_SESSION_SQL
    + CREATE_CURRENT_V_DEVICE_SQL
    + RESTORE_SOURCE_HEALTH_SQL
)


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("operations", "0075_alter_coveragerequirement_options_and_more"),
    ]

    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
