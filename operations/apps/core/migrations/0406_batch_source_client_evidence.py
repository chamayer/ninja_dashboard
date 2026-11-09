"""Batch source-record client attribution for the Operations Home summary."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION operations.computer_client_independent_evidence_batch(
    p_tenant bigint, p_observations uuid[]
) RETURNS TABLE (observation_id uuid, client_id uuid)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_context_tenant bigint;
BEGIN
    v_context_tenant := nullif(current_setting('operations.tenant_id', true), '')::bigint;
    IF p_tenant IS NULL OR v_context_tenant IS DISTINCT FROM p_tenant THEN
        RAISE EXCEPTION 'computer_client_independent_evidence_batch: tenant context mismatch';
    END IF;

    RETURN QUERY
    WITH requested AS MATERIALIZED (
        SELECT DISTINCT requested.observation_id
          FROM unnest(coalesce(p_observations, ARRAY[]::uuid[])) requested(observation_id)
         WHERE requested.observation_id IS NOT NULL
    ), base AS MATERIALIZED (
        SELECT requested.observation_id, observation.source_instance_id,
               instance.client_id AS instance_client_id,
               CASE WHEN observation.entity_type = 'org'
                    THEN nullif(btrim(observation.external_id), '')
                    ELSE nullif(btrim(observation.canonical_data->>'platform_group_id'), '')
               END AS group_id,
               observation.entity_type, observation.external_namespace,
               observation.parent_external_namespace, observation.parent_external_id
          FROM requested
          LEFT JOIN operations.entity_observation_current observation
            ON observation.tenant_id = p_tenant
           AND observation.observation_id = requested.observation_id
          LEFT JOIN operations.source_instances instance
            ON instance.tenant_id = p_tenant
           AND instance.id = observation.source_instance_id
    ), groups_to_resolve AS MATERIALIZED (
        SELECT DISTINCT base.source_instance_id, base.group_id,
                        base.parent_external_namespace AS group_parent_external_namespace,
                        base.parent_external_id AS group_parent_external_id
          FROM base
         WHERE base.source_instance_id IS NOT NULL
           AND base.instance_client_id IS NULL AND base.group_id IS NOT NULL
           AND base.entity_type IS NOT NULL AND base.entity_type <> 'org'
    ), org_matches AS MATERIALIZED (
        SELECT groups.source_instance_id, groups.group_id,
               groups.group_parent_external_namespace, groups.group_parent_external_id,
               count(org.observation_id)::bigint AS org_count,
               (array_agg(org.external_id))[1] AS external_id,
               (array_agg(org.external_namespace))[1] AS external_namespace,
               (array_agg(org.parent_external_namespace))[1] AS parent_external_namespace,
               (array_agg(org.parent_external_id))[1] AS parent_external_id
          FROM groups_to_resolve groups
          LEFT JOIN operations.entity_observation_current org
            ON org.tenant_id = p_tenant
           AND org.source_instance_id = groups.source_instance_id
           AND org.entity_type = 'org' AND org.active
           AND (org.entity_key = groups.group_id OR org.external_id = groups.group_id)
           AND (groups.group_parent_external_id IS DISTINCT FROM groups.group_id
                OR coalesce(groups.group_parent_external_namespace, '') = ''
                OR org.external_namespace = groups.group_parent_external_namespace)
         GROUP BY groups.source_instance_id, groups.group_id,
                  groups.group_parent_external_namespace, groups.group_parent_external_id
    ), identities AS MATERIALIZED (
        SELECT base.observation_id, base.source_instance_id,
               CASE WHEN base.entity_type = 'org' OR base.entity_type IS NULL
                    THEN base.group_id ELSE org_matches.external_id END AS external_id,
               CASE WHEN base.entity_type = 'org' OR base.entity_type IS NULL
                    THEN base.external_namespace ELSE org_matches.external_namespace END
                    AS external_namespace,
               CASE WHEN base.entity_type = 'org' OR base.entity_type IS NULL
                    THEN base.parent_external_namespace
                    ELSE org_matches.parent_external_namespace END AS parent_external_namespace,
               CASE WHEN base.entity_type = 'org' OR base.entity_type IS NULL
                    THEN base.parent_external_id ELSE org_matches.parent_external_id END
                    AS parent_external_id
          FROM base
          LEFT JOIN org_matches
            ON org_matches.source_instance_id = base.source_instance_id
           AND org_matches.group_id = base.group_id
           AND org_matches.group_parent_external_namespace IS NOT DISTINCT FROM
               base.parent_external_namespace
           AND org_matches.group_parent_external_id IS NOT DISTINCT FROM base.parent_external_id
         WHERE base.source_instance_id IS NOT NULL
           AND base.instance_client_id IS NULL AND base.group_id IS NOT NULL
           AND (base.entity_type = 'org' OR base.entity_type IS NULL
                OR org_matches.org_count = 1)
    ), unique_identities AS MATERIALIZED (
        SELECT DISTINCT source_instance_id, external_id, external_namespace,
                        parent_external_namespace, parent_external_id
          FROM identities
    ), links AS MATERIALIZED (
        SELECT identity.source_instance_id, identity.external_id,
               identity.external_namespace, identity.parent_external_namespace,
               identity.parent_external_id, link.id AS link_id, link.entity_id AS client_id
          FROM unique_identities identity
          JOIN operations.entity_source_links link
            ON link.tenant_id = p_tenant
           AND link.source_instance_id = identity.source_instance_id
           AND link.entity_class_id = 'client'
           AND link.external_id = identity.external_id
           AND link.external_namespace = identity.external_namespace
           AND link.parent_external_namespace = identity.parent_external_namespace
           AND link.parent_external_id = identity.parent_external_id
           AND link.missing_since IS NULL
          JOIN operations.clients client
            ON client.tenant_id = link.tenant_id AND client.id = link.entity_id
           AND client.deleted_at IS NULL
    ), link_decisions AS MATERIALIZED (
        SELECT link.*,
               coalesce(proof.operator_proved, false) AS operator_proved,
               coalesce(proof.automatic_candidate, false) AS automatic_candidate
          FROM links link
          LEFT JOIN LATERAL (
              SELECT bool_or(
                         decision.state = 'explicit' AND decision.provenance = 'operator'
                         AND decision.decided_at >= history.effective_from
                     ) AS operator_proved,
                     bool_or(
                         decision.state IN ('automatic', 'explicit')
                         AND decision.provenance IN ('resolver', 'legacy_alias')
                     ) AS automatic_candidate
                FROM operations.client_source_mapping_decisions decision
                JOIN operations.entity_source_link_history history
                  ON history.tenant_id = p_tenant
                 AND history.source_instance_id = link.source_instance_id
                 AND history.external_namespace = link.external_namespace
                 AND history.parent_external_namespace = link.parent_external_namespace
                 AND history.parent_external_id = link.parent_external_id
                 AND history.external_id = link.external_id
                 AND history.entity_class_id = 'client'
                 AND history.entity_id = link.client_id
                 AND history.effective_to IS NULL
               WHERE decision.tenant_id = p_tenant
                 AND decision.source_link_id = link.link_id
                 AND decision.superseded_at IS NULL
          ) proof ON true
    ), link_proof AS MATERIALIZED (
        SELECT link.source_instance_id, link.external_id, link.external_namespace,
               link.parent_external_namespace, link.parent_external_id,
               link.link_id, link.client_id,
               CASE WHEN link.operator_proved THEN true
                    WHEN link.automatic_candidate
                    THEN operations.computer_client_group_name_proved(p_tenant, link.link_id)
                    ELSE false END AS proved
          FROM link_decisions link
    ), identity_summary AS MATERIALIZED (
        SELECT identity.source_instance_id, identity.external_id,
               identity.external_namespace, identity.parent_external_namespace,
               identity.parent_external_id, count(link.link_id)::integer AS link_count,
               (array_agg(link.client_id) FILTER (WHERE link.client_id IS NOT NULL))[1]
                    AS client_id,
               bool_and(link.proved) FILTER (WHERE link.client_id IS NOT NULL) AS all_proved
          FROM unique_identities identity
          LEFT JOIN link_proof link
            ON link.source_instance_id = identity.source_instance_id
           AND link.external_id = identity.external_id
           AND link.external_namespace = identity.external_namespace
           AND link.parent_external_namespace = identity.parent_external_namespace
           AND link.parent_external_id = identity.parent_external_id
         GROUP BY identity.source_instance_id, identity.external_id,
                  identity.external_namespace, identity.parent_external_namespace,
                  identity.parent_external_id
    ), resolved_groups AS MATERIALIZED (
        SELECT identity.observation_id, summary.client_id
          FROM identities identity
          JOIN identity_summary summary
            ON summary.source_instance_id = identity.source_instance_id
           AND summary.external_id = identity.external_id
           AND summary.external_namespace = identity.external_namespace
           AND summary.parent_external_namespace = identity.parent_external_namespace
           AND summary.parent_external_id = identity.parent_external_id
         WHERE summary.link_count = 1 AND summary.all_proved
    )
    SELECT base.observation_id,
           CASE WHEN base.instance_client_id IS NOT NULL THEN live_client.id
                ELSE resolved_groups.client_id END AS client_id
      FROM base
      LEFT JOIN operations.clients live_client
        ON live_client.tenant_id = p_tenant
       AND live_client.id = base.instance_client_id AND live_client.deleted_at IS NULL
      LEFT JOIN resolved_groups
        ON resolved_groups.observation_id = base.observation_id;
END
$fn$;

ALTER FUNCTION operations.computer_client_independent_evidence_batch(bigint, uuid[])
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.computer_client_independent_evidence_batch(bigint, uuid[])
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.computer_client_independent_evidence_batch(bigint, uuid[])
    TO operations_app;
"""

REVERSE_SQL = r"""
DROP FUNCTION operations.computer_client_independent_evidence_batch(bigint, uuid[]);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0405_jobs_claim_successor_guard"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
