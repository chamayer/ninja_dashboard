from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
DO $block$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_view_owner') THEN
        CREATE ROLE operations_view_owner NOLOGIN NOBYPASSRLS;
    END IF;
END
$block$;

GRANT USAGE, CREATE ON SCHEMA operations TO operations_view_owner;
GRANT EXECUTE ON FUNCTION operations.current_tenant_id() TO operations_view_owner;
GRANT SELECT ON
    operations.entities,
    operations.entity_classes,
    operations.entity_types,
    operations.clients,
    operations.devices,
    operations.entity_source_links,
    operations.source_instances,
    operations.sources,
    operations.entity_observation_current,
    operations.entity_attribute_withheld_current,
    operations.entity_attribute_effective_current,
    operations.entity_attribute_conflict_current,
    operations.attribute_definitions,
    operations.entity_relationships,
    operations.entity_relationship_evidence_support,
    operations.relationship_types,
    operations.entity_candidates,
    operations.entity_candidate_events,
    operations.source_health_current
TO operations_view_owner;

CREATE OR REPLACE VIEW operations.v_entity_admin_summary
WITH (security_barrier = true) AS
WITH source_counts AS (
    SELECT tenant_id, entity_id,
           COUNT(*)::integer AS source_count,
           COUNT(*) FILTER (WHERE missing_since IS NULL)::integer AS active_source_count,
           COUNT(*) FILTER (WHERE missing_since IS NOT NULL)::integer AS missing_source_count
      FROM operations.entity_source_links
     WHERE tenant_id = operations.current_tenant_id()
     GROUP BY tenant_id, entity_id
), effective_counts AS (
    SELECT tenant_id, entity_id,
           COUNT(*)::integer AS effective_attribute_count
      FROM operations.entity_attribute_effective_current
     WHERE tenant_id = operations.current_tenant_id()
     GROUP BY tenant_id, entity_id
), conflict_counts AS (
    SELECT tenant_id, entity_id, COUNT(*)::integer AS conflict_count
      FROM operations.entity_attribute_conflict_current
     WHERE tenant_id = operations.current_tenant_id()
     GROUP BY tenant_id, entity_id
), relationship_counts AS (
    SELECT tenant_id, entity_id,
           SUM(outgoing_count)::integer AS outgoing_relationship_count,
           SUM(incoming_count)::integer AS incoming_relationship_count
      FROM (
          SELECT tenant_id, source_entity_id AS entity_id,
                 COUNT(*)::integer AS outgoing_count, 0::integer AS incoming_count
            FROM operations.entity_relationships
           WHERE tenant_id = operations.current_tenant_id() AND status = 'active'
           GROUP BY tenant_id, source_entity_id
          UNION ALL
          SELECT tenant_id, target_entity_id AS entity_id,
                 0::integer AS outgoing_count, COUNT(*)::integer AS incoming_count
            FROM operations.entity_relationships
           WHERE tenant_id = operations.current_tenant_id() AND status = 'active'
           GROUP BY tenant_id, target_entity_id
      ) counts
     GROUP BY tenant_id, entity_id
)
SELECT entity.id, entity.tenant_id,
       entity.entity_class_id AS entity_class,
       entity_class.display_name AS entity_class_display,
       entity.scope_kind, entity.client_id,
       owner_client.display_name AS client_display_name,
       COALESCE(NULLIF(device.canonical_hostname, ''),
                NULLIF(client_record.display_name, ''),
                entity_class.display_name || ' entity') AS display_label,
       entity.retired_at, entity.deleted_at, entity.updated_at,
       COALESCE(source_counts.source_count, 0) AS source_count,
       COALESCE(source_counts.active_source_count, 0) AS active_source_count,
       COALESCE(source_counts.missing_source_count, 0) AS missing_source_count,
       COALESCE(effective_counts.effective_attribute_count, 0)
           AS effective_attribute_count,
       COALESCE(conflict_counts.conflict_count, 0) AS conflict_count,
       COALESCE(relationship_counts.outgoing_relationship_count, 0)
           AS outgoing_relationship_count,
       COALESCE(relationship_counts.incoming_relationship_count, 0)
           AS incoming_relationship_count
  FROM operations.entities entity
  JOIN operations.entity_classes entity_class
    ON entity_class.name = entity.entity_class_id
  LEFT JOIN operations.clients owner_client ON owner_client.id = entity.client_id
  LEFT JOIN operations.clients client_record ON client_record.entity_id = entity.id
  LEFT JOIN operations.devices device ON device.entity_id = entity.id
  LEFT JOIN source_counts
    ON source_counts.tenant_id = entity.tenant_id
   AND source_counts.entity_id = entity.id
  LEFT JOIN effective_counts
    ON effective_counts.tenant_id = entity.tenant_id
   AND effective_counts.entity_id = entity.id
  LEFT JOIN conflict_counts
    ON conflict_counts.tenant_id = entity.tenant_id
   AND conflict_counts.entity_id = entity.id
  LEFT JOIN relationship_counts
    ON relationship_counts.tenant_id = entity.tenant_id
   AND relationship_counts.entity_id = entity.id
 WHERE entity.tenant_id = operations.current_tenant_id();

CREATE OR REPLACE VIEW operations.v_entity_source_evidence
WITH (security_barrier = true) AS
SELECT link.id, link.tenant_id, link.entity_id,
       link.source_instance_id, source.name AS source_name,
       link.external_namespace, link.parent_external_namespace,
       link.parent_external_id, link.external_id,
       link.match_method, link.match_confidence,
       link.first_seen_at, link.last_seen_at, link.missing_since,
       observation.observation_id, observation.entity_type,
       observation.active AS observation_active,
       observation.observed_at, observation.last_seen_at AS observation_last_seen_at,
       COALESCE(withheld.unmapped_field_count, 0) AS unmapped_field_count,
       COALESCE(withheld.restricted_field_count, 0) AS restricted_field_count,
       COALESCE(withheld.invalid_field_count, 0) AS invalid_field_count
  FROM operations.entity_source_links link
  JOIN operations.source_instances source_instance
    ON source_instance.tenant_id = link.tenant_id
   AND source_instance.id = link.source_instance_id
  JOIN operations.sources source ON source.id = source_instance.source_id
  LEFT JOIN operations.entity_observation_current observation
    ON observation.tenant_id = link.tenant_id
   AND observation.source_instance_id = link.source_instance_id
   AND observation.external_namespace = link.external_namespace
   AND observation.parent_external_namespace = link.parent_external_namespace
   AND observation.parent_external_id = link.parent_external_id
   AND observation.external_id = link.external_id
  LEFT JOIN operations.entity_attribute_withheld_current withheld
    ON withheld.tenant_id = observation.tenant_id
   AND withheld.observation_id = observation.observation_id
 WHERE link.tenant_id = operations.current_tenant_id();

CREATE OR REPLACE VIEW operations.v_entity_attribute_conflict_admin
WITH (security_barrier = true) AS
SELECT conflict.id, conflict.tenant_id, conflict.entity_id,
       conflict.entity_class_id AS entity_class,
       definition.key AS attribute_key,
       definition.display_name AS attribute_display_name,
       definition.sensitivity, conflict.conflict_kind,
       conflict.conflicting_value_count,
       conflict.first_detected_at, conflict.last_detected_at
  FROM operations.entity_attribute_conflict_current conflict
  JOIN operations.attribute_definitions definition
    ON definition.id = conflict.attribute_definition_id
 WHERE conflict.tenant_id = operations.current_tenant_id();

CREATE OR REPLACE VIEW operations.v_entity_relationship_admin
WITH (security_barrier = true) AS
SELECT relationship.id, relationship.tenant_id,
       relationship.relationship_type_id,
       relationship_type.display_name AS relationship_display_name,
       relationship.source_entity_id, relationship.target_entity_id,
       relationship.status, relationship.selection_reason,
       relationship.projected_at,
       COUNT(support.id)::integer AS supporting_evidence_count
  FROM operations.entity_relationships relationship
  JOIN operations.relationship_types relationship_type
    ON relationship_type.key = relationship.relationship_type_id
  LEFT JOIN operations.entity_relationship_evidence_support support
    ON support.tenant_id = relationship.tenant_id
   AND support.relationship_id = relationship.id
 WHERE relationship.tenant_id = operations.current_tenant_id()
 GROUP BY relationship.id, relationship.tenant_id,
          relationship.relationship_type_id, relationship_type.display_name,
          relationship.source_entity_id, relationship.target_entity_id,
          relationship.status, relationship.selection_reason,
          relationship.projected_at;

CREATE OR REPLACE VIEW operations.v_entity_candidate_admin
WITH (security_barrier = true) AS
SELECT candidate.id, candidate.tenant_id,
       candidate.proposed_entity_class_id AS entity_class,
       entity_class.display_name AS entity_class_display,
       candidate.client_id, client.display_name AS client_display_name,
       candidate.source_instance_id, source.name AS source_name,
       candidate.external_namespace, candidate.parent_external_namespace,
       candidate.parent_external_id, candidate.external_id,
       candidate.status, candidate.confidence,
       candidate.latest_decision, candidate.latest_decision_reason,
       candidate.first_observed_at, candidate.last_observed_at,
       candidate.resolved_entity_id,
       COUNT(event.id)::integer AS event_count
  FROM operations.entity_candidates candidate
  JOIN operations.entity_classes entity_class
    ON entity_class.name = candidate.proposed_entity_class_id
  JOIN operations.source_instances source_instance
    ON source_instance.tenant_id = candidate.tenant_id
   AND source_instance.id = candidate.source_instance_id
  JOIN operations.sources source ON source.id = source_instance.source_id
  LEFT JOIN operations.clients client ON client.id = candidate.client_id
  LEFT JOIN operations.entity_candidate_events event
    ON event.tenant_id = candidate.tenant_id
   AND event.candidate_id = candidate.id
 WHERE candidate.tenant_id = operations.current_tenant_id()
 GROUP BY candidate.id, candidate.tenant_id,
          candidate.proposed_entity_class_id, entity_class.display_name,
          candidate.client_id, client.display_name,
          candidate.source_instance_id, source.name,
          candidate.external_namespace, candidate.parent_external_namespace,
          candidate.parent_external_id, candidate.external_id,
          candidate.status, candidate.confidence,
          candidate.latest_decision, candidate.latest_decision_reason,
          candidate.first_observed_at, candidate.last_observed_at,
          candidate.resolved_entity_id;

CREATE OR REPLACE VIEW operations.v_source_instance_entity_counts
WITH (security_barrier = true) AS
SELECT observation.tenant_id, observation.source_instance_id,
       observation.entity_type,
       entity_type.entity_class_id AS entity_class,
       COUNT(*)::bigint AS current_count,
       COUNT(*) FILTER (WHERE observation.active)::bigint AS active_count,
       COUNT(*) FILTER (WHERE NOT observation.active)::bigint AS withdrawn_count,
       MAX(observation.last_seen_at) AS last_seen_at
  FROM operations.entity_observation_current observation
  JOIN operations.entity_types entity_type
    ON entity_type.name = observation.entity_type
 WHERE observation.tenant_id = operations.current_tenant_id()
 GROUP BY observation.tenant_id, observation.source_instance_id,
          observation.entity_type, entity_type.entity_class_id;

CREATE OR REPLACE VIEW operations.v_source_instance_health
WITH (security_barrier = true) AS
WITH observation_health AS (
    SELECT tenant_id, source_instance_id,
           MAX(last_seen_at) AS last_observed_at,
           COUNT(*)::bigint AS current_record_count,
           COUNT(*) FILTER (WHERE active)::bigint AS active_record_count
      FROM operations.entity_observation_current
     WHERE tenant_id = operations.current_tenant_id()
     GROUP BY tenant_id, source_instance_id
)
SELECT source_instance.id, source_instance.tenant_id,
       source_instance.source_id, source.name AS source_name,
       source_instance.client_id, client.display_name AS client_display_name,
       source_instance.enabled,
       COALESCE(NULLIF(source_instance.config->>'platform', ''), source.name)
           AS run_platform,
       observation_health.last_observed_at,
       COALESCE(observation_health.current_record_count, 0) AS current_record_count,
       COALESCE(observation_health.active_record_count, 0) AS active_record_count,
       source_health.last_run_ok, source_health.last_run_ended_at,
       source_health.last_run_rows, source_health.last_run_error,
       source_health.last_success_at, source_health.last_success_rows
  FROM operations.source_instances source_instance
  JOIN operations.sources source ON source.id = source_instance.source_id
  LEFT JOIN operations.clients client ON client.id = source_instance.client_id
  LEFT JOIN observation_health
    ON observation_health.tenant_id = source_instance.tenant_id
   AND observation_health.source_instance_id = source_instance.id
  LEFT JOIN operations.source_health_current source_health
    ON source_health.tenant_id = source_instance.tenant_id
   AND source_health.platform =
       COALESCE(NULLIF(source_instance.config->>'platform', ''), source.name)
 WHERE source_instance.tenant_id = operations.current_tenant_id();

ALTER VIEW operations.v_entity_admin_summary OWNER TO operations_view_owner;
ALTER VIEW operations.v_entity_source_evidence OWNER TO operations_view_owner;
ALTER VIEW operations.v_entity_attribute_conflict_admin OWNER TO operations_view_owner;
ALTER VIEW operations.v_entity_relationship_admin OWNER TO operations_view_owner;
ALTER VIEW operations.v_entity_candidate_admin OWNER TO operations_view_owner;
ALTER VIEW operations.v_source_instance_entity_counts OWNER TO operations_view_owner;
ALTER VIEW operations.v_source_instance_health OWNER TO operations_view_owner;
REVOKE CREATE ON SCHEMA operations FROM operations_view_owner;

REVOKE ALL ON operations.v_entity_admin_summary,
    operations.v_entity_source_evidence,
    operations.v_entity_attribute_conflict_admin,
    operations.v_entity_relationship_admin,
    operations.v_entity_candidate_admin,
    operations.v_source_instance_entity_counts,
    operations.v_source_instance_health
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_entity_admin_summary,
    operations.v_entity_source_evidence,
    operations.v_entity_attribute_conflict_admin,
    operations.v_entity_relationship_admin,
    operations.v_entity_candidate_admin,
    operations.v_source_instance_entity_counts,
    operations.v_source_instance_health
TO operations_app, operations_readonly;
"""


REVERSE_SQL = r"""
DROP VIEW IF EXISTS operations.v_source_instance_health;
DROP VIEW IF EXISTS operations.v_source_instance_entity_counts;
DROP VIEW IF EXISTS operations.v_entity_candidate_admin;
DROP VIEW IF EXISTS operations.v_entity_relationship_admin;
DROP VIEW IF EXISTS operations.v_entity_attribute_conflict_admin;
DROP VIEW IF EXISTS operations.v_entity_source_evidence;
DROP VIEW IF EXISTS operations.v_entity_admin_summary;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0115_restrict_e4_runtime_privileges"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
