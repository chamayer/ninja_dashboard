"""Bounded Software publication state; no payloads or credentials emitted."""
import json
import logging
import signal
import sys

logging.disable(logging.CRITICAL)
sys.path.insert(0, "/app")
signal.alarm(25)

from ingest import db
from ingest.config import settings

db.init(settings.postgres_dsn, min_size=1, max_size=1)
try:
    with db.transaction() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute("SELECT operations.software_overview_inputs(1)")
        inputs = cur.fetchone()[0]
        print(json.dumps({"ownership_pending": inputs.get("ownership_pending"), "classification_pending": inputs.get("classification_pending"), "active_inputs": len(inputs.get("active", [])), "owners_ready": {k:v.get("ready") for k,v in inputs.get("owners", {}).items()}}), flush=True)
        cur.execute("SELECT count(*),bool_or(contract_ready) FROM operations.software_overview_current WHERE tenant_id=1")
        print(json.dumps({"publication_state": cur.fetchone()}), flush=True)
        cur.execute("SELECT job_key,status,wait_category,count(*) FROM operations.operator_job_runs WHERE tenant_id=1 AND status IN ('running','queued') AND job_key IN ('software-overview','computer-client-ownership','computer-client-ownership-sweep','software-classify','software-classify-only','software-classify-full') GROUP BY 1,2,3")
        print(json.dumps({"jobs": cur.fetchall()}), flush=True)
        cur.execute("SELECT count(*) FROM operations.software_reclassification_targets WHERE tenant_id=1 AND consumed_at IS NULL")
        print(json.dumps({"pending_targets":cur.fetchone()[0]}),flush=True)
        cur.execute("SELECT state,wait_event_type,wait_event,cardinality(pg_blocking_pids(pid)),round(extract(epoch FROM clock_timestamp()-query_start)), CASE WHEN query ILIKE '%%begin_software_overview%%' THEN 'overview_begin' WHEN query ILIKE '%%publish_software_overview%%' THEN 'overview_publish' WHEN query ILIKE '%%pg_advisory%%' THEN 'advisory_lock' ELSE 'other' END FROM pg_stat_activity WHERE datname=current_database() AND state='active' AND pid<>pg_backend_pid()")
        print(json.dumps({"activity":cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT pid,state,wait_event,pg_blocking_pids(pid),round(extract(epoch FROM clock_timestamp()-query_start)), ARRAY(SELECT DISTINCT m[1] FROM regexp_matches(query,'operations[.][a-z_]+','g') m LIMIT 8) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND (state='active' OR pid IN (SELECT unnest(pg_blocking_pids(pid)) FROM pg_stat_activity))")
        print(json.dumps({"lock_chain":cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT job_key,id,status FROM operations.operator_job_runs WHERE tenant_id=1 AND status='running'")
        print(json.dumps({"running_jobs":cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT count(*),count(*) FILTER (WHERE device.deleted_at IS NULL AND device.id IS NOT NULL) FROM operations.computer_client_ownership owner LEFT JOIN operations.devices device ON device.tenant_id=owner.tenant_id AND device.id=owner.device_id WHERE owner.tenant_id=1 AND owner.state='dirty'")
        print(json.dumps({"dirty_total_and_reconcilable":cur.fetchone()}),flush=True)
        cur.execute("SELECT pid,state,wait_event_type,wait_event,round(extract(epoch FROM clock_timestamp()-query_start)),ARRAY(SELECT DISTINCT m[1] FROM regexp_matches(query,'operations[.][a-z_]+','g') m LIMIT 4) FROM pg_stat_activity WHERE datname=current_database() AND application_name='ingest' AND pid<>pg_backend_pid()")
        print(json.dumps({"ingest_connections":cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT job_key,stage,round(extract(epoch FROM clock_timestamp()-started_at)) FROM operations.operator_job_runs WHERE tenant_id=1 AND status='running'")
        print(json.dumps({"running_stages":cur.fetchall()},default=str),flush=True)
        cur.execute("SELECT status,terminal_reason,error FROM operations.operator_job_runs WHERE tenant_id=1 AND id='b45e48a4-4b12-4dbb-87ef-b74ed54b852d'")
        row = cur.fetchone()
        import re
        failure = row[2] or ''
        classes = re.findall(r'\b(?:[A-Z][A-Za-z]*(?:Error|Exception|Detected|Violation|Timeout)|deadlock detected|canceling statement due to[^\n]*|connection pool exhausted|connection timeout|statement timeout|permission denied)\b',failure)
        safe_prefix = re.sub(r"'[^']*'|\"[^\"]*\"", '[quoted]',failure.splitlines()[0] if failure else '')
        safe_prefix = re.sub(r'\b[0-9a-f]{8}-[0-9a-f-]{27,}\b','[id]',safe_prefix)
        # Only emit messages composed of known operational words; otherwise
        # disclose status/classification only, never arbitrary error text.
        allowed = re.fullmatch(r'[A-Za-z _.:;(),\[\]0-9-]*',safe_prefix) and not re.search(r'@|https?://',safe_prefix)
        print(json.dumps({"platform_terminal":{"status":row[0],"reason":row[1],"error_classes":classes,"error_prefix":safe_prefix[:220] if allowed else 'withheld'}}),flush=True)
        cur.execute("SELECT id,status,terminal_reason,requested_at,started_at,completed_at FROM operations.operator_job_runs WHERE tenant_id=1 AND id=%s",(inputs['owners']['platform-evaluate']['run_id'],))
        print(json.dumps({"selected_platform_checkpoint":cur.fetchone()},default=str),flush=True)
        cur.execute("SELECT input_watermarks FROM operations.software_overview_current WHERE tenant_id=1")
        publication=cur.fetchone()
        if publication:
            old=publication[0]['owners']
            print(json.dumps({'changed_owner_keys':[k for k in old if old[k]!=inputs['owners'].get(k)]}),flush=True)
finally:
    db.pool.close()
