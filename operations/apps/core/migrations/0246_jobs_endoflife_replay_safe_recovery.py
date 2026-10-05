"""Authorize recovery for the interrupted end-of-life corpus revision."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


EVIDENCE = (
    "The end-of-life refresh only reads the public endoflife.date API and "
    "upserts local corpus rows. A later replay converges to current source data "
    "and has no external mutation."
)

FORWARD_SQL = f"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (1, 'intel-endoflife', 'replay_safe', '{EVIDENCE}')
ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, 'intel-endoflife',
       'c28aa89b5e3a05bc6c47b99e613d9fa39ad551400b27eec90cccfe3a6e4a69eb',
       'replay_safe', '{EVIDENCE}'
 WHERE EXISTS (
    SELECT 1 FROM operations.job_definition_versions
     WHERE definition_key = 'intel-endoflife'
       AND definition_digest = 'c28aa89b5e3a05bc6c47b99e613d9fa39ad551400b27eec90cccfe3a6e4a69eb'
 )
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0245_jobs_matcher_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
