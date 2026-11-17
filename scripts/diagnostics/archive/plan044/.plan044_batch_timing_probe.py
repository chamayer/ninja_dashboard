import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/app")
import django

django.setup()

from django.db import DatabaseError, connection, transaction

for offset in range(0, 6000, 1000):
    started = time.perf_counter()
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL operations.tenant_id = 1")
            cursor.execute("SET LOCAL statement_timeout = '1200ms'")
            cursor.execute(
                """
                SELECT DISTINCT subject.observation_id
                  FROM operations.findings finding
                  JOIN operations.source_record_subjects subject
                    ON subject.tenant_id = finding.tenant_id AND subject.id = finding.subject_id
                 WHERE finding.tenant_id = 1 AND finding.subject_type = 'source_record'
                   AND finding.status IN ('open', 'acknowledged', 'investigating')
                   AND subject.observation_id IS NOT NULL
                 ORDER BY subject.observation_id
                 LIMIT 1000 OFFSET %s
                """,
                [offset],
            )
            observation_ids = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT count(*)::int, count(client_id)::int "
                "FROM operations.computer_client_independent_evidence_batch(%s, %s)",
                [1, observation_ids],
            )
            rows, attributed = cursor.fetchone()
        print(
            f"offset={offset} records={rows} elapsed_s={time.perf_counter()-started:.3f} "
            f"attributed={attributed}"
        )
    except DatabaseError as error:
        print(
            f"offset={offset} completed=false elapsed_s={time.perf_counter()-started:.3f} "
            f"error={type(error).__name__}"
        )
