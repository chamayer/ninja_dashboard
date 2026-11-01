"""Require unique automatic Computer associations (ADR-0050, PLAN-004 §5)."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

POLICY_SQL = r"""
SELECT operations.begin_change(
    'identity_policy.unique_only',
    'ADR-0050 / PLAN-004 §5: ambiguous evidence remains unresolved; recency does not choose a Computer.',
    '{"migration":"0378_strict_identity_matching"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0378', NULL, TRUE)
 WHERE to_regprocedure(
    'operations.begin_change(text, text, jsonb, text, bigint, text, text, bigint, boolean)'
 ) IS NOT NULL;

UPDATE operations.identity_match_policies
   SET requires_unique_candidate = TRUE,
       description = left(description || ' Automatic association requires one eligible Computer; recency never resolves ambiguity.', 300),
       reason = 'ADR-0050 §5: ambiguous candidates remain unassociated.',
       version = version + 1
 WHERE NOT requires_unique_candidate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0377_source_record_software_risk"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(POLICY_SQL, migrations.RunSQL.noop),
        migrations.AddConstraint(
            model_name="identitymatchpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(requires_unique_candidate=True),
                name="ck_identity_match_requires_unique_candidate",
            ),
        ),
    ]
