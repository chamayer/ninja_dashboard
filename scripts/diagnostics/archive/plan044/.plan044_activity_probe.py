import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/app")
import django

django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute(
        """
        SELECT pid, round(extract(epoch FROM now() - query_start))::int,
               state, coalesce(wait_event_type, 'none'),
               left(regexp_replace(query, E'[\\n\\r\\t]+', ' ', 'g'), 350)
          FROM pg_stat_activity
         WHERE datname = current_database() AND usename = current_user
           AND state = 'active' AND pid <> pg_backend_pid()
         ORDER BY query_start
        """
    )
    rows = cursor.fetchall()
for pid, seconds, state, wait, query in rows:
    print(f"pid={pid} seconds={seconds} state={state} wait={wait} query={query}")
if not rows:
    print("no_other_active_queries")
