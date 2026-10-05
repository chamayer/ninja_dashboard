"""Approve the audited KEV reconciliation revision for automatic recovery."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (
    1, 'intel-kev', 'replay_safe',
    'The KEV refresh only performs a transaction-scoped conditional upsert of the public CISA exploited-vulnerability feed. A later replay converges to the current feed and has no external mutation.'
) ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, 'intel-kev',
       '02b8fb3386e13d04ce90e54e1d7253591d9fcee85e98edea9413935b66fd0ade',
       authority.recovery_mode, authority.evidence_summary
  FROM operations.job_recovery_policy_authorities AS authority
  JOIN operations.job_definition_versions AS definition_version
    ON definition_version.definition_key = 'intel-kev'
   AND definition_version.definition_digest = '02b8fb3386e13d04ce90e54e1d7253591d9fcee85e98edea9413935b66fd0ade'
 WHERE authority.tenant_id = 1 AND authority.definition_key = 'intel-kev'
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0236_jobs_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
