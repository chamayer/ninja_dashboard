"""Bounded Source Records view/render comparison; no serving-code changes.

Two default GET handlers in one read-only snapshot. Candidate changes exactly
the reviewed page SELECT in this process. Output is timings and equality only.
"""

import ast
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
from unittest.mock import patch

from plan056_source_records_page_plan import SOURCE_CLIENT_SQL, selected_sql


def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.cache import caches
    from django.core.cache.backends.locmem import LocMemCache
    from django.db import connection, transaction
    from django.test import RequestFactory
    from django.urls import resolve
    from apps.core import views

    local_cache = caches["default"]
    if not isinstance(local_cache, LocMemCache):
        raise RuntimeError("Only an isolated local memory cache may be cleared")
    tree = ast.parse(Path("/app/apps/core/views.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "source_records")
    original = selected_sql(function, tree)
    prefix = "WITH page AS MATERIALIZED (\n                SELECT observation.*"
    boundary = "),\n            group_mapping AS MATERIALIZED ("
    if original.count(prefix) != 1 or original.count(boundary) != 1:
        raise ValueError("Unexpected page definition")
    candidate = original.replace(prefix, "WITH page_keys AS MATERIALIZED (\n                SELECT observation.tenant_id, observation.observation_id", 1)
    candidate = candidate.replace(boundary, """),
            page AS MATERIALIZED (
                SELECT observation.*
                  FROM operations.v_entity_observation_admin_metadata observation
                 WHERE observation.tenant_id = operations.current_tenant_id()
                   AND observation.observation_id = ANY(ARRAY(
                       SELECT observation_id FROM page_keys))
            ),
            page_clients AS MATERIALIZED (
                SELECT * FROM operations.computer_client_independent_evidence_batch(
                    operations.current_tenant_id(), ARRAY(SELECT observation_id FROM page))
            ),
            group_mapping AS MATERIALIZED (""", 1)
    if candidate.count(SOURCE_CLIENT_SQL) != 2:
        raise ValueError("Unexpected attribution sites")
    candidate = candidate.replace(SOURCE_CLIENT_SQL, "page_client.client_id").replace(
        "FROM page observation", "FROM page observation LEFT JOIN page_clients page_client ON page_client.observation_id = observation.observation_id", 1
    )
    normalize = lambda sql: " ".join(sql.split())
    expected = normalize(original)
    original_render = views.render
    contexts = []
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='15s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            actor = get_user_model().objects.filter(is_active=True, is_superuser=True).values_list("pk", flat=True).first()
            if actor is None:
                raise RuntimeError("No active administrator context")
            for label in ("current", "candidate"):
                local_cache.clear()
                calls = []
                locations = []
                page_calls = []
                captured = []

                def execute_checked(execute, sql, params, many, context):
                    frame = sys._getframe(1)
                    location = "framework"
                    while frame is not None:
                        if frame.f_code.co_filename.startswith("/app/apps/core/"):
                            location = frame.f_code.co_filename.removeprefix("/app/") + ":" + str(frame.f_lineno) + ":" + frame.f_code.co_name
                            break
                        frame = frame.f_back
                    is_page = isinstance(sql, str) and normalize(sql) == expected
                    if is_page and list(params) != [1, 100, 0, 1]:
                        raise ValueError("Unexpected page scope")
                    started = time.monotonic()
                    try:
                        return execute(candidate if is_page and label == "candidate" else sql, params, many, context)
                    finally:
                        elapsed = time.monotonic() - started
                        calls.append(elapsed)
                        locations.append({"location":location,"seconds":round(elapsed,3)})
                        if is_page:
                            page_calls.append(elapsed)

                def capture_render(request, template, context, *args, **kwargs):
                    if template != "source_records.html":
                        raise ValueError("Unexpected template")
                    captured.append(context.copy())
                    return original_render(request, template, context, *args, **kwargs)

                path = "/inventory/source-records/"
                request = RequestFactory().get(path, HTTP_HOST=settings.ALLOWED_HOSTS[0].lstrip("."))
                request.user = get_user_model().objects.get(pk=actor)
                request.tenant_id = 1
                request.org_mode = "none"
                request.current_client = None
                request.session = {}
                request.resolver_match = resolve(path)
                started = time.monotonic()
                print(json.dumps({"starting": label}), flush=True)
                with connection.execute_wrapper(execute_checked), patch.object(views, "render", capture_render):
                    response = request.resolver_match.func(request)
                    size = len(response.content)
                wall = time.monotonic() - started
                if response.status_code != 200 or len(page_calls) != 1 or len(captured) != 1:
                    raise ValueError("Incomplete view execution")
                contexts.append(captured[0])
                print(json.dumps({
                    "reader": label, "status": response.status_code,
                    "view_render_s": round(wall, 3), "sql_s": round(sum(calls), 3),
                    "page_query_s": round(page_calls[0], 3), "query_count": len(calls),
                    "rendered_bytes": size, "row_count": len(captured[0]["records"]),
                    "scope": "isolated_GET_and_render_including_context_processors",
                    "cache": "local_process_cache_cleared_each_run",
                    "slow_calls":[call for call in locations if call["seconds"] >= 0.05],
                }), flush=True)
            equal = contexts[0] == contexts[1]
            print(json.dumps({"complete_view_context_equal": equal, "values_discarded": True}), flush=True)
            if not equal:
                raise ValueError("Context mismatch")
    finally:
        connection.close()
        print(json.dumps({"connection_closed": True}), flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, lambda *_: sys.exit(2))
    signal.alarm(65)
    try:
        main()
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
