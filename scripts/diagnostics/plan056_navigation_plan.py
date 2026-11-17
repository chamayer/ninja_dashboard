"""One bounded actual-plan comparison of existing navigation reads."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import sys

logging.disable(logging.CRITICAL)
sys.path.insert(0,'/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod')
signal.alarm(45)
import django
django.setup()
from django.db import connection,transaction
from apps.core import issue_selection
from apps.core.models import Finding

spec=importlib.util.spec_from_file_location('apps.core._plan056_navigation_candidate',Path(__file__).with_name('plan056_navigation_candidate.py'))
candidate=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=candidate
spec.loader.exec_module(candidate)
try:
    with transaction.atomic(),connection.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute("SET LOCAL lock_timeout='1s'")
        captured=[]
        def capture(execute,sql,params,many,context):
            captured.append((sql,params))
            return execute(sql,params,many,context)
        with connection.execute_wrapper(capture):
            original=issue_selection.count(issue_selection.Scope(status='open'))
            patching=Finding.objects.filter(tenant_id=1,finding_type__issue_category='Patching & support',status__in=('open','acknowledged','investigating')).count()
        sql,params=candidate._filtered_sql(candidate.Scope(status='open_paused'),summary=True,home_compact=True,count_only=True)
        sql += "SELECT (SELECT count(*) FROM selected WHERE status='open'), (SELECT count(*) FROM items WHERE kind='finding' AND namespace='entity' AND issue_category='Patching & support')"
        cur.execute(sql,params)
        print(json.dumps({'counts_equal':tuple(cur.fetchone())==(original,patching)}),flush=True)
        for label,query,parameters in [('current_issues',*captured[0]),('candidate_combined',sql,params)]:
            cur.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+query,parameters)
            result=cur.fetchone()[0]
            if isinstance(result,str):
                result=json.loads(result)
            plan=result[0]
            nodes=[]
            stack=[plan['Plan']]
            while stack:
                node=stack.pop()
                children=node.get('Plans',[])
                total=node.get('Actual Total Time',0)*node.get('Actual Loops',1)
                own=total-sum(c.get('Actual Total Time',0)*c.get('Actual Loops',1) for c in children)
                nodes.append({**{k:node[k] for k in ('Node Type','Relation Name','Index Name','Actual Rows','Actual Loops','Heap Fetches','Shared Hit Blocks','Shared Read Blocks','Temp Read Blocks','Temp Written Blocks') if k in node},'inclusive_ms':round(total,3),'minus_child_ms':round(own,3)})
                stack.extend(children)
            nodes.sort(key=lambda n:n['minus_child_ms'],reverse=True)
            print(json.dumps({'reader':label,'execution_ms':plan.get('Execution Time'),'jit':plan.get('JIT'),'largest_nodes':nodes[:10]}),flush=True)
finally:
    connection.close()
