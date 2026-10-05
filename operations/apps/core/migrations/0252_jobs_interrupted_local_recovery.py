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
VALUES
(1, 'patch-classify', 'd645116fa465cbfa87919c5d23d6ab116e1f9b3c900bc8dbb58809d8e0d67959', 'replay_safe', 'Patch classification reads current local evidence and convergently upserts local findings.'),
(1, 'agent-compliance', '2aa2faa12bbdd3c897f5ed359cb1b77c9bdd1ac0293d692bba936474f9da6525', 'replay_safe', 'Agent compliance refreshes local derived compliance evidence; a later run converges to current source state.')
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""

class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0251_patch_evaluation_state")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
