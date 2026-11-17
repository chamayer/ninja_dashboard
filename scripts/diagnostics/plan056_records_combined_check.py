"""Compare actual reviewed candidate code in an isolated read-only process."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
from unittest.mock import patch

def load_source(name, filename):
    spec=importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0,"/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings.prod")
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.cache import caches
    from django.core.cache.backends.locmem import LocMemCache
    from django.db import connection,transaction
    from django.test import RequestFactory
    from django.urls import resolve
    from apps.core import views,context_processors
    domain=load_source("apps.core._plan056_domain", "plan056_records_domain_candidate.py")
    issues=load_source("apps.core._plan056_issues", "plan056_records_issues_candidate.py")
    context_candidate=load_source("apps.core._plan056_context", "plan056_records_context_candidate.py")
    context_candidate.issue_selection=issues
    proposed=load_source("apps.core._plan056_views", "plan056_records_views_candidate.py")
    proposed.source_record_summary=domain
    cache=caches['default']
    if not isinstance(cache,LocMemCache):
        raise RuntimeError("Only isolated local cache clearing is permitted")
    results=[]
    original_nav=context_processors._nav_issues_count
    original_patch=context_processors._nav_patching_count
    try:
        with transaction.atomic(),connection.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL operations.tenant_id='1'")
            cur.execute("SET LOCAL statement_timeout='15s'")
            cur.execute("SET LOCAL lock_timeout='1s'")
            cur.execute("SHOW jit")
            print(json.dumps({'database_jit_policy_unchanged':cur.fetchone()[0]}),flush=True)
            actor=get_user_model().objects.filter(is_active=True,is_superuser=True).values_list('pk',flat=True).first()
            if actor is None:
                raise RuntimeError("No active administrator")
            native_issues=context_processors.issue_selection
            for label,module,selector in (("current",views,native_issues),("combined_navigation",proposed,issues)):
                cache.clear()
                calls=[]
                contexts=[]
                nav={}
                render=module.render
                def capture(request,template,context,*args,**kwargs):
                    contexts.append(context.copy())
                    return render(request,template,context,*args,**kwargs)
                def count_nav(tenant):
                    nav['issues']=(context_candidate._nav_issues_count(tenant) if label == 'combined_navigation' else original_nav(tenant))
                    return nav['issues']
                def count_patch(tenant):
                    nav['patching']=original_patch(tenant)
                    return nav['patching']
                def trace(execute,sql,params,many,context):
                    frame=sys._getframe(1)
                    location='framework'
                    while frame:
                        file=frame.f_code.co_filename
                        if '/apps/core/' in file or 'plan056_records_' in Path(file).name:
                            location=Path(file).name+':'+frame.f_code.co_name
                            break
                        frame=frame.f_back
                    started=time.monotonic()
                    try:
                        return execute(sql,params,many,context)
                    finally:
                        calls.append({'location':location,'seconds':round(time.monotonic()-started,4)})
                request=RequestFactory().get('/inventory/source-records/',HTTP_HOST=settings.ALLOWED_HOSTS[0].lstrip('.'))
                request.user=get_user_model().objects.get(pk=actor)
                request.tenant_id=1
                request.org_mode='none'
                request.current_client=None
                request.session={}
                request.resolver_match=resolve(request.path_info)
                print(json.dumps({'starting':label}),flush=True)
                started=time.monotonic()
                with connection.execute_wrapper(trace),patch.object(module,'render',capture),patch.object(context_processors,'issue_selection',selector),patch.object(context_processors,'_nav_issues_count',count_nav),patch.object(context_processors,'_nav_patching_count',count_patch):
                    response=module.source_records(request)
                    size=len(response.content)
                if response.status_code!=200 or len(contexts)!=1:
                    raise RuntimeError('Incomplete view')
                results.append((contexts[0],nav))
                print(json.dumps({'reader':label,'view_render_s':round(time.monotonic()-started,3),'sql_s':round(sum(c['seconds'] for c in calls),3),'query_count':len(calls),'bytes':size,'rows':len(contexts[0]['records']),'slow_calls':[c for c in calls if c['seconds']>=.05]}),flush=True)
            equal=results[0]==results[1]
            print(json.dumps({'complete_context_and_badges_equal':equal,'values_discarded':True}),flush=True)
            if not equal:
                raise RuntimeError('Result mismatch')
    finally:
        connection.close()
        print(json.dumps({'connection_closed':True}),flush=True)

if __name__=='__main__':
    signal.signal(signal.SIGALRM,lambda *_:sys.exit(2))
    signal.alarm(65)
    try:
        main()
    except Exception as error:
        print(json.dumps({'stopped':type(error).__name__}),flush=True)
        raise SystemExit(1) from None
