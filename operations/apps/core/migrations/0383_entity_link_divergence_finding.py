"""Register the durable platform finding for entity-link projection drift.

Its condition definition is registered with the other PLAN-036 types in 0387,
so the policy is activated (and finding state recomputed) once.
"""

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
    'entity_link_divergence', 'high', 'admin', 'ingest.platform_findings',
    'device', FALSE, TRUE, FALSE, FALSE, 'global', '', '',
    'The device association projection differs from the confirmed source-link authority.',
    'Computer association projection is inconsistent', 'Data collection',
    'Collection and processing', 640, FALSE, '[]'::jsonb, '', ARRAY[]::text[]
)
ON CONFLICT (name) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0382_independent_identity_corroboration"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(TYPE_SQL, migrations.RunSQL.noop),
    ]
