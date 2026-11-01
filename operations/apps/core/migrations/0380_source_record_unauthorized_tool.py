"""Register per-source findings for unauthorized capability software."""

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
    'source_record_unauthorized_tool', 'high', 'entity', 'source_record.assessment',
    'source_record', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
    'A source record reports an alertable software capability that is not authorized by policy.',
    'Source record has an unauthorized tool', 'Security', 'Software authorization', 81,
    FALSE, '[]'::jsonb, '', ARRAY['source_record']
) ON CONFLICT (name) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0379_source_record_rejected_software"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(TYPE_SQL, migrations.RunSQL.noop),
    ]
