"""Migration 0061 — shared source-health derived state.

`source_health_current` serves the Dashboard and Sources page with one row per
tenant/platform. It keeps operational current state separate from the raw,
auditable observations and avoids repeatedly aggregating the observation
history during page renders.
"""

from __future__ import annotations

from django.db import migrations


_VIEW_SQL = """
CREATE MATERIALIZED VIEW operations.source_health_current AS
WITH observation_rollup AS (
    SELECT
        tenant_id,
        platform,
        MAX(observed_at) AS last_observed_at,
        MAX(observed_at) FILTER (
            WHERE entity_type LIKE 'agent.%'
        ) AS last_agent_observed_at
    FROM operations.entity_observations
    GROUP BY tenant_id, platform
),
latest_run AS (
    SELECT DISTINCT ON (tenant_id, split_part(kind, '.', 2))
        tenant_id,
        split_part(kind, '.', 2) AS platform,
        ok AS last_run_ok,
        ended_at AS last_run_ended_at,
        rows AS last_run_rows,
        error AS last_run_error
    FROM operations.run_log
    WHERE kind LIKE 'source.%'
      AND split_part(kind, '.', 2) <> ''
    ORDER BY tenant_id, split_part(kind, '.', 2), started_at DESC
),
latest_success AS (
    SELECT DISTINCT ON (tenant_id, split_part(kind, '.', 2))
        tenant_id,
        split_part(kind, '.', 2) AS platform,
        ended_at AS last_success_at,
        rows AS last_success_rows
    FROM operations.run_log
    WHERE kind LIKE 'source.%'
      AND ok
      AND split_part(kind, '.', 2) <> ''
    ORDER BY tenant_id, split_part(kind, '.', 2), started_at DESC
),
agent_reach AS (
    SELECT
        tenant_id,
        platform,
        COUNT(DISTINCT client_id)::int AS client_count,
        COUNT(DISTINCT device_id)::int AS device_count
    FROM operations.device_agent_presence_current
    GROUP BY tenant_id, platform
),
platforms AS (
    SELECT tenant_id, platform FROM observation_rollup
    UNION
    SELECT tenant_id, platform FROM latest_run
    UNION
    SELECT tenant_id, platform FROM agent_reach
)
SELECT
    p.tenant_id,
    p.platform,
    o.last_observed_at,
    o.last_agent_observed_at,
    r.last_run_ok,
    r.last_run_ended_at,
    r.last_run_rows,
    r.last_run_error,
    s.last_success_at,
    s.last_success_rows,
    COALESCE(a.client_count, 0) AS client_count,
    COALESCE(a.device_count, 0) AS device_count,
    NOW() AS computed_at
FROM platforms p
LEFT JOIN observation_rollup o
       ON o.tenant_id = p.tenant_id AND o.platform = p.platform
LEFT JOIN latest_run r
       ON r.tenant_id = p.tenant_id AND r.platform = p.platform
LEFT JOIN latest_success s
       ON s.tenant_id = p.tenant_id AND s.platform = p.platform
LEFT JOIN agent_reach a
       ON a.tenant_id = p.tenant_id AND a.platform = p.platform
WITH DATA;

CREATE UNIQUE INDEX idx_source_health_current_pk
    ON operations.source_health_current (tenant_id, platform);

GRANT SELECT ON operations.source_health_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.source_health_current OWNER TO operations_migrate;

CREATE OR REPLACE FUNCTION operations.refresh_source_health_current()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.source_health_current;
END;
$$;

GRANT EXECUTE ON FUNCTION operations.refresh_source_health_current()
    TO operations_app, ninja_ingest;

CREATE OR REPLACE FUNCTION operations.refresh_derived()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM operations.refresh_device_agent_presence_current();
    PERFORM operations.refresh_device_session_current();
    PERFORM operations.refresh_patching_scope_current();
    PERFORM operations.refresh_client_health_trend_current();
    PERFORM operations.refresh_source_health_current();
END;
$$;
"""


_REVERSE_SQL = """
CREATE OR REPLACE FUNCTION operations.refresh_derived()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM operations.refresh_device_agent_presence_current();
    PERFORM operations.refresh_device_session_current();
    PERFORM operations.refresh_patching_scope_current();
    PERFORM operations.refresh_client_health_trend_current();
END;
$$;

DROP FUNCTION IF EXISTS operations.refresh_source_health_current();
DROP MATERIALIZED VIEW IF EXISTS operations.source_health_current;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0060_backfill_missing_device_links"),
    ]

    operations = [
        migrations.RunSQL(_VIEW_SQL, reverse_sql=_REVERSE_SQL),
    ]
