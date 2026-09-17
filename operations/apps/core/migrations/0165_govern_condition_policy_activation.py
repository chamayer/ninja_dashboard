"""Make policy review and activation an explicit database-governed workflow."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.condition_policy_reviews (
    version TEXT PRIMARY KEY REFERENCES operations.condition_policy_versions(version),
    reviewer_id BIGINT NOT NULL,
    reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
    validation_result JSONB NOT NULL CHECK (jsonb_typeof(validation_result) = 'object'),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE operations.condition_policy_reviews OWNER TO operations_migrate;
REVOKE ALL ON operations.condition_policy_reviews FROM PUBLIC, operations_app,
    ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.condition_policy_reviews TO operations_app, ninja_ingest,
    operations_readonly, metabase_ro;

CREATE OR REPLACE FUNCTION operations.review_condition_policy_version(
    p_version TEXT, p_reviewer BIGINT, p_reason TEXT, p_validation_result JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
BEGIN
    IF p_reviewer IS NULL OR p_reason IS NULL OR length(btrim(p_reason)) = 0
       OR p_validation_result IS NULL OR jsonb_typeof(p_validation_result) <> 'object' THEN
        RAISE EXCEPTION 'A reviewer, reason, and validation result are required';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM operations.condition_policy_versions WHERE version = p_version
    ) OR NOT EXISTS (
        SELECT 1 FROM operations.condition_policies WHERE policy_version = p_version
    ) THEN
        RAISE EXCEPTION 'Unknown or incomplete condition policy version: %', p_version;
    END IF;
    INSERT INTO operations.condition_policy_reviews
        (version, reviewer_id, reason, validation_result)
    VALUES (p_version, p_reviewer, btrim(p_reason), p_validation_result);
END
$$;

CREATE OR REPLACE FUNCTION operations.activate_condition_policy_version(p_version TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('operations.condition_policy_activation'));
    IF NOT EXISTS (
        SELECT 1 FROM operations.condition_policy_versions p
        JOIN operations.condition_policy_reviews r ON r.version = p.version
        WHERE p.version = p_version
    ) THEN
        RAISE EXCEPTION 'Policy must be reviewed before activation: %', p_version;
    END IF;
    UPDATE operations.condition_policy_versions SET active = FALSE WHERE active;
    UPDATE operations.condition_policy_versions SET active = TRUE WHERE version = p_version;
    -- Existing assessments are retained for explanation, but lose all
    -- response authority in the same transaction as activation. Producers
    -- must write a fresh assessment under the newly active policy.
    UPDATE operations.condition_assessments
       SET response = response || jsonb_build_object(
               'may_evaluate', false,
               'may_notify', false,
               'may_execute', false,
               'may_clear', false
           ),
           currentness = currentness || jsonb_build_object(
               'invalidated_reason', 'policy_activated',
               'invalidated_by_policy', p_version,
               'invalidated_at', now()
           )
     WHERE policy_version <> p_version;
END
$$;

ALTER FUNCTION operations.review_condition_policy_version(TEXT, BIGINT, TEXT, JSONB)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.review_condition_policy_version(TEXT, BIGINT, TEXT, JSONB)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.review_condition_policy_version(TEXT, BIGINT, TEXT, JSONB)
    TO operations_app;
"""


REVERSE_SQL = """
CREATE OR REPLACE FUNCTION operations.activate_condition_policy_version(p_version TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('operations.condition_policy_activation'));
    IF NOT EXISTS (SELECT 1 FROM operations.condition_policy_versions WHERE version = p_version)
       OR NOT EXISTS (SELECT 1 FROM operations.condition_policies WHERE policy_version = p_version) THEN
        RAISE EXCEPTION 'Unknown or invalid condition policy version: %', p_version;
    END IF;
    UPDATE operations.condition_policy_versions SET active = FALSE WHERE active;
    UPDATE operations.condition_policy_versions SET active = TRUE WHERE version = p_version;
END
$$;
DROP FUNCTION IF EXISTS operations.review_condition_policy_version(TEXT, UUID, TEXT, JSONB);
DROP TABLE IF EXISTS operations.condition_policy_reviews;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0164_policy_defined_issue_categories"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
