-- 114: exposure eligibility from per-device readiness (design D1, D4).
--
-- Migration 112 derived exposure from a stored assessment per (finding, device).
-- The rebuilt software classifier no longer writes those rows: a title-level
-- finding carries one aggregate assessment (executable only while at least one
-- exposed device is ready), and each device's readiness for a finding type is
-- held once in operations.software_device_readiness.
--
-- An exposure row requires the finding's aggregate assessment to permit
-- execution (definition active, handling not suppressed or snoozed) and the
-- device to be ready for that finding type under the same active policy. Its
-- condition deadline is the older of the two assessments plus the policy's
-- freshness window; the public view still enforces both deadlines live.
--
-- Evaluation is staged with MATERIALIZED steps and source evidence is computed
-- only for the candidate (device, title) pairs: the planner misjudged the
-- fleet-wide evidence join by two orders of magnitude and the single-statement
-- form did not finish within 300 seconds. Columns, indexes, privileges and the
-- public view (approvals from migration 113) are unchanged.

DROP MATERIALIZED VIEW IF EXISTS operations.device_software_exposure_current CASCADE;

CREATE MATERIALIZED VIEW operations.device_software_exposure_current AS
WITH evidence_policy AS MATERIALIZED (
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
software_findings AS MATERIALIZED (
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
exposed_versions AS MATERIALIZED (
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
),
authorized AS MATERIALIZED (
    SELECT exposed.*,
           aggregate.assessed_at AS aggregate_assessed_at,
           (policy.policy->>'freshness_hours')::integer AS freshness_hours,
           policy.version AS policy_version
      FROM exposed_versions exposed
      JOIN operations.condition_assessments aggregate
        ON aggregate.tenant_id = exposed.tenant_id
       AND aggregate.row_kind = 'entity'
       AND aggregate.finding_id = exposed.finding_id
       AND aggregate.participant_kind = 'condition'
       AND (aggregate.response->>'may_execute')::boolean IS TRUE
      JOIN operations.condition_policy_versions policy
        ON policy.version = aggregate.policy_version
       AND policy.active
),
candidates AS MATERIALIZED (
    SELECT authorized.*,
           installation.device_id,
           installation.client_id,
           installation.canonical_name,
           installation.publisher,
           installation.install_location,
           installation.install_date,
           LEAST(readiness.assessed_at, authorized.aggregate_assessed_at)
               + make_interval(hours => authorized.freshness_hours) AS condition_fresh_until
      FROM authorized
      JOIN operations.software_installations_current installation
        ON installation.tenant_id = authorized.tenant_id
       AND installation.software_version_id = authorized.software_version_id
       AND installation.stale_since IS NULL
       AND installation.deleted_at IS NULL
      JOIN operations.software_device_readiness readiness
        ON readiness.tenant_id = installation.tenant_id
       AND readiness.device_id = installation.device_id
       AND readiness.finding_type_id = authorized.finding_type_id
       AND readiness.policy_version = authorized.policy_version
       AND readiness.may_execute
),
current_installation_evidence AS MATERIALIZED (
    SELECT history.tenant_id,
           history.device_id,
           history.canonical_name,
           MAX(
               history.last_seen_at + make_interval(hours => policy.max_age_hours)
           ) AS evidence_fresh_until
      FROM (SELECT DISTINCT tenant_id, device_id, canonical_name FROM candidates) pair
      JOIN operations.software_installation_history history
        ON history.tenant_id = pair.tenant_id
       AND history.device_id = pair.device_id
       AND history.canonical_name = pair.canonical_name
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
)
SELECT candidates.finding_id,
       candidates.tenant_id,
       candidates.finding_type_id,
       candidates.finding_type,
       candidates.subject_type,
       candidates.subject_id,
       candidates.severity,
       candidates.status,
       candidates.first_seen_at,
       candidates.last_seen_at,
       candidates.finding_details,
       candidates.device_id,
       candidates.client_id,
       candidates.canonical_name,
       candidates.publisher,
       candidates.install_location,
       candidates.install_date,
       version.version,
       evidence.evidence_fresh_until,
       candidates.condition_fresh_until,
       now() AS computed_at
  FROM candidates
  JOIN catalog.software_versions version ON version.id = candidates.software_version_id
  JOIN current_installation_evidence evidence
    ON evidence.tenant_id = candidates.tenant_id
   AND evidence.device_id = candidates.device_id
   AND evidence.canonical_name = candidates.canonical_name;

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
  JOIN operations.finding_types finding_type
    ON finding_type.id = exposure.finding_type_id
  LEFT JOIN operations.v_software_decision_keys title_device
    ON title_device.tenant_id = exposure.tenant_id
   AND title_device.match_kind = 'title' AND title_device.scope = 'device'
   AND title_device.device_id = exposure.device_id
   AND title_device.match_key = lower(exposure.canonical_name)
  LEFT JOIN operations.v_software_decision_keys title_client
    ON title_client.tenant_id = exposure.tenant_id
   AND title_client.match_kind = 'title' AND title_client.scope = 'client'
   AND title_client.client_id = exposure.client_id
   AND title_client.match_key = lower(exposure.canonical_name)
  LEFT JOIN operations.v_software_decision_keys title_global
    ON title_global.tenant_id = exposure.tenant_id
   AND title_global.match_kind = 'title' AND title_global.scope = 'global'
   AND title_global.match_key = lower(exposure.canonical_name)
  LEFT JOIN operations.v_software_decision_keys publisher_device
    ON publisher_device.tenant_id = exposure.tenant_id
   AND publisher_device.match_kind = 'publisher' AND publisher_device.scope = 'device'
   AND publisher_device.device_id = exposure.device_id
   AND publisher_device.match_key = lower(exposure.publisher)
  LEFT JOIN operations.v_software_decision_keys publisher_client
    ON publisher_client.tenant_id = exposure.tenant_id
   AND publisher_client.match_kind = 'publisher' AND publisher_client.scope = 'client'
   AND publisher_client.client_id = exposure.client_id
   AND publisher_client.match_key = lower(exposure.publisher)
  LEFT JOIN operations.v_software_decision_keys publisher_global
    ON publisher_global.tenant_id = exposure.tenant_id
   AND publisher_global.match_kind = 'publisher' AND publisher_global.scope = 'global'
   AND publisher_global.match_key = lower(exposure.publisher)
 WHERE exposure.tenant_id = operations.current_tenant_id()
   AND exposure.evidence_fresh_until >= now()
   AND exposure.condition_fresh_until >= now()
   AND NOT (
       finding_type.suppressed_by_approval
       AND COALESCE(
           title_device.decision, title_client.decision, title_global.decision,
           publisher_device.decision, publisher_client.decision, publisher_global.decision
       ) IN ('approve', 'approve_publisher')
   );

ALTER VIEW operations.v_device_software_exposure OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_device_software_exposure
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_device_software_exposure
    TO operations_app, operations_readonly, metabase_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_device_software_exposure
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

COMMENT ON VIEW operations.v_device_software_exposure IS
    'Current device exposure eligibility with live evidence/condition freshness. The effective software decision (title before publisher; device before client before global) hides an exposure only for finding types marked suppressed_by_approval.';

COMMENT ON MATERIALIZED VIEW operations.device_software_exposure_current IS
    'Rebuildable device/software exposure candidates: finding aggregate assessment plus per-device readiness, with evidence and condition freshness deadlines. Refreshed after each software reconcile; live freshness and operator approvals are intentionally excluded.';
