"""Align the stored hardware-match policy with the PLAN-015 identifier rule."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

BEGIN_CHANGE = """
SELECT operations.begin_change(
    'identity_policy.identifier_rule', %s,
    '{"migration":"0427_identity_identifier_rule"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0427', NULL, TRUE)
 WHERE to_regprocedure(
    'operations.begin_change(text, text, jsonb, text, bigint, text, text, bigint, boolean)'
 ) IS NOT NULL;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0426_identity_split_membership_guard"),
    ]

    operations: ClassVar[list] = [
        migrations.RemoveConstraint(
            model_name="identitymatchpolicy",
            name="ck_identity_match_hardware_corroboration",
        ),
        migrations.RunSQL(
            BEGIN_CHANGE.replace("%s", "'PLAN-015: matching identifiers do not require corroboration'")
            + "UPDATE operations.identity_match_policies "
              "SET requires_independent_corroboration = false, version = version + 1, "
              "description = CASE "
              "WHEN matcher = 'serial' AND description = "
              "'Match one same-client Computer by usable serial only when another source instance independently confirms its name or MAC; a conflicting VM UUID blocks it.' "
              "THEN 'Match one Computer by usable serial unless current identity evidence conflicts.' "
              "WHEN matcher = 'vm_uuid' AND description = "
              "'Match one same-client Computer by VM UUID only when another source instance independently confirms its name or MAC; a conflicting serial blocks it.' "
              "THEN 'Match one Computer by VM UUID unless current identity evidence conflicts.' "
              "ELSE description END, "
              "reason = CASE WHEN reason = "
              "'ADR-0050 / PLAN-004 §5: strong hardware matches require independent source support.' "
              "THEN 'PLAN-015: matching identifiers need no independent corroboration.' ELSE reason END "
              "WHERE matcher IN ('serial', 'vm_uuid')",
            BEGIN_CHANGE.replace("%s", "'Restore the earlier identity policy'")
            + "UPDATE operations.identity_match_policies "
              "SET requires_independent_corroboration = true, version = version + 1, "
              "description = CASE "
              "WHEN matcher = 'serial' AND description = "
              "'Match one Computer by usable serial unless current identity evidence conflicts.' "
              "THEN 'Match one same-client Computer by usable serial only when another source instance independently confirms its name or MAC; a conflicting VM UUID blocks it.' "
              "WHEN matcher = 'vm_uuid' AND description = "
              "'Match one Computer by VM UUID unless current identity evidence conflicts.' "
              "THEN 'Match one same-client Computer by VM UUID only when another source instance independently confirms its name or MAC; a conflicting serial blocks it.' "
              "ELSE description END, "
              "reason = CASE WHEN reason = "
              "'PLAN-015: matching identifiers need no independent corroboration.' "
              "THEN 'ADR-0050 / PLAN-004 §5: strong hardware matches require independent source support.' "
              "ELSE reason END "
              "WHERE matcher IN ('serial', 'vm_uuid')",
        ),
    ]
