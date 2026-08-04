from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.entity_relationship_evidence_history
    ADD CONSTRAINT fk_rel_hist_tenant_current
    FOREIGN KEY (tenant_id, evidence_current_id)
    REFERENCES operations.entity_relationship_evidence_current (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_hist_tenant_source_entity
    FOREIGN KEY (tenant_id, source_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_rel_hist_tenant_target_entity
    FOREIGN KEY (tenant_id, target_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_relationship_evidence_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_relationship_evidence_history
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON operations.entity_relationship_evidence_history
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());

REVOKE ALL ON operations.entity_relationship_evidence_history FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
    ON operations.entity_relationship_evidence_history TO ninja_ingest;
ALTER TABLE operations.entity_relationship_evidence_history
    OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0112_entityrelationshipevidencehistory"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
