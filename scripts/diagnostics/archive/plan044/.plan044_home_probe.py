import os
import sys
import time
import urllib.error
import urllib.request

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/app")
import django

django.setup()

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.db import connection, transaction
from django.test import Client


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = 1")
    user = get_user_model().objects.filter(is_active=True).order_by("id").first()
if user is None:
    raise SystemExit("No active tenant user available for authenticated probe")

client = Client()
session = client.session
session_saved = False
try:
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session["plan044_probe"] = "temporary"
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL operations.tenant_id = 1")
        session.save()
    session_saved = True
    request = urllib.request.Request(
        "http://127.0.0.1:3002/",
        headers={
            "Cookie": f"{settings.SESSION_COOKIE_NAME}={session.session_key}",
            "Host": "127.0.0.1:3002",
            "User-Agent": "PLAN-044-bounded-home-probe",
        },
    )
    started = time.perf_counter()
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
            body = response.read()
            print(f"status={response.status} elapsed_s={time.perf_counter()-started:.3f} bytes={len(body)}")
    except urllib.error.HTTPError as response:
        body = response.read()
        print(f"status={response.code} elapsed_s={time.perf_counter()-started:.3f} bytes={len(body)}")
    except Exception as error:
        print(f"result={type(error).__name__} elapsed_s={time.perf_counter()-started:.3f}")
finally:
    if session_saved:
        session.delete()
