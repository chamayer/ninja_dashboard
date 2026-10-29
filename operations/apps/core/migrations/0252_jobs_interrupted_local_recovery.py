"""Authorize recovery for verified interrupted local reconciliation handlers."""

from __future__ import annotations
from typing import ClassVar
from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (tenant_id, definition_key, recovery_mode, evidence_summary)
VALUES
(1, 'patch-classify', 'replay_safe', 'Patch classification reads current local evidence and convergently upserts local findings.'),
(1, 'agent-compliance', 'replay_safe', 'Agent compliance refreshes local derived compliance evidence; a later run converges to current source state.')
ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary)
SELECT 1, d.definition_key, d.definition_digest, 'replay_safe', authority.evidence_summary
  FROM operations.job_definition_versions d
  JOIN (VALUES
      ('patch-classify', 'Patch classification reads current local evidence and convergently upserts local findings.'),
      ('agent-compliance', 'Agent compliance refreshes local derived compliance evidence; a later run converges to current source state.')
  ) AS authority(definition_key, evidence_summary)
    ON authority.definition_key = d.definition_key
 WHERE d.handler_version = 'registry-v1'
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""

class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0251_patch_evaluation_state")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
