from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
REVOKE ALL ON operations.relationship_types,
    operations.relationship_authority_policies,
    operations.entity_relationship_evidence_current,
    operations.entity_relationship_evidence_history,
    operations.entity_relationship_dirty,
    operations.entity_relationship_decision_current,
    operations.entity_relationships,
    operations.entity_relationship_evidence_support,
    operations.source_events
FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;

GRANT SELECT ON operations.relationship_types
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.relationship_authority_policies
    TO operations_app, ninja_ingest, operations_readonly;
GRANT SELECT, INSERT, UPDATE ON operations.entity_relationship_evidence_current,
    operations.entity_relationship_evidence_history TO ninja_ingest;
GRANT SELECT, INSERT, UPDATE ON operations.entity_relationship_decision_current
    TO operations_app;
GRANT SELECT ON operations.entity_relationships,
    operations.entity_relationship_evidence_support TO operations_app;
GRANT SELECT, INSERT, UPDATE ON operations.source_events TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0114_fix_candidate_projector_defaults"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
