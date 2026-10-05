"""Approve the audited OTX revision for automatic replay-safe recovery."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (
    1, 'intel-otx', 'replay_safe',
    'The AlienVault OTX refresh only reads the subscribed-pulse feed and performs transaction-scoped conditional upserts of local threat signals. A later replay converges to current feed state and has no external mutation.'
)
ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, seeded.definition_key, seeded.definition_digest,
       authority.recovery_mode, authority.evidence_summary
  FROM (VALUES
    ('intel-otx', '5046b33141f7403898d0d20f8e68ab84055b87b8e8bf493269b30913be1e687b')
  ) AS seeded(definition_key, definition_digest)
  JOIN operations.job_recovery_policy_authorities AS authority
    ON authority.tenant_id = 1 AND authority.definition_key = seeded.definition_key
  JOIN operations.job_definition_versions AS definition_version
    ON definition_version.definition_key = seeded.definition_key
   AND definition_version.definition_digest = seeded.definition_digest
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0240_jobs_collection_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
