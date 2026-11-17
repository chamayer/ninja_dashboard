-- Each statement uses a fresh autocommit snapshot in one read-only connection.
WITH observed AS MATERIALIZED (
 SELECT pid,backend_start,leader_pid,backend_type,state,
        xact_start,query_start,wait_event_type,wait_event,query,
        CASE application_name WHEN 'operations' THEN 'operations'
             WHEN 'ingest' THEN 'ingest' ELSE 'other' END AS application
 FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
), selected AS MATERIALIZED (
 SELECT * FROM observed
 WHERE state='active' OR state LIKE 'idle in transaction%'
 ORDER BY query_start NULLS LAST,pid LIMIT 50
)
SELECT jsonb_build_object('section','activity','utc',clock_timestamp(),
 'active_or_idle_xact_total',(SELECT count(*) FROM observed
   WHERE state='active' OR state LIKE 'idle in transaction%'),
 'truncated',(SELECT count(*) FROM observed
   WHERE state='active' OR state LIKE 'idle in transaction%')>50,
 'sessions',(SELECT coalesce(jsonb_agg(jsonb_build_object(
   'pid',pid,'backend_start',backend_start,'leader_pid',leader_pid,
   'backend_type',backend_type,'application',application,'state',state,
   'query_age_s',extract(epoch FROM clock_timestamp()-query_start),
   'xact_age_s',extract(epoch FROM clock_timestamp()-xact_start),
   'wait_type',wait_event_type,'wait',wait_event,
   'blocker_pids',pg_blocking_pids(pid),
   'family',CASE
     WHEN query ILIKE '%v_hudu_computer_inventory_observation_current%' THEN 'coverage_hudu'
     WHEN query ILIKE '%entity_relationship_evidence_history%' THEN 'relationship_history'
     WHEN query ILIKE '%entity_relationship_evidence_current%' THEN 'relationship_current'
     WHEN query ILIKE '%software_device_readiness%' THEN 'software_readiness'
     WHEN query ILIKE '%cve_match%' THEN 'cve_match'
     WHEN query ILIKE '%device_requirement_state%' THEN 'requirements'
     WHEN query ILIKE '%refresh materialized view%' THEN 'materialized_refresh'
     WHEN query ILIKE '%v_entity_observation_admin_metadata%' THEN 'source_metadata'
     WHEN query ILIKE '%device_patching_scope_current%' THEN 'patch_scope'
     WHEN query ILIKE '%condition_assessments%' THEN 'assessments'
     WHEN query ILIKE '%finding_state%' OR query ILIKE '%operations.findings%' THEN 'findings'
     ELSE 'unclassified' END)), '[]') FROM selected));

SELECT jsonb_build_object('section','jobs','utc',clock_timestamp(),
 'truncated',(SELECT count(*) FROM operations.operator_job_runs
   WHERE tenant_id=1 AND status IN ('running','queued'))>50,
 'runs',(SELECT coalesce(jsonb_agg(to_jsonb(j)),'[]') FROM (
   SELECT md5(id::text) AS run_alias,
     CASE WHEN job_key IN ('source-refresh','resolver','platform-evaluate',
       'software-classify-only','software-classify-full','intel-matcher',
       'source-record-assess','computer-client-ownership',
       'computer-client-ownership-sweep') THEN job_key ELSE 'other' END AS family,
     status,started_at,heartbeat_at,md5(stage) AS stage_alias,stage_updated_at,
     extract(epoch FROM clock_timestamp()-started_at) AS elapsed_s
   FROM operations.operator_job_runs
   WHERE tenant_id=1 AND status IN ('running','queued')
   ORDER BY started_at NULLS LAST,id LIMIT 50) j));

SELECT jsonb_build_object('section','database','utc',clock_timestamp(),
 'counters',(SELECT to_jsonb(d) FROM (
   SELECT blks_read,blks_hit,temp_files,temp_bytes,tup_inserted,tup_updated,
          tup_deleted,deadlocks,blk_read_time,blk_write_time,stats_reset
   FROM pg_stat_database WHERE datname=current_database()) d));
