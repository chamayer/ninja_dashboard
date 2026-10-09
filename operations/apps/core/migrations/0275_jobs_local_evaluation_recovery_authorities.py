"""Approve replay-safe recovery for local-only evaluation Jobs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES
    (1, 'resolver', 'replay_safe', 'Record matching drains local Operations observations into canonical identity links. A later replay converges to the current evidence and does not mutate an external system.'),
    (1, 'patch-classify', 'replay_safe', 'Patch-status evaluation reads local Ninja evidence and convergently updates local findings. A later replay has no external mutation.'),
    (1, 'platform-evaluate', 'replay_safe', 'Client-status evaluation reads local Operations evidence and convergently updates local findings. A later replay has no external mutation.')
ON CONFLICT (tenant_id, definition_key) DO UPDATE
   SET recovery_mode = EXCLUDED.recovery_mode,
       evidence_summary = EXCLUDED.evidence_summary,
       reviewed_at = now();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0274_jobs_retire_undeclared_schedules"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
