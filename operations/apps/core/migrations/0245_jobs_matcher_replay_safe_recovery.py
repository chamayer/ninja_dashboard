"""Authorize recovery only for the interrupted local CVE matcher revision."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


EVIDENCE = (
    "The CVE matcher rebuilds local match rows in one database transaction and "
    "refreshes a local read model afterward. A later replay converges to current "
    "installed software and intelligence data and has no external mutation."
)

FORWARD_SQL = f"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (1, 'intel-matcher', 'replay_safe', '{EVIDENCE}')
ON CONFLICT (tenant_id, definition_key) DO NOTHING;

/* This is the immutable definition revision recorded by the contained run.
 * The existence check prevents authorizing a digest that was not registered.
 */
INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, 'intel-matcher',
       '91920aa6b5d00667eccd9c186328ddf3dab2f5e6ee9336075e2c5b066f8c266c',
       'replay_safe', '{EVIDENCE}'
 WHERE EXISTS (
    SELECT 1 FROM operations.job_definition_versions
     WHERE definition_key = 'intel-matcher'
       AND definition_digest = '91920aa6b5d00667eccd9c186328ddf3dab2f5e6ee9336075e2c5b066f8c266c'
 )
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0244_jobs_operation_entrypoints"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
