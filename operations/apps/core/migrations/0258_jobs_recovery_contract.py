"""Make reviewed source-collector replay recovery durable."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES
    (
        1, 'agent-observations', 'replay_safe',
        'Agent observation collection only reads connected source APIs and writes current local observations and derived projections. A later replay converges to current source state and has no source-side mutation.'
    ),
    (
        1, 'documentation-observations', 'replay_safe',
        'Documentation observation collection only reads CMDB source APIs and writes current local observations and derived projections. A later replay converges to current source state and has no source-side mutation.'
    )
ON CONFLICT (tenant_id, definition_key) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0257_jobs_dispatch_runnable_ready"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
