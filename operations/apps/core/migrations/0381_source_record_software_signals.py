"""Register source-record suspicious-name and threat-hint findings."""

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
) VALUES
(
    'source_record_suspicious_software', 'medium', 'entity', 'source_record.assessment',
    'source_record', FALSE, TRUE, TRUE, TRUE, 'global', '', '',
    'A source record reports software matching an enabled suspicious-name rule.',
    'Source record has suspicious software', 'Security', 'Suspicious software', 82,
    FALSE, '[]'::jsonb, '', ARRAY['source_record']
),
(
    'source_record_malicious_software_hint', 'low', 'entity', 'source_record.assessment',
    'source_record', FALSE, TRUE, FALSE, TRUE, 'global', '', '',
    'Threat-intelligence feeds report enough signals about software on a source record.',
    'Source record software has threat-intelligence signals', 'Security', 'Threat intelligence', 83,
    FALSE, '[]'::jsonb, '', ARRAY['source_record']
)
ON CONFLICT (name) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0380_source_record_unauthorized_tool"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(TYPE_SQL, migrations.RunSQL.noop),
    ]
