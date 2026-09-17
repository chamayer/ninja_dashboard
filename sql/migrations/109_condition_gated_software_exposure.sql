-- Require current effective condition authority for every device exposure.
-- This is an additive replacement for the view introduced by migration 107.
CREATE OR REPLACE VIEW operations.v_device_software_exposure
WITH (security_barrier = true) AS
WITH software_findings AS (
    SELECT f.id AS finding_id, f.tenant_id, f.finding_type_id, f.subject_type,
           f.subject_id, f.severity, f.status, f.first_seen_at, f.last_seen_at,
           f.finding_details, ft.name AS finding_type
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE f.subject_type IN ('software_product', 'software_version')
       AND f.status IN ('open', 'acknowledged', 'investigating')
       AND ft.creates_device_exposure
),
exposed AS (
    SELECT sf.*, version.id AS software_version_id
      FROM software_findings sf
      JOIN catalog.products product ON product.product_uuid = sf.subject_id
      JOIN catalog.software_versions version ON version.product_id = product.id
     WHERE sf.subject_type = 'software_product'
    UNION ALL
    SELECT sf.*, version.id AS software_version_id
      FROM software_findings sf
      JOIN catalog.software_versions version ON version.version_uuid = sf.subject_id
     WHERE sf.subject_type = 'software_version'
)
SELECT e.finding_id, e.tenant_id, e.finding_type_id, e.finding_type,
       e.subject_type, e.subject_id, e.severity, e.status,
       e.first_seen_at, e.last_seen_at, e.finding_details,
       installation.device_id, installation.client_id,
       installation.canonical_name, installation.publisher,
       installation.install_location, installation.install_date, version.version
  FROM exposed e
  JOIN operations.software_installations_current installation
    ON installation.software_version_id = e.software_version_id
   AND installation.tenant_id = e.tenant_id
  JOIN catalog.software_versions version ON version.id = e.software_version_id
 WHERE installation.stale_since IS NULL
   AND installation.deleted_at IS NULL
   AND EXISTS (
       SELECT 1
         FROM operations.v_software_installation_evidence_current evidence
        WHERE evidence.tenant_id = installation.tenant_id
          AND evidence.device_id = installation.device_id
          AND evidence.canonical_name = installation.canonical_name
          AND evidence.evidence_state IN ('current', 'offline')
   )
   AND EXISTS (
       SELECT 1
         FROM operations.condition_assessments assessment
         JOIN operations.condition_policy_versions policy
           ON policy.version = assessment.policy_version AND policy.active
        WHERE assessment.tenant_id = installation.tenant_id
          AND assessment.row_kind = 'entity'
          AND assessment.finding_id = e.finding_id
          AND assessment.participant_kind = 'device'
          AND assessment.participant_id = installation.device_id
          AND assessment.participant_role <> 'context'
          AND (assessment.response->>'may_execute')::boolean IS TRUE
          AND assessment.assessed_at >= now() -
              (policy.policy->>'freshness_hours')::integer * interval '1 hour'
   )
   AND NOT EXISTS (
        SELECT 1 FROM operations.software_decisions decision
         WHERE decision.tenant_id = installation.tenant_id
           AND decision.device_id = installation.device_id
           AND decision.decision IN ('approve', 'approve_publisher')
           AND ((decision.canonical_name <> '' AND decision.canonical_name = installation.canonical_name)
             OR (decision.publisher <> '' AND decision.publisher = installation.publisher))
   )
   AND NOT EXISTS (
        SELECT 1 FROM operations.software_decisions decision
         WHERE decision.tenant_id = installation.tenant_id
           AND decision.client_id = installation.client_id
           AND decision.device_id IS NULL
           AND decision.decision IN ('approve', 'approve_publisher')
           AND ((decision.canonical_name <> '' AND decision.canonical_name = installation.canonical_name)
             OR (decision.publisher <> '' AND decision.publisher = installation.publisher))
   );

ALTER VIEW operations.v_device_software_exposure OWNER TO operations_view_owner;
GRANT SELECT ON operations.condition_assessments,
    operations.condition_policy_versions
TO operations_view_owner;
REVOKE ALL ON operations.v_device_software_exposure
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_device_software_exposure
TO operations_app, operations_readonly, metabase_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_device_software_exposure
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
