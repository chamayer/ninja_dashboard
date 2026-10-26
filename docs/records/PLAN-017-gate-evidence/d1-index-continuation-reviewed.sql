-- Reviewed targeted continuation authorized by user direction: do not skip; do it now.
SELECT n.nspname AS schema_name, tab.relname AS relation_name,
       idx.relname AS index_name, am.amname,
       i.indisprimary, i.indisunique, i.indisvalid, i.indisready,
       pg_catalog.pg_get_indexdef(idx.oid) AS index_definition
FROM pg_catalog.pg_index i
JOIN pg_catalog.pg_class tab ON tab.oid = i.indrelid
JOIN pg_catalog.pg_namespace n ON n.oid = tab.relnamespace
JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
JOIN pg_catalog.pg_am am ON am.oid = idx.relam
WHERE n.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
  AND n.nspname = 'operations'
  AND tab.relname = ANY(ARRAY['run_log','software_reclassification_targets'])
ORDER BY n.nspname, tab.relname, idx.relname
LIMIT 1000;
