\pset pager off
SET operations.tenant_id = 1;

-- Does collapsing keep client scope? Compare title-only vs (client,title).
SELECT ft.name AS finding_type,
       COUNT(*) AS open_rows,
       COUNT(DISTINCT lower(f.finding_details->>'canonical_name')) AS by_title,
       COUNT(DISTINCT (f.client_id::text || '|' ||
             lower(f.finding_details->>'canonical_name'))) AS by_client_title
  FROM operations.findings f
  JOIN operations.finding_types ft ON ft.id = f.finding_type_id
 WHERE ft.source_module = 'platform.software_findings'
   AND f.tenant_id = 1 AND f.status IN ('open','acknowledged')
 GROUP BY ft.name ORDER BY open_rows DESC;

-- Are software approval decisions per-client or global?
SELECT table_name, column_name
  FROM information_schema.columns
 WHERE table_schema = 'operations'
   AND table_name LIKE '%software%decision%'
 ORDER BY table_name, ordinal_position;
