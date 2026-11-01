"""Register the native source-record software risk finding and assessment rule."""

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
    'source_record_vulnerable_software', 'high', 'entity', 'source_record.assessment',
    'source_record', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
    'A source record reports software with a known severe vulnerability.',
    'Source record has vulnerable software', 'Security', 'Software security', 79,
    FALSE, '[]'::jsonb, '', ARRAY['source_record']
) ON CONFLICT (name) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0376_source_record_software_inventory"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(TYPE_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(
            """
            SELECT operations.source_record_enqueue(
                       tenant_id, 'source_record', source_record_id)
              FROM (SELECT DISTINCT tenant_id, source_record_id
                      FROM operations.source_record_software_current
                     WHERE stale_since IS NULL) inventory;
            """,
            migrations.RunSQL.noop,
        ),
    ]
