-- 112: restore the derived/live split for device software exposure.
--
-- The live exposure view had become an estate-wide fan-out plus source-current
-- and condition-authority checks on every operator request.  That is derived
-- state, not an operator decision.  Keep it in one rebuildable materialized
-- read model, then retain only approvals in the public effective view so an
-- operator's approval is still immediate.
--
-- This supersedes the retired 083 base with the current safeguards from 107
-- and 109. The base retains source/evaluation freshness deadlines; the public
-- view evaluates those clocks live so delayed work cannot leave stale exposure.

CREATE MATERIALIZED VIEW operations.device_software_exposure_current AS
WITH evidence_policy AS (
    SELECT GREATEST(
               COALESCE(
                   MAX(NULLIF(config->>'installation_evidence_max_age_hours', '')::integer),
                   24
               ),
               1
           ) AS max_age_hours
      FROM operations.evaluator_config
     WHERE evaluator_name = 'software_classifier'
),
current_installation_evidence AS (
    SELECT history.tenant_id,
           history.device_id,
           history.canonical_name,
           MAX(
               history.last_seen_at + make_interval(hours => policy.max_age_hours)
           ) AS evidence_fresh_until
      FROM operations.software_installation_history history
      JOIN operations.source_bindings binding
        ON binding.tenant_id = history.tenant_id
       AND binding.id = history.source_binding_id
      JOIN operations.source_instances source_instance
        ON source_instance.tenant_id = binding.tenant_id
       AND source_instance.id = binding.source_instance_id
      JOIN operations.entity_observation_current observation
        ON observation.tenant_id = history.tenant_id
       AND observation.device_id = history.device_id
       AND observation.source_instance_id = binding.source_instance_id
       AND observation.active
     CROSS JOIN evidence_policy policy
      LEFT JOIN LATERAL (
          SELECT mapping.counts_as_current_computer_evidence
            FROM operations.source_record_lifecycle_mappings mapping
           WHERE mapping.enabled
             AND (mapping.source_id IS NULL
                  OR mapping.source_id = source_instance.source_id)
             AND (mapping.external_namespace = ''
                  OR mapping.external_namespace = observation.external_namespace)
             AND (mapping.entity_type = ''
                  OR mapping.entity_type = observation.entity_type)
             AND observation.canonical_data -> mapping.canonical_field = mapping.match_value
           ORDER BY mapping.priority, mapping.id
           LIMIT 1
      ) lifecycle ON TRUE
     WHERE history.active
       AND history.effective_to IS NULL
       AND COALESCE(lifecycle.counts_as_current_computer_evidence, TRUE)
     GROUP BY history.tenant_id, history.device_id, history.canonical_name
),
current_condition_authority AS (
    SELECT assessment.tenant_id,
           assessment.finding_id,
           assessment.participant_id AS device_id,
           MAX(
               assessment.assessed_at + make_interval(
                   hours => (policy.policy->>'freshness_hours')::integer
               )
           ) AS condition_fresh_until
      FROM operations.condition_assessments assessment
      JOIN operations.condition_policy_versions policy
        ON policy.version = assessment.policy_version
       AND policy.active
     WHERE assessment.row_kind = 'entity'
       AND assessment.participant_kind = 'device'
       AND assessment.participant_role <> 'context'
       AND (assessment.response->>'may_execute')::boolean IS TRUE
     GROUP BY assessment.tenant_id, assessment.finding_id, assessment.participant_id
),
software_findings AS (
    SELECT finding.id AS finding_id,
           finding.tenant_id,
           finding.finding_type_id,
           finding.subject_type,
           finding.subject_id,
           finding.severity,
           finding.status,
           finding.first_seen_at,
           finding.last_seen_at,
           finding.finding_details,
           finding_type.name AS finding_type
      FROM operations.findings finding
      JOIN operations.finding_types finding_type ON finding_type.id = finding.finding_type_id
     WHERE finding.subject_type IN ('software_product', 'software_version')
       AND finding.status IN ('open', 'acknowledged', 'investigating')
       AND finding_type.creates_device_exposure
),
exposed_versions AS (
    SELECT finding.*, version.id AS software_version_id
      FROM software_findings finding
      JOIN catalog.products product ON product.product_uuid = finding.subject_id
      JOIN catalog.software_versions version ON version.product_id = product.id
     WHERE finding.subject_type = 'software_product'
    UNION ALL
    SELECT finding.*, version.id AS software_version_id
      FROM software_findings finding
      JOIN catalog.software_versions version ON version.version_uuid = finding.subject_id
     WHERE finding.subject_type = 'software_version'
)
SELECT exposed.finding_id,
       exposed.tenant_id,
       exposed.finding_type_id,
       exposed.finding_type,
       exposed.subject_type,
       exposed.subject_id,
       exposed.severity,
       exposed.status,
       exposed.first_seen_at,
       exposed.last_seen_at,
       exposed.finding_details,
       installation.device_id,
       installation.client_id,
       installation.canonical_name,
       installation.publisher,
       installation.install_location,
       installation.install_date,
       version.version,
       evidence.evidence_fresh_until,
       authority.condition_fresh_until,
       now() AS computed_at
  FROM exposed_versions exposed
  JOIN operations.software_installations_current installation
    ON installation.tenant_id = exposed.tenant_id
   AND installation.software_version_id = exposed.software_version_id
  JOIN catalog.software_versions version ON version.id = exposed.software_version_id
  JOIN current_installation_evidence evidence
    ON evidence.tenant_id = installation.tenant_id
   AND evidence.device_id = installation.device_id
   AND evidence.canonical_name = installation.canonical_name
  JOIN current_condition_authority authority
    ON authority.tenant_id = installation.tenant_id
   AND authority.finding_id = exposed.finding_id
   AND authority.device_id = installation.device_id
 WHERE installation.stale_since IS NULL
   AND installation.deleted_at IS NULL;

CREATE UNIQUE INDEX device_software_exposure_current_pk
    ON operations.device_software_exposure_current
       (tenant_id, finding_id, device_id, canonical_name);
CREATE INDEX device_software_exposure_current_device_idx
    ON operations.device_software_exposure_current (tenant_id, device_id);
CREATE INDEX device_software_exposure_current_client_idx
    ON operations.device_software_exposure_current (tenant_id, client_id);
CREATE INDEX device_software_exposure_current_finding_idx
    ON operations.device_software_exposure_current (tenant_id, finding_id);
CREATE INDEX device_software_exposure_current_title_idx
    ON operations.device_software_exposure_current (tenant_id, canonical_name);
CREATE INDEX device_software_exposure_current_freshness_idx
    ON operations.device_software_exposure_current
       (tenant_id, evidence_fresh_until, condition_fresh_until);

ALTER MATERIALIZED VIEW operations.device_software_exposure_current
    OWNER TO operations_migrate;
REVOKE ALL ON operations.device_software_exposure_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.device_software_exposure_current
    TO operations_view_owner;
GRANT SELECT ON TABLE operations.devices, operations.software_decisions
    TO operations_view_owner;

CREATE OR REPLACE VIEW operations.v_device_software_exposure
WITH (security_barrier = true) AS
SELECT exposure.finding_id,
       exposure.tenant_id,
       exposure.finding_type_id,
       exposure.finding_type,
       exposure.subject_type,
       exposure.subject_id,
       exposure.severity,
       exposure.status,
       exposure.first_seen_at,
       exposure.last_seen_at,
       exposure.finding_details,
       exposure.device_id,
       exposure.client_id,
       exposure.canonical_name,
       exposure.publisher,
       exposure.install_location,
       exposure.install_date,
       exposure.version
  FROM operations.device_software_exposure_current exposure
  JOIN operations.devices device
    ON device.tenant_id = exposure.tenant_id
   AND device.id = exposure.device_id
   AND device.deleted_at IS NULL
 WHERE exposure.tenant_id = operations.current_tenant_id()
   AND exposure.evidence_fresh_until >= now()
   AND exposure.condition_fresh_until >= now()
   AND NOT EXISTS (
        SELECT 1
          FROM operations.software_decisions decision
         WHERE decision.tenant_id = exposure.tenant_id
           AND decision.device_id = exposure.device_id
           AND decision.decision IN ('approve', 'approve_publisher')
           AND ((decision.canonical_name <> ''
                 AND decision.canonical_name = exposure.canonical_name)
             OR (decision.publisher <> ''
                 AND decision.publisher = exposure.publisher))
   )
   AND NOT EXISTS (
        SELECT 1
          FROM operations.software_decisions decision
         WHERE decision.tenant_id = exposure.tenant_id
           AND decision.client_id = exposure.client_id
           AND decision.device_id IS NULL
           AND decision.decision IN ('approve', 'approve_publisher')
           AND ((decision.canonical_name <> ''
                 AND decision.canonical_name = exposure.canonical_name)
             OR (decision.publisher <> ''
                 AND decision.publisher = exposure.publisher))
   );

ALTER VIEW operations.v_device_software_exposure OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_device_software_exposure
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_device_software_exposure
    TO operations_app, operations_readonly, metabase_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_device_software_exposure
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

COMMENT ON MATERIALIZED VIEW operations.device_software_exposure_current IS
    'Rebuildable device/software exposure candidates with evidence and condition freshness deadlines. Refreshed after successful software classification; live freshness and operator approvals are intentionally excluded.';
COMMENT ON VIEW operations.v_device_software_exposure IS
    'Current device exposure eligibility with live evidence/condition freshness and client/device approval decisions applied.';
