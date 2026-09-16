"""Persist reviewed-distinct decisions against exact evidence fingerprints."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.condition_reviewed_distinct (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id),
    condition_identity TEXT NOT NULL,
    membership_fingerprint TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    reviewer_id UUID NOT NULL,
    reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, condition_identity)
);
ALTER TABLE operations.condition_reviewed_distinct ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.condition_reviewed_distinct FORCE ROW LEVEL SECURITY;
CREATE POLICY condition_reviewed_distinct_tenant_isolation
    ON operations.condition_reviewed_distinct
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT);
ALTER TABLE operations.condition_reviewed_distinct OWNER TO operations_migrate;
REVOKE ALL ON operations.condition_reviewed_distinct FROM PUBLIC, operations_app, ninja_ingest;
GRANT SELECT ON operations.condition_reviewed_distinct TO operations_app;
GRANT SELECT ON operations.condition_reviewed_distinct TO ninja_ingest;

CREATE OR REPLACE FUNCTION operations.record_reviewed_distinct(
    p_tenant_id BIGINT, p_condition_identity TEXT, p_membership_fingerprint TEXT,
    p_evidence_fingerprint TEXT, p_reviewer_id UUID, p_reason TEXT
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
ALTER FUNCTION operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, UUID, TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, UUID, TEXT)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, UUID, TEXT)
    TO operations_app;
"""

REVERSE_SQL = """
DROP FUNCTION IF EXISTS operations.record_reviewed_distinct(BIGINT, TEXT, TEXT, TEXT, UUID, TEXT);
DROP TABLE IF EXISTS operations.condition_reviewed_distinct;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0166_condition_assessment_integrity"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
