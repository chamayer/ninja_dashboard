"""Align condition reviewer identifiers with Django's integer user IDs."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM operations.condition_policy_reviews
        WHERE reviewer_id::text !~ '^[0-9]+$'
    ) OR EXISTS (
        SELECT 1 FROM operations.condition_reviewed_distinct
        WHERE reviewer_id::text !~ '^[0-9]+$'
    ) THEN
        RAISE EXCEPTION
            'Condition reviewer data contains non-numeric IDs; map reviewers before migration 0169';
    END IF;
END
$$;
ALTER TABLE operations.condition_policy_reviews
    ALTER COLUMN reviewer_id TYPE BIGINT USING reviewer_id::text::bigint;
ALTER TABLE operations.condition_reviewed_distinct
    ALTER COLUMN reviewer_id TYPE BIGINT USING reviewer_id::text::bigint;
DROP FUNCTION IF EXISTS operations.review_condition_policy_version(TEXT, UUID, TEXT, JSONB);
CREATE OR REPLACE FUNCTION operations.review_condition_policy_version(
    p_version TEXT, p_reviewer BIGINT, p_reason TEXT, p_validation_result JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
BEGIN
    IF p_reviewer IS NULL OR p_reason IS NULL OR length(btrim(p_reason)) = 0
       OR p_validation_result IS NULL OR jsonb_typeof(p_validation_result) <> 'object' THEN
        RAISE EXCEPTION 'A reviewer, reason, and validation result are required';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM operations.condition_policy_versions WHERE version = p_version)
       OR NOT EXISTS (SELECT 1 FROM operations.condition_policies WHERE policy_version = p_version) THEN
        RAISE EXCEPTION 'Unknown or incomplete condition policy version: %', p_version;
    END IF;
    INSERT INTO operations.condition_policy_reviews
        (version, reviewer_id, reason, validation_result)
    VALUES (p_version, p_reviewer, btrim(p_reason), p_validation_result);
END
$$;
ALTER FUNCTION operations.review_condition_policy_version(TEXT, BIGINT, TEXT, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.review_condition_policy_version(TEXT, BIGINT, TEXT, JSONB)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.review_condition_policy_version(TEXT, BIGINT, TEXT, JSONB)
    TO operations_app;
DROP FUNCTION IF EXISTS operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, UUID, TEXT);
CREATE OR REPLACE FUNCTION operations.record_reviewed_distinct(
    p_tenant_id BIGINT, p_condition_identity TEXT, p_membership_fingerprint TEXT,
    p_evidence_fingerprint TEXT, p_reviewer_id BIGINT, p_reason TEXT
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
BEGIN
    IF NULLIF(current_setting('operations.tenant_id', true), '') IS DISTINCT FROM p_tenant_id::text
       OR p_tenant_id <= 0 OR p_condition_identity IS NULL OR p_membership_fingerprint IS NULL
       OR p_evidence_fingerprint IS NULL OR p_reviewer_id IS NULL
       OR p_reason IS NULL OR length(btrim(p_reason)) = 0 THEN
        RAISE EXCEPTION 'Invalid reviewed-distinct decision or tenant context';
    END IF;
    INSERT INTO operations.condition_reviewed_distinct
        (tenant_id, condition_identity, membership_fingerprint, evidence_fingerprint,
         reviewer_id, reason)
    VALUES (p_tenant_id, p_condition_identity, p_membership_fingerprint,
            p_evidence_fingerprint, p_reviewer_id, btrim(p_reason))
    ON CONFLICT (tenant_id, condition_identity) DO UPDATE SET
        membership_fingerprint = EXCLUDED.membership_fingerprint,
        evidence_fingerprint = EXCLUDED.evidence_fingerprint,
        reviewer_id = EXCLUDED.reviewer_id, reason = EXCLUDED.reason,
        reviewed_at = now();
END
$$;
ALTER FUNCTION operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, BIGINT, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, BIGINT, TEXT)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, BIGINT, TEXT)
    TO operations_app;
"""

REVERSE_SQL = """
-- Integer Django user IDs are the canonical representation; no lossy UUID
-- reverse conversion is provided.
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0168_preserve_operator_finding_episodes"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
