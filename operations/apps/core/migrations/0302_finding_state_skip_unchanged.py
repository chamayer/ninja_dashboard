"""Skip the full recompute when a reassessment changed nothing.

Migration 0301 refreshes a finding's state on every assessment write. The evaluators rewrite
almost every assessment each hour with an identical response, and the recompute cost them about
40 percent more time (platform evaluate 323 s -> 452 s). An assessment whose response and policy
version are unchanged cannot change the finding's state, so the state is only re-stamped
(``computed_at``), which is what keeps it inside the policy's freshness window. Anything that did
change, a new assessment row, a different policy version, or a state computed under another policy
version, still goes through the full ``refresh_finding_state``.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
/* Re-stamp the state of findings whose reassessment changed nothing. Part of the single
 * writer family: nothing else writes finding_state. Findings with no row, or a row computed under
 * another policy version, are refreshed in full instead. */
CREATE OR REPLACE FUNCTION operations.touch_finding_state(p_ids uuid[])
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE
    active_version text;
    touched uuid[];
BEGIN
    IF p_ids IS NULL OR cardinality(p_ids) = 0 THEN
        RETURN 0;
    END IF;
    SELECT v.version INTO active_version
      FROM operations.condition_policy_versions v WHERE v.active ORDER BY v.version DESC LIMIT 1;
    WITH bumped AS (
        UPDATE operations.finding_state s
           SET computed_at = now()
         WHERE s.finding_id = ANY(p_ids) AND s.policy_version IS NOT DISTINCT FROM active_version
        RETURNING s.finding_id
    )
    SELECT array_agg(finding_id) INTO touched FROM bumped;
    PERFORM operations.refresh_finding_state(
        ARRAY(SELECT unnest(p_ids) EXCEPT SELECT unnest(COALESCE(touched, ARRAY[]::uuid[]))));
    RETURN COALESCE(cardinality(touched), 0);
END
$function$;

/* Rows changed in this UPDATE statement get a full refresh; rows whose response and policy
 * version are identical only re-stamp. A finding with any changed row is refreshed in full. */
CREATE OR REPLACE FUNCTION operations.finding_state_after_assessment_update()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, operations
AS $function$
DECLARE
    changed uuid[];
    unchanged uuid[];
BEGIN
    SELECT array_agg(DISTINCT n.finding_id) INTO changed
      FROM new_rows n
      JOIN old_rows o
        ON o.tenant_id = n.tenant_id AND o.row_kind = n.row_kind AND o.finding_id = n.finding_id
       AND o.participant_kind = n.participant_kind AND o.participant_id = n.participant_id
       AND o.participant_role = n.participant_role
     WHERE n.row_kind = 'entity' AND n.finding_id IS NOT NULL
       AND (n.response IS DISTINCT FROM o.response
            OR n.policy_version IS DISTINCT FROM o.policy_version);
    SELECT array_agg(DISTINCT n.finding_id) INTO unchanged
      FROM new_rows n
     WHERE n.row_kind = 'entity' AND n.finding_id IS NOT NULL
       AND NOT (n.finding_id = ANY(COALESCE(changed, ARRAY[]::uuid[])));
    PERFORM operations.refresh_finding_state(changed);
    PERFORM operations.touch_finding_state(unchanged);
    RETURN NULL;
END
$function$;

DROP TRIGGER IF EXISTS finding_state_assessments_update ON operations.condition_assessments;
CREATE TRIGGER finding_state_assessments_update
AFTER UPDATE ON operations.condition_assessments
REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_assessment_update();

DO $privileges$
DECLARE
    fn text;
BEGIN
    FOREACH fn IN ARRAY ARRAY[
        'operations.touch_finding_state(uuid[])',
        'operations.finding_state_after_assessment_update()'
    ] LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO operations_migrate', fn);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, operations_app, ninja_ingest, '
                       'operations_readonly, metabase_ro', fn);
    END LOOP;
END
$privileges$;
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS finding_state_assessments_update ON operations.condition_assessments;
CREATE TRIGGER finding_state_assessments_update
AFTER UPDATE ON operations.condition_assessments
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION operations.finding_state_after_assessments();
DROP FUNCTION IF EXISTS operations.finding_state_after_assessment_update();
DROP FUNCTION IF EXISTS operations.touch_finding_state(uuid[]);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0301_finding_state"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
