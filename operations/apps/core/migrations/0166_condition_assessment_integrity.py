"""Add currentness metadata and an atomic participant reconciliation primitive."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.condition_assessments
    ADD COLUMN currentness JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(currentness) = 'object');
ALTER TABLE operations.condition_participants
    ADD CONSTRAINT condition_participant_tenant_positive CHECK (tenant_id > 0);
DROP VIEW operations.v_condition_assessment_current;
CREATE VIEW operations.v_condition_assessment_current
WITH (security_barrier = true, security_invoker = true) AS
SELECT a.tenant_id, a.row_kind, a.finding_id,
       a.participant_kind, a.participant_id, a.participant_role,
       a.condition_identity, a.policy_version, a.policy_digest,
       a.coverage, a.response, a.reevaluation_key, a.currentness, a.assessed_at
  FROM operations.condition_assessments a
 WHERE a.tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_condition_assessment_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_condition_assessment_current TO operations_app,
    ninja_ingest, operations_readonly, metabase_ro;

CREATE OR REPLACE FUNCTION operations.reconcile_condition_participants(
    p_tenant_id BIGINT, p_row_kind TEXT, p_finding_id UUID, p_participants JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
DECLARE item JSONB;
BEGIN
    IF p_tenant_id <= 0 OR p_row_kind NOT IN ('entity', 'admin')
       OR p_finding_id IS NULL OR p_participants IS NULL
       OR jsonb_typeof(p_participants) <> 'array' THEN
        RAISE EXCEPTION 'Invalid condition participant batch';
    END IF;
    IF NULLIF(current_setting('operations.tenant_id', true), '') IS DISTINCT FROM p_tenant_id::text THEN
        RAISE EXCEPTION 'Tenant context is required for condition participant reconciliation';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_tenant_id::text || ':' || p_row_kind || ':' || p_finding_id::text, 0));
    FOR item IN SELECT value FROM jsonb_array_elements(p_participants) LOOP
        IF jsonb_typeof(item) <> 'object'
           OR item->>'kind' !~ '^[a-z][a-z0-9_]{0,63}$'
           OR item->>'role' !~ '^[a-z][a-z0-9_]{0,63}$'
           OR (item->>'reference')::uuid IS NULL
           OR (item->>'tenant_id')::bigint IS DISTINCT FROM p_tenant_id THEN
            RAISE EXCEPTION 'Invalid condition participant';
        END IF;
    END LOOP;
    DELETE FROM operations.condition_assessments a
     WHERE a.tenant_id = p_tenant_id AND a.row_kind = p_row_kind
       AND a.finding_id = p_finding_id AND a.participant_kind <> 'condition'
       AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_participants) AS participant(item)
            WHERE participant.item->>'kind' = a.participant_kind
              AND (participant.item->>'reference')::uuid = a.participant_id
              AND participant.item->>'role' = a.participant_role
       );
    DELETE FROM operations.condition_participants p
     WHERE p.tenant_id = p_tenant_id AND p.row_kind = p_row_kind
       AND p.finding_id = p_finding_id
       AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_participants) AS participant(item)
            WHERE participant.item->>'kind' = p.participant_kind
              AND (participant.item->>'reference')::uuid = p.participant_id
              AND participant.item->>'role' = p.participant_role
       );
    INSERT INTO operations.condition_participants
        (tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role)
    SELECT p_tenant_id, p_row_kind, p_finding_id, participant.item->>'kind',
           (participant.item->>'reference')::uuid, participant.item->>'role'
      FROM jsonb_array_elements(p_participants) AS participant(item)
    ON CONFLICT DO NOTHING;
END
$$;
ALTER FUNCTION operations.reconcile_condition_participants(BIGINT, TEXT, UUID, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.reconcile_condition_participants(BIGINT, TEXT, UUID, JSONB)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.reconcile_condition_participants(BIGINT, TEXT, UUID, JSONB)
    TO operations_app, ninja_ingest;
"""

REVERSE_SQL = """
REVOKE ALL ON FUNCTION operations.reconcile_condition_participants(BIGINT, TEXT, UUID, JSONB)
    FROM PUBLIC, operations_app, ninja_ingest;
DROP FUNCTION IF EXISTS operations.reconcile_condition_participants(BIGINT, TEXT, UUID, JSONB);
DROP VIEW operations.v_condition_assessment_current;
CREATE VIEW operations.v_condition_assessment_current
WITH (security_barrier = true, security_invoker = true) AS
SELECT a.tenant_id, a.row_kind, a.finding_id,
       a.participant_kind, a.participant_id, a.participant_role,
       a.condition_identity, a.policy_version, a.policy_digest,
       a.coverage, a.response, a.reevaluation_key, a.assessed_at
  FROM operations.condition_assessments a
 WHERE a.tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_condition_assessment_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_condition_assessment_current TO operations_app,
    ninja_ingest, operations_readonly, metabase_ro;
ALTER TABLE operations.condition_participants
    DROP CONSTRAINT IF EXISTS condition_participant_tenant_positive;
ALTER TABLE operations.condition_assessments DROP COLUMN IF EXISTS currentness;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0165_govern_condition_policy_activation"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
