"""Register native Hudu reference-review findings for source records."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

TYPE_SQL = r"""
INSERT INTO operations.finding_types (
    name, default_severity, finding_class, source_module, subject_scope,
    creates_device_exposure, auto_resolvable, suppressed_by_approval,
    concern_signal, default_decision_scope, drilldown_evidence_key, runbook_path,
    description, display_name, issue_category, issue_group, sort_order,
    alertable, covered_by, cover_note, allowed_subject_kinds
) VALUES (
    'source_record_reference_review', 'medium', 'entity', 'source_record.assessment',
    'source_record', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
    'A source record has a stale or conflicting reference to a represented Computer.',
    'Source record reference needs review', 'Inventory', 'Hudu references', 84,
    FALSE, '[]'::jsonb, '', ARRAY['source_record']
)
ON CONFLICT (name) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0385_source_record_policy_health"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(TYPE_SQL, migrations.RunSQL.noop),
    ]
