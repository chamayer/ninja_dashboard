"""Delete recovery configuration for Jobs retired with agent compliance (PLAN-022).

The four Jobs left the registry in the same change. Their recovery policies
and policy approvals describe Jobs that can no longer run, and nothing
references those rows. The two disabled schedules stay: their schedule
events reference them, and job_schedule_events is append-only by design
(reject_jobs_history_mutation, migration 0183), so neither can be removed.
Runs, requests, recovery assessments and definition snapshots are kept as
audit.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DELETE FROM operations.job_recovery_policy_authorities
 WHERE definition_key IN ('agent-compliance', 'agent-compliance-evaluate',
                          'agent-compliance-review-digest', 'parity-check');

DELETE FROM operations.job_recovery_policies
 WHERE definition_key IN ('agent-compliance', 'agent-compliance-evaluate',
                          'agent-compliance-review-digest', 'parity-check');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0350_drop_daily_presence"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
