"""Let disjoint Jobs use the existing two-work global capacity."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = """
UPDATE operations.job_lane_limits
   SET capacity = 2,
       policy_revision = 'd2be923381651b35dc2f6be7f3a1568248c126e8c0ea3c6e3a84f94a68e11b4f'
 WHERE tenant_id = 1
   AND lane IN ('collection', 'evaluation', 'software', 'intelligence', 'service');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0247_jobs_domain_resource_ownership"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
