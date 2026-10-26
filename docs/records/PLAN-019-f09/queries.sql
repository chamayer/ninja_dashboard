-- F1: catalog sizes and planner row estimates; metadata only.
SELECT c.relname, c.reltuples::bigint AS est_rows,
       pg_catalog.pg_table_size(c.oid) AS table_bytes,
       pg_catalog.pg_indexes_size(c.oid) AS index_bytes,
       pg_catalog.pg_total_relation_size(c.oid) AS total_bytes
  FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'operations'
   AND c.relname IN ('source_record_seen_daily', 'entity_observation_current',
                     'entity_observation_history')
 ORDER BY c.relname;
-- F2: presence rows per day for the last 14 days, by source platform and entity type.
SELECT d.rollup_day, c.platform, c.entity_type, count(*) AS presence_rows
  FROM operations.source_record_seen_daily d
  JOIN operations.entity_observation_current c
    ON c.tenant_id = d.tenant_id AND c.observation_id = d.source_record_id
 WHERE d.tenant_id = 1
   AND d.rollup_day >= current_date - 14
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3;
-- F3: current source records by platform and entity type: total, active, seen in 1 and 7 days.
SELECT c.platform, c.entity_type, count(*) AS records,
       count(*) FILTER (WHERE c.active) AS active_records,
       count(*) FILTER (WHERE c.last_seen_at > now() - interval '1 day') AS seen_1d,
       count(*) FILTER (WHERE c.last_seen_at > now() - interval '7 days') AS seen_7d
  FROM operations.entity_observation_current c
 WHERE c.tenant_id = 1
 GROUP BY 1, 2
 ORDER BY 1, 2;
-- F4: presence history bounds and backfill share; bounded by the BRIN-free full scan, so planned first.
SELECT min(rollup_day) AS first_day, max(rollup_day) AS last_day,
       count(*) AS rows, count(*) FILTER (WHERE backfilled_from_legacy) AS backfilled_rows
  FROM operations.source_record_seen_daily
 WHERE tenant_id = 1;
-- F5: Ninja daily presence collapsed into continuous stretches, strict and with gap tolerance.
WITH d AS (
    SELECT source_record_id,
           rollup_day - lag(rollup_day) OVER (PARTITION BY source_record_id ORDER BY rollup_day) AS gap
      FROM operations.source_record_seen_daily
     WHERE tenant_id = 1
)
SELECT count(DISTINCT source_record_id) AS records, count(*) AS day_rows,
       count(*) FILTER (WHERE gap IS NULL OR gap > 1) AS episodes_strict,
       count(*) FILTER (WHERE gap IS NULL OR gap > 3) AS episodes_gap_3d,
       count(*) FILTER (WHERE gap IS NULL OR gap > 7) AS episodes_gap_7d
  FROM d;
-- F6: calendar days with any presence row, and the days missing from the range.
SELECT count(DISTINCT rollup_day) AS days_with_rows,
       (max(rollup_day) - min(rollup_day) + 1) AS days_in_range
  FROM operations.source_record_seen_daily
 WHERE tenant_id = 1;
