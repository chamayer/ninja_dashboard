"""Delete configuration for Jobs retired with agent compliance (PLAN-022).

The four Jobs left the registry in the same change. Their recovery policies,
policy approvals and two disabled schedules describe Jobs that can no longer
run. A schedule cannot be deleted while its schedule events reference it, so
those events (the scheduler's due/requested/skipped log for the two
schedules) go with it, by the user's decision on 2026-10-26. Runs, requests,
recovery assessments and the definition snapshots they point at are kept as
audit.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DELETE FROM operations.job_schedule_events
 WHERE schedule_id IN (
       SELECT id FROM operations.job_schedules
        WHERE definition_key IN ('agent-compliance', 'agent-compliance-evaluate',
                                 'agent-compliance-review-digest', 'parity-check'));

DELETE FROM operations.job_schedules
 WHERE definition_key IN ('agent-compliance', 'agent-compliance-evaluate',
                          'agent-compliance-review-digest', 'parity-check');

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
