"""Software review policy as data: concern flag, decision scope and rules.

User decision 2026-10-13: everything that tunes software findings is data with
an admin surface. This adds:

- ``finding_types.concern_signal``: which types are trust/anomaly concerns. A
  publisher approval silences another signal only when no concern exists on the
  title or installation (design D9).
- ``finding_types.default_decision_scope``: the scope a decision made from a
  finding defaults to (rare software: the device; others: everywhere).
- ``software_classifier_rules`` type ``junk_publisher``: placeholder publisher
  strings, a review reason in their own right.
- ``software_suggestion_rules``: signal-to-suggestion rules in priority order
  (design 4.10). Adverse rules always beat favorable ones.
"""

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
ALTER TABLE operations.software_suggestion_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON operations.software_suggestion_rules FOR SELECT USING (TRUE);
GRANT SELECT ON operations.software_suggestion_rules
    TO operations_app, ninja_ingest, operations_readonly;
GRANT INSERT, UPDATE, DELETE ON operations.software_suggestion_rules TO operations_app;

INSERT INTO operations.software_suggestion_rules
    (priority, signal, adverse, suggestion, enabled, note)
VALUES
    (10, 'threat_hit', TRUE, 'investigate', TRUE, 'Threat-intelligence hit on the title or publisher.'),
    (20, 'install_path', TRUE, 'investigate', TRUE, 'An install of this title sits in a suspicious location.'),
    (30, 'suspicious_name', TRUE, 'investigate', TRUE, 'The title matches a suspicious-name pattern.'),
    (40, 'unauthorized_capability', TRUE, 'review_capability', TRUE, 'Remote-management or security capability not authorized for the client.'),
    (50, 'junk_publisher', TRUE, 'investigate', TRUE, 'The publisher is empty or a placeholder.'),
    (60, 'established_publisher', FALSE, 'approve_publisher', TRUE, 'Used by many clients for a while, known vendor, no concern.'),
    (70, 'prevalent', FALSE, 'approve_title', TRUE, 'Installed widely with no concern.'),
    (80, 'fallback', FALSE, 'none', TRUE, 'Not enough evidence to suggest an action.')
ON CONFLICT (signal) DO NOTHING;

INSERT INTO operations.software_classifier_rules
    (rule_type, pattern, is_regex, enabled, note, created_at)
VALUES
    ('junk_publisher', '^\s*$', TRUE, TRUE, 'Empty publisher.', now()),
    ('junk_publisher', '^(your |default )?company name$', TRUE, TRUE, 'Installer template placeholder.', now()),
    ('junk_publisher', '^\{?[0-9a-f]{8}-[0-9a-f]{4}-', TRUE, TRUE, 'GUID instead of a name.', now()),
    ('junk_publisher', '^(unknown|none|n/?a|null|test|publisher|default)$', TRUE, TRUE, 'Generic placeholder word.', now()),
    ('junk_publisher', '^[^a-z]*$', TRUE, TRUE, 'No letters at all.', now())
ON CONFLICT (rule_type, pattern) DO NOTHING;

UPDATE operations.finding_types
   SET concern_signal = TRUE
 WHERE name IN (
     'suspicious_name', 'install_path_suspicious', 'known_malicious_hint',
     'capability_review_candidate', 'unauthorized_av', 'unauthorized_rmm',
     'unauthorized_remote_access', 'rare_recent', 'multi_av_conflict'
 );
UPDATE operations.finding_types SET default_decision_scope = 'device' WHERE name = 'rare_recent';
"""

REVERSE_SQL = r"""
DELETE FROM operations.software_classifier_rules WHERE rule_type = 'junk_publisher';
DROP POLICY IF EXISTS tenant_read ON operations.software_suggestion_rules;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0282_software_device_readiness"),
    ]

    operations: ClassVar[list] = [
        migrations.CreateModel(
            name="SoftwareSuggestionRule",
            fields=[
                ("id", models.SmallAutoField(primary_key=True, serialize=False)),
                ("priority", models.PositiveSmallIntegerField()),
                (
                    "signal",
                    models.CharField(
                        choices=[
                            ("threat_hit", "Threat-intelligence hit"),
                            ("install_path", "Install-path anomaly"),
                            ("suspicious_name", "Suspicious name"),
                            ("unauthorized_capability", "Unauthorized capability"),
                            ("junk_publisher", "Placeholder or junk publisher"),
                            ("established_publisher", "Established publisher"),
                            ("prevalent", "Prevalent, no concern"),
                            ("fallback", "Otherwise"),
                        ],
                        max_length=32,
                        unique=True,
                    ),
                ),
                ("adverse", models.BooleanField(default=True)),
                (
                    "suggestion",
                    models.CharField(
                        choices=[
                            ("investigate", "Investigate"),
                            ("review_capability", "Review capability"),
                            ("approve_publisher", "Approve publisher"),
                            ("approve_title", "Approve title"),
                            ("none", "No suggestion"),
                        ],
                        max_length=32,
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                ("note", models.CharField(blank=True, default="", max_length=240)),
            ],
            options={
                "db_table": "software_suggestion_rules",
                "ordering": ("priority", "id"),
            },
        ),
        migrations.AddField(
            model_name="findingtype",
            name="concern_signal",
            field=models.BooleanField(
                default=False,
                help_text="Checked when a finding of this type is a trust or anomaly concern. A publisher approval does not silence another signal on a title that carries a concern.",
            ),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="default_decision_scope",
            field=models.CharField(
                choices=[
                    ("device", "This device"),
                    ("client", "This client"),
                    ("global", "Everywhere"),
                ],
                default="global",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="softwareclassifierrule",
            name="rule_type",
            field=models.CharField(
                choices=[
                    ("suspicious_name", "Suspicious name"),
                    ("install_path_suspicious", "Suspicious install path"),
                    ("eol_runtime", "End-of-life runtime"),
                    ("junk_publisher", "Placeholder or junk publisher"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
