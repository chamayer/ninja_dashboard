"""Approve the audited full classifier revision for automatic recovery."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (
    1, 'software-classify-full', 'replay_safe',
    'Full software classification only reconciles Operations intelligence, findings, and a read model from current source data. A later replay converges to the current installation and policy state and has no external mutation.'
) ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, 'software-classify-full',
       '82349c35e905f3414277ae04243d00e169ea79cb2f0c16dbec1473f3d77025bf',
       authority.recovery_mode, authority.evidence_summary
  FROM operations.job_recovery_policy_authorities AS authority
  JOIN operations.job_definition_versions AS definition_version
    ON definition_version.definition_key = 'software-classify-full'
   AND definition_version.definition_digest = '82349c35e905f3414277ae04243d00e169ea79cb2f0c16dbec1473f3d77025bf'
 WHERE authority.tenant_id = 1 AND authority.definition_key = 'software-classify-full'
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0237_jobs_kev_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
