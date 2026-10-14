"""Decision helper for undecided software: evidence-based "Supports approval".

User decision 2026-10-14: the approve suggestions rested on popularity alone,
which is not evidence of safety, and no code-signing data is available. This
adds:

- ``software_suggestion_rules.requires``: signals that must all be present with
  the rule's own signal, so a suggestion can need several agreeing facts.
- Signals ``known_vendor`` (the publisher matches a vendor in the vulnerability
  database) and ``publisher_approved`` (other titles from the publisher were
  approved here).
- Suggestion ``supports_approval`` and two rules that use it. The older
  "approve publisher" and "approve title" popularity rules are disabled, not
  deleted, so an administrator can turn them back on.
"""

from typing import ClassVar

from django.db import migrations, models

SIGNALS = [
    ("threat_hit", "Threat-intelligence hit"),
    ("install_path", "Install-path anomaly"),
    ("suspicious_name", "Suspicious name"),
    ("unauthorized_capability", "Unauthorized capability"),
    ("junk_publisher", "Placeholder or junk publisher"),
    ("established_publisher", "Established publisher"),
    ("prevalent", "Prevalent, no concern"),
    ("known_vendor", "Known vendor"),
    ("publisher_approved", "Publisher already approved"),
    ("fallback", "Otherwise"),
]
SUGGESTIONS = [
    ("investigate", "Investigate"),
    ("review_capability", "Review capability"),
    ("approve_publisher", "Approve publisher"),
    ("approve_title", "Approve title"),
    ("supports_approval", "Supports approval"),
    ("none", "No suggestion"),
]

FORWARD_SQL = r"""
INSERT INTO operations.software_suggestion_rules
    (priority, signal, adverse, suggestion, enabled, note, requires)
VALUES
    (52, 'publisher_approved', FALSE, 'supports_approval', TRUE,
     'Other titles from this publisher are already approved here, and nothing concerning is known.',
     '[]'::jsonb),
    (55, 'known_vendor', FALSE, 'supports_approval', TRUE,
     'The publisher matches a vendor in the vulnerability database, it is used by several clients for a while, and nothing concerning is known.',
     '["established_publisher"]'::jsonb)
ON CONFLICT (signal) DO NOTHING;

UPDATE operations.software_suggestion_rules
   SET enabled = FALSE,
       note = note || ' Disabled 2026-10-14: popularity alone is not evidence; see Supports approval.'
 WHERE signal IN ('established_publisher', 'prevalent') AND enabled;
"""

REVERSE_SQL = r"""
DELETE FROM operations.software_suggestion_rules
 WHERE signal IN ('publisher_approved', 'known_vendor');
UPDATE operations.software_suggestion_rules SET enabled = TRUE
 WHERE signal IN ('established_publisher', 'prevalent');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0291_finding_type_alertable"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="softwaresuggestionrule",
            name="requires",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Other signals that must also be present for this rule to apply.",
            ),
        ),
        migrations.AlterField(
            model_name="softwaresuggestionrule",
            name="signal",
            field=models.CharField(choices=SIGNALS, max_length=32, unique=True),
        ),
        migrations.AlterField(
            model_name="softwaresuggestionrule",
            name="suggestion",
            field=models.CharField(choices=SUGGESTIONS, max_length=32),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
