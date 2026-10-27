-- Aggregate verification of linked candidates that are not attached.
-- No candidate/source/customer identifiers or values are returned.
WITH linked AS (
    SELECT candidate.id, candidate.status, candidate.material_hash,
           candidate.last_observed_at, observation.active,
           observation.last_seen_at,
           observation.material_hash AS observation_material_hash,
           link.entity_class_id = candidate.proposed_entity_class_id AS class_matches
      FROM operations.entity_candidates candidate
      JOIN operations.entity_source_links link
        ON link.tenant_id = candidate.tenant_id
       AND link.source_instance_id = candidate.source_instance_id
       AND link.external_namespace = candidate.external_namespace
       AND link.parent_external_namespace = candidate.parent_external_namespace
       AND link.parent_external_id = candidate.parent_external_id
       AND link.external_id = candidate.external_id
      LEFT JOIN operations.entity_types entity_type
        ON entity_type.entity_class_id = candidate.proposed_entity_class_id
      LEFT JOIN operations.entity_observation_current observation
        ON observation.tenant_id = candidate.tenant_id
       AND observation.source_instance_id = candidate.source_instance_id
       AND observation.external_namespace = candidate.external_namespace
       AND observation.parent_external_namespace = candidate.parent_external_namespace
       AND observation.parent_external_id = candidate.parent_external_id
       AND observation.external_id = candidate.external_id
       AND observation.entity_type = entity_type.name
     WHERE candidate.status <> 'attached'
), grouped AS (
    SELECT status,
           CASE WHEN active IS TRUE THEN 'active'
                WHEN active IS FALSE THEN 'inactive'
                ELSE 'no_current_observation' END AS observation_state,
           class_matches,
           COUNT(DISTINCT id)::bigint AS candidates,
           COUNT(DISTINCT id) FILTER (
               WHERE active IS TRUE AND material_hash IS DISTINCT FROM observation_material_hash
           )::bigint AS active_hash_diff,
           COUNT(DISTINCT id) FILTER (
               WHERE active IS TRUE AND material_hash IS NOT DISTINCT FROM observation_material_hash
           )::bigint AS active_hash_same,
           COUNT(DISTINCT id) FILTER (
               WHERE active IS TRUE AND last_seen_at > last_observed_at
           )::bigint AS observation_newer_than_candidate,
           COUNT(DISTINCT id) FILTER (
               WHERE active IS TRUE AND last_seen_at <= last_observed_at
           )::bigint AS candidate_at_least_as_fresh
      FROM linked
     GROUP BY status, observation_state, class_matches
)
SELECT status, observation_state, class_matches, candidates,
       active_hash_diff, active_hash_same,
       observation_newer_than_candidate, candidate_at_least_as_fresh
  FROM grouped
 ORDER BY status, observation_state, class_matches;
