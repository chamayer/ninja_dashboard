"""Compare grouped count SQL against deployed Sources in one read-only snapshot."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
from unittest.mock import patch

logging.disable(logging.CRITICAL)
signal.alarm(45)
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod')
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.db import connection, transaction
from django.test import RequestFactory
from django.urls import resolve
from django.utils import timezone
from apps.core import views

spec=importlib.util.spec_from_file_location('sources_candidate',Path(__file__).with_name('plan056_sources_counts_candidate.py'))
candidate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)
body=candidate.FORWARD_SQL
body=body[body.index('WITH streams AS'):body.index(';\nREVOKE')]
replacement='SELECT source_instance_id, entity_type, entity_class, current_count, active_count, withdrawn_count, last_seen_at FROM ('+body+') counts WHERE tenant_id = %s ORDER BY source_instance_id, entity_class, entity_type'
results=[]
cache=caches['default']
fixed_now=timezone.now()
try:
    if not isinstance(cache,LocMemCache):
        raise RuntimeError('Only process-local cache can be cleared')
    with transaction.atomic(),connection.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='12s'")
        cur.execute("SET LOCAL lock_timeout='1s'")
        actor=get_user_model().objects.filter(is_active=True,is_superuser=True).values_list('pk',flat=True).first()
        for mode in ('current','grouped'):
            cache.clear()
            contexts=[]
            measurements=[]
            render=views.render
            def capture(request,template,context,*args,**kwargs):
                contexts.append(context)
                return render(request,template,context,*args,**kwargs)
            def intercept(execute,sql,params,many,context):
                count_read='v_source_instance_record_counts' in sql
                if count_read and mode=='grouped':
                    sql=replacement
                started=time.monotonic()
                try:
                    return execute(sql,params,many,context)
                finally:
                    if count_read:
                        measurements.append(round(time.monotonic()-started,4))
            request=RequestFactory().get('/sources/',HTTP_HOST=settings.ALLOWED_HOSTS[0].lstrip('.'))
            request.user=get_user_model().objects.get(pk=actor)
            request.tenant_id=1
            request.org_mode='none'
            request.current_client=None
            request.session={}
            request.resolver_match=resolve(request.path_info)
            started=time.monotonic()
            with connection.execute_wrapper(intercept),patch.object(views,'render',capture),patch.object(views.timezone,'now',return_value=fixed_now):
                response=views.sources_status(request)
            if response.status_code!=200 or len(contexts)!=1:
                raise RuntimeError('Incomplete page')
            results.append((contexts[0],response.content))
            print(json.dumps({'mode':mode,'render_s':round(time.monotonic()-started,3),'count_s':measurements,'bytes':len(response.content)}),flush=True)
        context_equal=results[0][0]==results[1][0]
        # CSRF output may vary between the two independent request objects.
        print(json.dumps({'complete_context_equal':context_equal,'values_discarded':True}),flush=True)
        if not context_equal:
            raise RuntimeError('Context mismatch')
finally:
    connection.close()
