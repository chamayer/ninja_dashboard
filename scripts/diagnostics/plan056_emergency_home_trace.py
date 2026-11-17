"""One read-only Home handler trace; output code locations and timings only.

Emergency recovery diagnosis, 2026-11-17. No HTTP login, session write, Job,
shared-cache mutation, SQL text, parameters or response content is emitted.
Middleware/network costs are excluded. Process-local cache starts empty.
"""

import json
import logging
import os
import signal
import sys
import time


def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.cache import caches
    from django.db import connection, transaction
    from django.test import RequestFactory
    from django.urls import resolve

    # Stop rather than populate any configured shared cache during a direct trace.
    if caches["default"].__class__.__module__ != "django.core.cache.backends.locmem":
        print(json.dumps({"stopped": "shared_cache_configured"}), flush=True)
        connection.close()
        return 1
    calls = []

    def trace(execute, sql, params, many, context):
        frame = sys._getframe(1)
        location = "framework"
        while frame is not None:
            filename = frame.f_code.co_filename
            if filename.startswith("/app/apps/core/"):
                location = filename.removeprefix("/app/") + ":" + str(frame.f_lineno) + ":" + frame.f_code.co_name
                break
            frame = frame.f_back
        started = time.monotonic()
        try:
            return execute(sql, params, many, context)
        finally:
            calls.append({"location": location, "seconds": round(time.monotonic() - started, 4)})

    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='12s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            user = get_user_model().objects.filter(tenant_id=1, is_active=True, is_superuser=True).first()
            if user is None:
                raise RuntimeError("AdministratorUnavailable")
            request = RequestFactory().get("/", HTTP_HOST=settings.ALLOWED_HOSTS[0].lstrip("."))
            request.user = user
            request.tenant_id = 1
            request.org_mode = "none"
            request.current_client = None
            request.session = {}
            request.resolver_match = resolve("/")
            started = time.monotonic()
            with connection.execute_wrapper(trace):
                response = request.resolver_match.func(request)
                if hasattr(response, "render"):
                    response.render()
            print(json.dumps({
                "status": response.status_code,
                "handler_s": round(time.monotonic() - started, 3),
                "sql_s": round(sum(c["seconds"] for c in calls), 3),
                "query_count": len(calls),
                "slow_calls": [c for c in calls if c["seconds"] >= 0.05],
                "response_discarded": True,
            }), flush=True)
        return 0
    finally:
        connection.close()
        print(json.dumps({"connection_closed": True}), flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(2))
    signal.alarm(35)
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
