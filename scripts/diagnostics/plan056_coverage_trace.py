"""One bounded read-only Coverage trace; emit timings/code locations only."""

import cProfile
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

    if caches["default"].__class__.__module__ != "django.core.cache.backends.locmem":
        print(json.dumps({"stopped": "shared_cache_configured"}), flush=True)
        return 1
    profiler = cProfile.Profile()
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
        label = "other"
        for relation, name in (
            ("read_hudu_computer_inventory_evidence", "page_hudu_detail"),
            ("v_device_source_link", "page_source_timestamps"),
            ("device_requirement_state", "stored_requirements"),
            ("v_hudu_computer_inventory_observation_current", "hudu_inventory_lifecycle"),
            ("v_device_source_record_lifecycle_current", "source_record_counts"),
            ("v_device_observation_current", "compact_source_observations"),
            ("device_agent_presence_current", "source_presence"),
            ("device_session_current", "computer_inventory"),
        ):
            if relation in sql:
                label = name
                break
        started = time.monotonic()
        try:
            return execute(sql, params, many, context)
        finally:
            item = {"label": label, "location": location, "seconds": round(time.monotonic() - started, 4)}
            calls.append(item)
            if item["seconds"] >= 0.05:
                print(json.dumps({"query": item}), flush=True)

    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='8s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            user = get_user_model().objects.filter(tenant_id=1, is_active=True, is_superuser=True).first()
            if user is None:
                raise RuntimeError("AdministratorUnavailable")
            path = "/inventory/computers/"
            request = RequestFactory().get(path, HTTP_HOST=settings.ALLOWED_HOSTS[0].lstrip("."))
            request.user = user
            request.tenant_id = 1
            request.org_mode = "none"
            request.current_client = None
            request.session = {}
            request.resolver_match = resolve(path)
            started = time.monotonic()
            profiler.enable()
            try:
                with connection.execute_wrapper(trace):
                    response = request.resolver_match.func(request)
                    if hasattr(response, "render"):
                        response.render()
            finally:
                profiler.disable()
            print(json.dumps({"status": response.status_code,
                "handler_s": round(time.monotonic() - started, 3),
                "sql_s": round(sum(c["seconds"] for c in calls), 3),
                "query_count": len(calls), "response_discarded": True}), flush=True)
            entries = []
            for entry in profiler.getstats():
                code = entry.code
                if not isinstance(code, str) and code.co_filename.startswith("/app/apps/core/"):
                    entries.append({"location": code.co_filename.removeprefix("/app/") + ":" + str(code.co_firstlineno) + ":" + code.co_name,
                        "calls": entry.callcount, "self_s": round(entry.inlinetime, 4), "cumulative_s": round(entry.totaltime, 4)})
            print(json.dumps({"top_application_self_time": sorted(entries, key=lambda e: e["self_s"], reverse=True)[:8]}), flush=True)
        return 0
    finally:
        profiler.disable()
        connection.close()
        print(json.dumps({"connection_closed": True}), flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(2))
    signal.alarm(45)
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
