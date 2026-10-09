"""Repair generic projections that source refreshes depend on."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.validate_relationship_tuple()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE contract relationship_types%ROWTYPE; source_row entities%ROWTYPE; target_row entities%ROWTYPE;
BEGIN
    SELECT * INTO contract FROM relationship_types WHERE key = NEW.relationship_type_id;
    IF NOT FOUND OR NOT contract.enabled THEN RAISE EXCEPTION 'relationship type is missing or disabled'; END IF;
    SELECT * INTO source_row FROM entities WHERE id = NEW.source_entity_id AND tenant_id = NEW.tenant_id;
    SELECT * INTO target_row FROM entities WHERE id = NEW.target_entity_id AND tenant_id = NEW.tenant_id;
    IF source_row.id IS NULL OR target_row.id IS NULL THEN RAISE EXCEPTION 'relationship endpoints must belong to the decision tenant'; END IF;
    IF source_row.entity_class_id <> contract.source_entity_class_id OR target_row.entity_class_id <> contract.target_entity_class_id THEN
        RAISE EXCEPTION 'relationship endpoint classes do not match the type contract';
    END IF;
    IF NEW.source_entity_id = NEW.target_entity_id THEN RAISE EXCEPTION 'relationship endpoints must be distinct'; END IF;
    IF TG_TABLE_NAME = 'entity_relationships' AND to_jsonb(NEW)->>'status' = 'active' THEN
        IF contract.source_cardinality = 'one' AND EXISTS (SELECT 1 FROM entity_relationships edge WHERE edge.tenant_id = NEW.tenant_id AND edge.relationship_type_id = NEW.relationship_type_id AND edge.source_entity_id = NEW.source_entity_id AND edge.target_entity_id <> NEW.target_entity_id AND edge.status = 'active') THEN RAISE EXCEPTION 'relationship source cardinality would be exceeded'; END IF;
        IF contract.target_cardinality = 'one' AND EXISTS (SELECT 1 FROM entity_relationships edge WHERE edge.tenant_id = NEW.tenant_id AND edge.relationship_type_id = NEW.relationship_type_id AND edge.target_entity_id = NEW.target_entity_id AND edge.source_entity_id <> NEW.source_entity_id AND edge.status = 'active') THEN RAISE EXCEPTION 'relationship target cardinality would be exceeded'; END IF;
    END IF;
    RETURN NEW;
END
$function$;

/* An attached candidate must reference an entity of its declared class.  Clear
 * historical invalid attachments so the projector can reassess them from
 * current source links instead of retaining an impossible foreign key. */
UPDATE operations.entity_candidates candidate
   SET status = 'observed_only', resolved_entity_id = NULL,
       latest_decision = '', latest_decision_reason = 'Awaiting a matching source entity.',
       latest_decided_at = clock_timestamp(), version = version + 1
 WHERE candidate.resolved_entity_id IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM operations.entities entity
        WHERE entity.tenant_id = candidate.tenant_id
          AND entity.id = candidate.resolved_entity_id
          AND entity.entity_class_id = candidate.proposed_entity_class_id
   );

CREATE OR REPLACE FUNCTION operations.guard_candidate_resolved_entity_class()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
BEGIN
    IF NEW.resolved_entity_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM entities entity
         WHERE entity.tenant_id = NEW.tenant_id
           AND entity.id = NEW.resolved_entity_id
           AND entity.entity_class_id = NEW.proposed_entity_class_id
    ) THEN
        NEW.status := 'observed_only';
        NEW.resolved_entity_id := NULL;
        NEW.latest_decision := '';
        NEW.latest_decision_reason := 'Awaiting a matching source entity.';
        NEW.latest_decided_at := clock_timestamp();
    END IF;
    RETURN NEW;
END
$function$;
DROP TRIGGER IF EXISTS guard_candidate_resolved_entity_class ON operations.entity_candidates;
CREATE TRIGGER guard_candidate_resolved_entity_class
BEFORE INSERT OR UPDATE OF resolved_entity_id, proposed_entity_class_id ON operations.entity_candidates
FOR EACH ROW EXECUTE FUNCTION operations.guard_candidate_resolved_entity_class();

ALTER FUNCTION operations.validate_relationship_tuple() OWNER TO operations_migrate;
ALTER FUNCTION operations.guard_candidate_resolved_entity_class() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.guard_candidate_resolved_entity_class() FROM PUBLIC;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0272_source_to_tenant_workflow_scope"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
