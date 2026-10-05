"""Approve audited CPE and Ninja collection revisions for automatic recovery."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES
(
    1, 'intel-cpe-dict', 'replay_safe',
    'The CPE dictionary refresh only performs cursor-backed, transaction-scoped conditional upserts of a public feed. A later replay resumes or converges to the current dictionary and has no external mutation.'
),
(
    1, 'patches', 'replay_safe',
    'The Ninja collection cycle only reads the vendor API and reconciles local source projections from the current response. A later replay converges to current source state and has no vendor-side mutation.'
)
ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, seeded.definition_key, seeded.definition_digest,
       authority.recovery_mode, authority.evidence_summary
  FROM (VALUES
    ('intel-cpe-dict', 'a7ac5b98c5463bccbd7c4840e5f1fa4cbf674966e2610f88693b2e37085e4406'),
    ('patches', 'e5b4ca4ad5c9f25c61f7056ecf32331a7daa9bd9aff2e486af478191f7f0c17c')
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
        ("operations", "0239_jobs_nvd_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
