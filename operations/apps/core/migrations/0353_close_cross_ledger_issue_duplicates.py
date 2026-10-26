"""Close legacy entity-ledger duplicates of active admin findings.

Both finding ledgers remain intact. The admin row is authoritative for the
platform conditions that currently emit source_failure and
software_queue_stalled; the entity row is retained with an auditable reason.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
UPDATE operations.findings entity_finding
   SET status = 'resolved',
       resolved_at = now(),
       closed_at = COALESCE(entity_finding.closed_at, now()),
       finding_details = COALESCE(entity_finding.finding_details, '{}'::jsonb)
           || jsonb_build_object(
               'resolution_reason', 'duplicate_of_active_admin_finding',
               'duplicate_admin_finding_id', admin_finding.id::text,
               'resolution_recorded_at', now()::text
           )
  FROM operations.admin_findings admin_finding
  JOIN operations.finding_types admin_type
    ON admin_type.id = admin_finding.finding_type_id
 WHERE entity_finding.tenant_id = admin_finding.tenant_id
   AND entity_finding.condition_key = admin_finding.condition_key
   AND entity_finding.finding_type_id = admin_finding.finding_type_id
   AND admin_type.name IN ('source_failure', 'software_queue_stalled')
   AND admin_finding.status IN ('open', 'acknowledged', 'investigating')
   AND entity_finding.status IN ('open', 'acknowledged', 'investigating');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0352_issue_findings_read_model"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
