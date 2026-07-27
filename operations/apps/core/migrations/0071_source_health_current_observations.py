from __future__ import annotations

from typing import ClassVar

from django.db import migrations

RENAME_LEGACY_SQL = """
ALTER MATERIALIZED VIEW IF EXISTS operations.source_health_current
    RENAME TO source_health_current_legacy;
ALTER INDEX IF EXISTS operations.idx_source_health_current_pk
    RENAME TO idx_source_health_current_legacy_pk;
"""

RESTORE_LEGACY_SQL = """
ALTER MATERIALIZED VIEW IF EXISTS operations.source_health_current_legacy
    RENAME TO source_health_current;
ALTER INDEX IF EXISTS operations.idx_source_health_current_legacy_pk
    RENAME TO idx_source_health_current_pk;
"""

CREATE_CURRENT_SQL = """
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

DROP_CURRENT_SQL = """
DROP MATERIALIZED VIEW IF EXISTS operations.source_health_current;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [("operations", "0070_identity_candidate_current_reference")]
    operations: ClassVar = [
        migrations.RunSQL(
            RENAME_LEGACY_SQL,
            RESTORE_LEGACY_SQL,
        ),
        migrations.RunSQL(
            CREATE_CURRENT_SQL,
            DROP_CURRENT_SQL,
        ),
    ]
