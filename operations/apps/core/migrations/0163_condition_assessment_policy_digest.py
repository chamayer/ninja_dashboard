"""Retain the exact policy digest used by each condition assessment."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.condition_assessments
    ADD COLUMN policy_digest TEXT;

UPDATE operations.condition_assessments a
   SET policy_digest = p.digest
  FROM operations.condition_policy_versions p
 WHERE p.version = a.policy_version;

ALTER TABLE operations.condition_assessments
    ALTER COLUMN policy_digest SET NOT NULL;
ALTER TABLE operations.condition_policy_versions
    ADD CONSTRAINT uq_condition_policy_version_digest UNIQUE (version, digest);
ALTER TABLE operations.condition_assessments
    ADD CONSTRAINT fk_condition_assessment_policy_digest
    FOREIGN KEY (policy_version, policy_digest)
    REFERENCES operations.condition_policy_versions (version, digest);

DROP VIEW operations.v_condition_assessment_current;
CREATE VIEW operations.v_condition_assessment_current
WITH (security_barrier = true, security_invoker = true) AS
SELECT a.tenant_id, a.row_kind, a.finding_id,
       a.participant_kind, a.participant_id, a.participant_role,
       a.condition_identity,
       a.policy_version, a.policy_digest, a.coverage, a.response,
       a.reevaluation_key, a.assessed_at
  FROM operations.condition_assessments a
 WHERE a.tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_condition_assessment_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_condition_assessment_current TO operations_app,
    ninja_ingest, operations_readonly, metabase_ro;

CREATE INDEX idx_condition_assessments_policy_current
    ON operations.condition_assessments
       (tenant_id, row_kind, finding_id, policy_version, policy_digest, assessed_at);
"""

REVERSE_SQL = """
DROP INDEX IF EXISTS operations.idx_condition_assessments_policy_current;
ALTER TABLE operations.condition_assessments
    DROP CONSTRAINT IF EXISTS fk_condition_assessment_policy_digest;
ALTER TABLE operations.condition_policy_versions
    DROP CONSTRAINT IF EXISTS uq_condition_policy_version_digest;
DROP VIEW operations.v_condition_assessment_current;
CREATE VIEW operations.v_condition_assessment_current
WITH (security_barrier = true, security_invoker = true) AS
SELECT a.tenant_id, a.row_kind, a.finding_id,
       a.participant_kind, a.participant_id, a.participant_role,
       a.condition_identity,
       a.policy_version, a.coverage, a.response,
       a.reevaluation_key, a.assessed_at
  FROM operations.condition_assessments a
 WHERE a.tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_condition_assessment_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_condition_assessment_current TO operations_app,
    ninja_ingest, operations_readonly, metabase_ro;
ALTER TABLE operations.condition_assessments
    DROP COLUMN IF EXISTS policy_digest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0162_harden_condition_policy_authority")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
