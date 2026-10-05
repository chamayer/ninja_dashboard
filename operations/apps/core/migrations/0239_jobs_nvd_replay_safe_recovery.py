"""Approve the audited NVD reconciliation revision for automatic recovery."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (
    1, 'intel-nvd', 'replay_safe',
    'The NVD refresh only performs transaction-scoped conditional upserts of a public vulnerability feed. A later replay converges to the current feed and has no external mutation.'
) ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, 'intel-nvd',
       '9d58d823a51043da124b6a2da9b867bdb3a740f4824458b470f3965bce333c46',
       authority.recovery_mode, authority.evidence_summary
  FROM operations.job_recovery_policy_authorities AS authority
  JOIN operations.job_definition_versions AS definition_version
    ON definition_version.definition_key = 'intel-nvd'
   AND definition_version.definition_digest = '9d58d823a51043da124b6a2da9b867bdb3a740f4824458b470f3965bce333c46'
 WHERE authority.tenant_id = 1 AND authority.definition_key = 'intel-nvd'
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0238_jobs_full_classification_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
