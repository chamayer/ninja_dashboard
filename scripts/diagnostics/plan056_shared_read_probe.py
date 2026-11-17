"""One bounded comparison of two shared read patterns; emit no data values."""

import json
import logging
import os
import signal
import sys
import time

SOURCE_COUNTS = """
SELECT source_instance_id,entity_type,entity_class,current_count,active_count,
       withdrawn_count,last_seen_at
FROM operations.v_source_instance_record_counts WHERE tenant_id=1
ORDER BY source_instance_id,entity_class,entity_type
"""

GROUPED_COUNTS = """
WITH streams AS MATERIALIZED (
    SELECT tenant_id,source_instance_id,external_namespace,entity_type,
           count(*)::bigint AS current_count,
           count(*) FILTER(WHERE active)::bigint AS active_count,
           count(*) FILTER(WHERE NOT active)::bigint AS withdrawn_count,
           max(last_seen_at) AS last_seen_at
    FROM operations.v_entity_observation_admin_metadata
    WHERE tenant_id=1
    GROUP BY tenant_id,source_instance_id,external_namespace,entity_type
), included AS MATERIALIZED (
    SELECT * FROM streams
    WHERE NOT operations.is_companion_stream(tenant_id,source_instance_id,external_namespace)
)
SELECT included.source_instance_id,included.entity_type,kind.entity_class_id,
       sum(included.current_count)::bigint,sum(included.active_count)::bigint,
       sum(included.withdrawn_count)::bigint,max(included.last_seen_at)
FROM included JOIN operations.entity_types kind ON kind.name=included.entity_type
GROUP BY included.source_instance_id,included.entity_type,kind.entity_class_id
ORDER BY included.source_instance_id,kind.entity_class_id,included.entity_type
"""


def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from django.db import connection, transaction

    from apps.core import issue_selection

    def execute(cursor, label, statement, params=None):
        started = time.monotonic()
        cursor.execute(statement, params)
        rows = cursor.fetchall()
        print(json.dumps({"read": label, "elapsed_s": round(time.monotonic()-started, 3)}), flush=True)
        return rows

    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id='1'")
            cursor.execute("SET LOCAL statement_timeout='15s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            original = execute(cursor, "source_counts_current", SOURCE_COUNTS)
            grouped = execute(cursor, "source_counts_group_first", GROUPED_COUNTS)
            print(json.dumps({"source_counts_equal": original == grouped}), flush=True)
            if original != grouped:
                raise RuntimeError("Source population mismatch")
            scope = issue_selection.Scope(status="open")
            original_sql, params = issue_selection._filtered_sql(scope, summary=True)
            compact_sql, compact_params = issue_selection._filtered_sql(scope, summary=True, home_compact=True)
            original = execute(cursor, "navigation_count_current", original_sql+" SELECT count(*) FROM selected", params)
            compact = execute(cursor, "navigation_count_compact", compact_sql+" SELECT count(*) FROM selected", compact_params)
            print(json.dumps({"navigation_count_equal": original == compact, "values_discarded": True}), flush=True)
            if original != compact:
                raise RuntimeError("Action population mismatch")
    finally:
        connection.close()


def deadline(signum, frame):
    raise TimeoutError()


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(60)
    try:
        main()
    except Exception as error:
        print(json.dumps({"stopped": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
