-- 113: one effective software decision, applied live at every scope.
--
-- An operator decision is keyed by title or publisher and scoped to a device,
-- a client, or the whole tenant. The classifier resolved it in Python (title
-- before publisher; device before client before global) while the exposure
-- view applied only device and client approvals, compared names case-sensitively
-- and hid every finding type on an approved title. All 418 production
-- decisions are global, so approvals reached exposure only through a classifier
-- run.
--
-- `v_software_decision_keys` is the single resolution input: one current
-- decision per (match kind, scope, device, client, lower-cased key). Callers
-- resolve precedence with six equality joins, which the planner can hash; a
-- per-row lateral lookup over all installations took longer than 55 seconds,
-- the joins take about 10.
--
-- The public exposure view keeps its columns. An approval now hides an exposure
-- only for finding types the registry marks `suppressed_by_approval`: approving
-- a title cannot make a vulnerability or an end-of-life date untrue (design D3).

CREATE OR REPLACE VIEW operations.v_software_decision_keys
WITH (security_barrier = true) AS
SELECT DISTINCT ON (tenant_id, match_kind, scope, device_id, client_id, match_key)
       tenant_id,
       match_kind,
       scope,
       device_id,
       client_id,
       match_key,
       decision,
       decided_at
  FROM (
      SELECT decision.tenant_id,
             CASE WHEN decision.canonical_name <> '' THEN 'title' ELSE 'publisher' END
                 AS match_kind,
             CASE
                 WHEN decision.device_id IS NOT NULL THEN 'device'
                 WHEN decision.client_id IS NOT NULL THEN 'client'
                 ELSE 'global'
             END AS scope,
             decision.device_id,
             CASE WHEN decision.device_id IS NULL THEN decision.client_id END AS client_id,
             lower(
                 CASE
                     WHEN decision.canonical_name <> '' THEN decision.canonical_name
                     ELSE decision.publisher
                 END
             ) AS match_key,
             decision.decision,
             decision.decided_at
        FROM operations.software_decisions decision
       WHERE decision.canonical_name <> '' OR decision.publisher <> ''
  ) candidate
 ORDER BY tenant_id, match_kind, scope, device_id, client_id, match_key, decided_at DESC;

ALTER VIEW operations.v_software_decision_keys OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_software_decision_keys
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_software_decision_keys
    TO operations_app, ninja_ingest, operations_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_software_decision_keys
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON TABLE operations.finding_types TO operations_view_owner;

COMMENT ON VIEW operations.v_software_decision_keys IS
    'Current software decision per match kind (title/publisher), scope (device/client/global) and lower-cased key. Resolve precedence: title before publisher; device before client before global.';

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
