"""Register approved immutable revisions that were interrupted before policy registration."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT DISTINCT run.tenant_id, run.job_key, run.definition_digest,
       authority.recovery_mode, authority.evidence_summary
  FROM operations.operator_job_runs AS run
  JOIN operations.job_recovery_policy_authorities AS authority
    ON authority.tenant_id = run.tenant_id
   AND authority.definition_key = run.job_key
   AND authority.recovery_mode = 'replay_safe'
  JOIN operations.job_resource_claims AS claim
    ON claim.tenant_id = run.tenant_id
   AND claim.run_id = run.id
   AND claim.state = 'contained'
 WHERE run.tenant_id = 1
   AND run.status = 'stalled'
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0259_jobs_current_lifecycle"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
