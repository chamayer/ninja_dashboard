-- 107: make the source evidence behind a software installation explicit.
--
-- `software_installation_history` is the existing per-source SCD-2 evidence
-- store.  `software_installations_current` is the compact current projection
-- used by inventory readers.  The latter intentionally has one row per
-- Computer/title and therefore cannot decide whether a source still supports
-- that row.  This view supplies that missing evidence-state boundary without
-- replacing or deleting either record.
--
-- A source may report a Computer offline while still providing current
-- software evidence.  That is distinct from stale evidence (the software
-- inventory has not refreshed within the configured age) and withdrawn
-- evidence (the source no longer has a current record for the Computer).
-- The freshness threshold is operator-managed evaluator configuration, not a
-- source-name rule in code.  Twenty-four hours is a conservative bootstrap
-- default until an administrator changes it. The existing Classifier
-- configuration screen creates the optional evaluator_config row on first
-- save; this migration does not manufacture an operator-authored row.

CREATE OR REPLACE VIEW operations.v_software_installation_evidence_current
WITH (security_barrier = true) AS
WITH policy AS (
    SELECT GREATEST(
               COALESCE(
                   MAX(NULLIF(config->>'installation_evidence_max_age_hours', '')::integer),
                   24
               ),
               1
           ) AS max_age_hours
      FROM operations.evaluator_config
     WHERE tenant_id = operations.current_tenant_id()
       AND evaluator_name = 'software_classifier'
)
SELECT history.id AS evidence_id,
       history.tenant_id,
       history.source_binding_id,
       source_instance.id AS source_instance_id,
       source.name AS source_name,
       history.client_id,
       history.device_id,
       history.canonical_name,
       history.publisher,
       history.version,
       history.install_location,
       history.install_date,
       history.last_seen_at,
       history.received_at,
       observation.observation_id AS supporting_observation_id,
       observation.reported_online,
       CASE
           WHEN observation.observation_id IS NULL
             OR COALESCE(lifecycle.counts_as_current_computer_evidence, FALSE) = FALSE
               THEN 'withdrawn'
           WHEN history.last_seen_at < NOW() - make_interval(hours => policy.max_age_hours)
               THEN 'stale'
           WHEN observation.reported_online IS FALSE THEN 'offline'
           ELSE 'current'
       END AS evidence_state
  FROM operations.software_installation_history history
  JOIN operations.source_bindings binding
    ON binding.tenant_id = history.tenant_id
   AND binding.id = history.source_binding_id
  JOIN operations.source_instances source_instance
    ON source_instance.tenant_id = binding.tenant_id
   AND source_instance.id = binding.source_instance_id
  JOIN operations.sources source ON source.id = source_instance.source_id
 CROSS JOIN policy
  LEFT JOIN LATERAL (
      SELECT current_observation.observation_id,
             presence.reported_online
        FROM operations.v_device_observation_current current_observation
        LEFT JOIN operations.device_agent_presence_current presence
          ON presence.tenant_id = current_observation.tenant_id
         AND presence.device_id = current_observation.device_id
         AND presence.platform = current_observation.source_name
         AND presence.entity_type = current_observation.entity_type
       WHERE current_observation.tenant_id = history.tenant_id
         AND current_observation.device_id = history.device_id
         AND current_observation.source_instance_id = source_instance.id
         AND current_observation.observation_active
       ORDER BY current_observation.observation_last_seen_at DESC NULLS LAST,
                current_observation.observation_id
       LIMIT 1
  ) observation ON TRUE
  LEFT JOIN operations.v_device_source_record_lifecycle_current lifecycle
    ON lifecycle.observation_id = observation.observation_id
 WHERE history.tenant_id = operations.current_tenant_id()
   AND history.active
   AND history.effective_to IS NULL;

ALTER VIEW operations.v_software_installation_evidence_current
    OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_software_installation_evidence_current
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_software_installation_evidence_current
TO operations_app, operations_readonly, ninja_ingest;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_software_installation_evidence_current
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

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
REVOKE ALL ON operations.v_device_software_exposure
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_device_software_exposure
TO operations_app, operations_readonly, metabase_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_device_software_exposure
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

COMMENT ON VIEW operations.v_software_installation_evidence_current IS
    'Current source-specific software-installation evidence with current, offline, stale, or withdrawn state.';
COMMENT ON VIEW operations.v_device_software_exposure IS
    'Current device exposure to an open software finding, supported by current or offline source installation evidence only.';
