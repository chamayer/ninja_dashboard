"""One bounded read-only Sources render; print timings and shape only."""
import json
import logging
import os
import signal
import sys
import time
from unittest.mock import patch

logging.disable(logging.CRITICAL)
signal.alarm(40)
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod')
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import RequestFactory
from django.urls import resolve
from apps.core import views

queries=[]
contexts=[]
render=views.render
def capture(request, template, context, *args, **kwargs):
    contexts.append(context)
    return render(request, template, context, *args, **kwargs)

def trace(execute, sql, params, many, context):
    label=next((name for name in ('v_source_instance_health','v_source_instance_record_counts','operator_job_runs','finding_state','entity_observation') if name in sql),'other')
    started=time.monotonic()
    try:
        return execute(sql,params,many,context)
    finally:
        queries.append({'reader':label,'seconds':round(time.monotonic()-started,4)})

try:
    with transaction.atomic(),connection.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SET LOCAL operations.tenant_id='1'")
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute("SET LOCAL lock_timeout='1s'")
        actor=get_user_model().objects.filter(is_active=True,is_superuser=True).first()
        if actor is None:
            raise RuntimeError('No administrator')
        request=RequestFactory().get('/sources/',HTTP_HOST=settings.ALLOWED_HOSTS[0].lstrip('.'))
        request.user=actor
        request.tenant_id=1
        request.org_mode='none'
        request.current_client=None
        request.session={}
        request.resolver_match=resolve(request.path_info)
        started=time.monotonic()
        with connection.execute_wrapper(trace),patch.object(views,'render',capture):
            response=views.sources_status(request)
        print(json.dumps({'status':response.status_code,'render_s':round(time.monotonic()-started,3),'bytes':len(response.content),'queries':queries,'source_groups':len(contexts[0]['source_groups'])}),flush=True)
finally:
    connection.close()
