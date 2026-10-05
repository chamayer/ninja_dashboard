"""Approve the audited abuse.ch revision for automatic recovery."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES (
    1, 'intel-abusech', 'replay_safe',
    'The abuse.ch refresh only reads public MalwareBazaar and ThreatFox feeds and performs transaction-scoped conditional upserts of local threat signals. A later replay converges to current feed state and has no external mutation.'
)
ON CONFLICT (tenant_id, definition_key) DO NOTHING;

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
)
SELECT 1, seeded.definition_key, seeded.definition_digest,
       authority.recovery_mode, authority.evidence_summary
  FROM (VALUES
    ('intel-abusech', 'ce588955190b02582046a0f8dbfd671b91b2eb42674d0bf5b8f865b697be75bc')
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
        ("operations", "0242_jobs_current_work_activity"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
