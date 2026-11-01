"""Require independent source evidence for serial/VM automatic matches."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

POLICY_SQL = r"""
SELECT operations.begin_change(
    'identity_policy.independent_corroboration',
    'ADR-0050 / PLAN-004 §5: serial and VM UUID matches require corroborating name or MAC evidence from another source instance; conflicting identifiers remain blocking.',
    '{"migration":"0382_independent_identity_corroboration"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0382', NULL, TRUE)
 WHERE to_regprocedure(
    'operations.begin_change(text, text, jsonb, text, bigint, text, text, bigint, boolean)'
 ) IS NOT NULL;

UPDATE operations.identity_match_policies
   SET requires_independent_corroboration = matcher IN ('serial', 'vm_uuid'),
       blocking_signal_keys = CASE matcher
           WHEN 'serial' THEN '["vm_uuid"]'::jsonb
           WHEN 'vm_uuid' THEN '["serial"]'::jsonb
           ELSE '["serial", "vm_uuid", "same_source_live"]'::jsonb
       END,
       description = CASE matcher
           WHEN 'serial' THEN
               'Match one same-client Computer by usable serial only when another source instance independently confirms its name or MAC; a conflicting VM UUID blocks it.'
           WHEN 'vm_uuid' THEN
               'Match one same-client Computer by VM UUID only when another source instance independently confirms its name or MAC; a conflicting serial blocks it.'
           WHEN 'hostname_mac' THEN
               'Match one same-client Computer by name and shared MAC unless serial, VM UUID, or concurrent same-source evidence conflicts.'
           WHEN 'hostname' THEN
               'Match one same-client Computer by the configured comparable name policy unless serial, VM UUID, or concurrent same-source evidence conflicts.'
           WHEN 'source_identity' THEN
               'Keep an established source identity attached unless current serial, VM UUID, or concurrent same-source evidence contradicts it.'
           ELSE description
       END,
       reason = 'ADR-0050 / PLAN-004 §5: strong hardware matches require independent source support.',
       version = version + 1;

SELECT operations.source_record_enqueue(tenant_id, 'source_record', id)
  FROM operations.source_record_subjects
 WHERE subject_kind = 'record';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0381_source_record_software_signals"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="identitymatchpolicy",
            name="requires_independent_corroboration",
            field=models.BooleanField(default=False),
        ),
        migrations.RunSQL(POLICY_SQL, migrations.RunSQL.noop),
        migrations.AddConstraint(
            model_name="identitymatchpolicy",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(matcher__in=["serial", "vm_uuid"])
                    | models.Q(requires_independent_corroboration=True)
                ),
                name="ck_identity_match_hardware_corroboration",
            ),
        ),
    ]
