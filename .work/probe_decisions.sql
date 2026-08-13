\pset pager off
SET operations.tenant_id = 1;

-- Which authorization tiers actually have rows, and were any written recently?
SELECT CASE
         WHEN client_id IS NULL AND device_id IS NULL THEN 'global'
         WHEN device_id IS NOT NULL                   THEN 'device'
         ELSE 'client'
       END AS tier,
       COUNT(*)          AS rows,
       MIN(decided_at)   AS earliest,
       MAX(decided_at)   AS latest
  FROM operations.software_decisions
 WHERE tenant_id = 1
 GROUP BY 1 ORDER BY rows DESC;
