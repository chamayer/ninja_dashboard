import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/app")
import django

django.setup()

from django.db import connection, transaction

with transaction.atomic(), connection.cursor() as cursor:
    cursor.execute("SET LOCAL operations.tenant_id = 1")
    cursor.execute(
        """
        SELECT count(*)::int AS source_record_findings,
               count(*) FILTER (WHERE instance.client_id IS NOT NULL)::int AS assigned_instance,
               count(*) FILTER (WHERE instance.client_id IS NULL)::int AS unassigned_instance
          FROM operations.findings finding
          JOIN operations.source_record_subjects subject
            ON subject.tenant_id = finding.tenant_id AND subject.id = finding.subject_id
          LEFT JOIN operations.source_instances instance
            ON instance.tenant_id = subject.tenant_id
           AND instance.id = subject.source_instance_id
         WHERE finding.tenant_id = 1 AND finding.subject_type = 'source_record'
           AND finding.status IN ('open', 'acknowledged', 'investigating')
           AND (finding.snoozed_until IS NULL OR finding.snoozed_until <= now())
        """
    )
    total, assigned, unassigned = cursor.fetchone()
    print(f"source_record_findings={total} assigned_instances={assigned} unresolved_instances={unassigned}")
