"""Project Computer ownership under the PLAN-045 invalidation lock.

The reader transition, operator decision writer and full-cycle integration
must accompany this unfinished migration before deployment.
"""

import importlib
from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
-- Association history uses clock_timestamp(); decision timestamps must use the
-- same clock so a decision made later in one transaction follows its link.
ALTER TABLE operations.client_source_mapping_decisions
    ALTER COLUMN decided_at SET DEFAULT clock_timestamp();

INSERT INTO operations.operator_decision_dimensions
    (name, entity_type, value_type, allowed_values, description, enabled)
VALUES ('client_ownership_choice', 'device', 'json', NULL,
        'Explicit Computer client choice, including the selected client and decision evidence.', true)
ON CONFLICT (name) DO NOTHING;

CREATE FUNCTION operations.computer_client_conflict_decisions(p_tenant bigint)
RETURNS TABLE (device_id uuid, dimension text, value jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
BEGIN
    IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'computer_client_conflict_decisions: tenant context mismatch';
    END IF;
    RETURN QUERY
        SELECT d.device_id, d.dimension::text, d.value
          FROM operations.device_operator_decisions d
         WHERE d.tenant_id = p_tenant
           AND d.dimension IN ('client_conflict_accepted', 'client_ownership_choice');
END
$fn$;
REVOKE ALL ON FUNCTION operations.computer_client_conflict_decisions(bigint)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.computer_client_conflict_decisions(bigint) TO ninja_ingest;

-- A source-group name can independently corroborate an automatic mapping when
-- it identifies exactly one live client by its current name or a trusted alias.
CREATE FUNCTION operations.computer_client_group_name_proved(p_tenant bigint, p_link uuid)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_client uuid; v_name text; v_placeholder boolean; v_org_count bigint;
BEGIN
    IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'computer_client_group_name_proved: tenant context mismatch';
    END IF;
    SELECT count(*), (array_agg(link.entity_id))[1],
           (array_agg(regexp_replace(lower(coalesce(org.canonical_data->>'name', '')), '[\s\-_.]', '', 'g')))[1],
           bool_or(lower(coalesce(org.canonical_data->>'is_placeholder', 'false')) = 'true')
      INTO v_org_count, v_client, v_name, v_placeholder
      FROM operations.entity_source_links link
      JOIN operations.entity_observation_current org
        ON org.tenant_id = link.tenant_id AND org.source_instance_id = link.source_instance_id
       AND org.external_namespace = link.external_namespace
       AND org.parent_external_namespace = link.parent_external_namespace
       AND org.parent_external_id = link.parent_external_id AND org.external_id = link.external_id
       AND org.entity_type = 'org' AND org.active
     WHERE link.tenant_id = p_tenant AND link.id = p_link AND link.entity_class_id = 'client'
       AND link.missing_since IS NULL;
    IF v_org_count <> 1 OR v_name = '' OR v_placeholder OR
       EXISTS (SELECT 1 FROM operations.placeholder_org_names
                WHERE tenant_id = p_tenant AND normalized_name = v_name) OR
       EXISTS (SELECT 1 FROM operations.client_org_excludes
                WHERE tenant_id = p_tenant AND enabled AND normalized_name = v_name) THEN
        RETURN false;
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM operations.clients client
         WHERE client.tenant_id = p_tenant AND client.id = v_client AND client.deleted_at IS NULL
           AND (regexp_replace(lower(client.display_name), '[\s\-_.]', '', 'g') = v_name OR EXISTS (
               SELECT 1 FROM operations.client_name_aliases alias
                WHERE alias.tenant_id = p_tenant AND alias.client_id = client.id AND alias.enabled
                  AND alias.normalized_name = v_name
                  AND (alias.tier = 'seed' OR (alias.tier = 'manual'
                       AND (alias.created_by = 'operator' OR alias.created_by LIKE 'user:%')))))
    ) AND NOT EXISTS (
        SELECT 1 FROM operations.clients other
         WHERE other.tenant_id = p_tenant AND other.id <> v_client AND other.deleted_at IS NULL
           AND regexp_replace(lower(other.display_name), '[\s\-_.]', '', 'g') = v_name
    ) AND NOT EXISTS (
        SELECT 1 FROM operations.client_name_aliases alias
        JOIN operations.clients other ON other.tenant_id = alias.tenant_id
         AND other.id = alias.client_id AND other.deleted_at IS NULL
         WHERE alias.tenant_id = p_tenant AND alias.client_id <> v_client
           AND alias.enabled AND alias.normalized_name = v_name
    );
END
$fn$;
REVOKE ALL ON FUNCTION operations.computer_client_group_name_proved(bigint, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;

CREATE FUNCTION operations.computer_client_independent_evidence(p_tenant bigint, p_observation uuid)
RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_instance uuid;
    v_instance_client uuid;
    v_group text;
    v_entity_type text;
    v_namespace text;
    v_parent_namespace text;
    v_parent_id text;
    v_org_count bigint;
    v_link_count integer;
    v_client uuid;
    v_proved boolean;
BEGIN
    IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'computer_client_independent_evidence: tenant context mismatch';
    END IF;
    SELECT observation.source_instance_id, instance.client_id,
           CASE WHEN observation.entity_type = 'org' THEN nullif(btrim(observation.external_id), '')
                ELSE nullif(btrim(observation.canonical_data->>'platform_group_id'), '') END,
           observation.entity_type, observation.external_namespace,
           observation.parent_external_namespace, observation.parent_external_id
      INTO v_instance, v_instance_client, v_group, v_entity_type,
           v_namespace, v_parent_namespace, v_parent_id
      FROM operations.entity_observation_current observation
      LEFT JOIN operations.source_instances instance
        ON instance.tenant_id = observation.tenant_id AND instance.id = observation.source_instance_id
     WHERE observation.tenant_id = p_tenant AND observation.observation_id = p_observation;
    IF NOT FOUND OR v_instance IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_instance_client IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM operations.clients
                    WHERE tenant_id = p_tenant AND id = v_instance_client AND deleted_at IS NULL) THEN
            RETURN v_instance_client;
        END IF;
        RETURN NULL;
    END IF;
    IF v_group IS NULL THEN
        RETURN NULL;
    END IF;
    -- Resolve the source's group ID to exactly one current organization record.
    -- Its complete identity, not the possibly reused group ID, selects a link.
    IF v_entity_type <> 'org' THEN
        SELECT count(*), (array_agg(org.external_id))[1],
               (array_agg(org.external_namespace))[1],
               (array_agg(org.parent_external_namespace))[1],
               (array_agg(org.parent_external_id))[1]
          INTO v_org_count, v_group, v_namespace, v_parent_namespace, v_parent_id
          FROM operations.entity_observation_current org
         WHERE org.tenant_id = p_tenant AND org.source_instance_id = v_instance
           AND org.entity_type = 'org' AND org.active
           AND (org.entity_key = v_group OR org.external_id = v_group)
           AND (v_parent_id IS DISTINCT FROM v_group OR coalesce(v_parent_namespace, '') = ''
                OR org.external_namespace = v_parent_namespace);
        IF v_org_count <> 1 THEN RETURN NULL; END IF;
    END IF;
    SELECT count(*), (array_agg(link.entity_id))[1],
           bool_and(EXISTS (
               SELECT 1 FROM operations.client_source_mapping_decisions decision
               JOIN operations.entity_source_link_history history
                 ON history.tenant_id = link.tenant_id
                AND history.source_instance_id = link.source_instance_id
                AND history.external_namespace = link.external_namespace
                AND history.parent_external_namespace = link.parent_external_namespace
                AND history.parent_external_id = link.parent_external_id
                AND history.external_id = link.external_id
                AND history.entity_class_id = 'client' AND history.entity_id = link.entity_id
                AND history.effective_to IS NULL
              WHERE decision.tenant_id = link.tenant_id AND decision.source_link_id = link.id
                AND decision.superseded_at IS NULL
                AND ((decision.state = 'explicit' AND decision.provenance = 'operator'
                      AND decision.decided_at >= history.effective_from)
                     OR (decision.state IN ('automatic', 'explicit')
                         AND decision.provenance IN ('resolver', 'legacy_alias')
                         AND operations.computer_client_group_name_proved(p_tenant, link.id)))
           ))
      INTO v_link_count, v_client, v_proved
      FROM operations.entity_source_links link
      JOIN operations.clients client ON client.tenant_id = link.tenant_id
       AND client.id = link.entity_id AND client.deleted_at IS NULL
     WHERE link.tenant_id = p_tenant AND link.source_instance_id = v_instance
       AND link.entity_class_id = 'client' AND link.external_id = v_group
       AND link.external_namespace = v_namespace
       AND link.parent_external_namespace = v_parent_namespace
       AND link.parent_external_id = v_parent_id
       AND link.missing_since IS NULL;
    IF v_link_count = 1 AND v_proved THEN
        RETURN v_client;
    END IF;
    RETURN NULL;
END
$fn$;
REVOKE ALL ON FUNCTION operations.computer_client_independent_evidence(bigint, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.computer_client_independent_evidence(bigint, uuid)
    TO ninja_ingest, operations_app;

-- Ingest can read these tables but cannot acquire row locks directly. Keep the
-- source instance and its live client stable while inline matching uses them.
CREATE FUNCTION operations.lock_source_instance_client(
    p_tenant bigint, p_instance uuid, p_client uuid
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE v_client uuid;
BEGIN
    IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'lock_source_instance_client: tenant context mismatch';
    END IF;
    SELECT instance.client_id INTO v_client
      FROM operations.source_instances instance
      JOIN operations.clients client
        ON client.tenant_id = instance.tenant_id AND client.id = instance.client_id
       AND client.deleted_at IS NULL
     WHERE instance.tenant_id = p_tenant AND instance.id = p_instance
       AND (p_client IS NULL OR instance.client_id = p_client)
     FOR SHARE OF instance, client;
    RETURN v_client;
END
$fn$;
REVOKE ALL ON FUNCTION operations.lock_source_instance_client(bigint, uuid, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.lock_source_instance_client(bigint, uuid, uuid) TO ninja_ingest;

CREATE FUNCTION operations.project_computer_client(p_tenant bigint, p_device uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    d operations.devices%ROWTYPE;
    v_state text;
    v_reason text := '';
    v_client uuid;
    v_choice jsonb;
    v_record_count bigint;
    v_client_count bigint;
    v_unknown_count bigint;
    v_contradiction boolean := false;
    v_legacy_decision boolean := false;
    v_previous_state text;
    v_previous_client uuid;
    v_needs_update boolean;
    v_os_entities uuid[];
    v_action text := current_setting('operations.change_action_id', true);
BEGIN
    IF p_tenant IS NULL OR p_device IS NULL OR p_tenant IS DISTINCT FROM
       nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RAISE EXCEPTION 'project_computer_client: tenant context mismatch';
    END IF;

    INSERT INTO operations.computer_client_ownership (tenant_id, device_id)
    SELECT tenant_id, id FROM operations.devices
     WHERE tenant_id = p_tenant AND id = p_device AND deleted_at IS NULL
    ON CONFLICT (tenant_id, device_id) DO NOTHING;
    SELECT state, effective_client_id INTO v_previous_state, v_previous_client
      FROM operations.computer_client_ownership
     WHERE tenant_id = p_tenant AND device_id = p_device FOR UPDATE;
    IF NOT FOUND THEN
        IF EXISTS (SELECT 1 FROM operations.devices
                    WHERE tenant_id = p_tenant AND id = p_device AND deleted_at IS NOT NULL) THEN
            RETURN 'deleted';
        END IF;
        RAISE EXCEPTION 'project_computer_client: unknown or deleted Computer';
    END IF;
    SELECT * INTO d FROM operations.devices
     WHERE tenant_id = p_tenant AND id = p_device AND deleted_at IS NULL FOR UPDATE;
    IF NOT FOUND THEN
        IF EXISTS (SELECT 1 FROM operations.devices
                    WHERE tenant_id = p_tenant AND id = p_device AND deleted_at IS NOT NULL) THEN
            RETURN 'deleted';
        END IF;
        RAISE EXCEPTION 'project_computer_client: unknown or deleted Computer';
    END IF;

    SELECT count(*), count(DISTINCT client.id),
           count(*) FILTER (WHERE client.id IS NULL),
           (array_agg(DISTINCT client.id) FILTER (WHERE client.id IS NOT NULL))[1]
      INTO v_record_count, v_client_count, v_unknown_count, v_client
      FROM operations.entity_observation_current observation
      LEFT JOIN LATERAL (
          SELECT operations.computer_client_independent_evidence(
              observation.tenant_id, observation.observation_id) AS client_id
      ) source_client ON TRUE
      LEFT JOIN operations.clients client
        ON client.tenant_id = observation.tenant_id AND client.id = source_client.client_id
       AND client.deleted_at IS NULL
     WHERE observation.tenant_id = p_tenant AND observation.device_id = p_device
       AND observation.active AND observation.entity_type <> 'org'
       AND NOT operations.is_companion_stream(observation.tenant_id,
               observation.source_instance_id, observation.external_namespace)
       AND NOT EXISTS (
           SELECT 1 FROM operations.identity_roaming_records roaming
            WHERE roaming.tenant_id = observation.tenant_id
              AND roaming.source_instance_id = observation.source_instance_id
              AND roaming.external_id = observation.external_id);

    IF v_client_count > 1 THEN
        v_state := 'conflict'; v_client := NULL;
    ELSIF v_record_count = 0 OR v_unknown_count > 0 THEN
        v_state := 'unknown'; v_client := NULL;
    ELSE
        v_state := 'resolved';
    END IF;

    SELECT value INTO v_choice FROM operations.device_operator_decisions
     WHERE tenant_id = p_tenant AND device_id = p_device
       AND dimension = 'client_ownership_choice';
    IF FOUND THEN
        IF jsonb_typeof(v_choice) <> 'object' OR coalesce(v_choice ->> 'client_id', '') = '' THEN
            RAISE EXCEPTION 'project_computer_client: invalid client ownership decision';
        END IF;
        v_client := (v_choice ->> 'client_id')::uuid;
        IF NOT EXISTS (SELECT 1 FROM operations.clients
                        WHERE tenant_id = p_tenant AND id = v_client AND deleted_at IS NULL) THEN
            v_state := 'review'; v_client := NULL; v_reason := 'decision_client_unavailable';
        ELSE
            SELECT EXISTS (
                SELECT 1 FROM operations.entity_observation_current observation
                JOIN LATERAL (
                    SELECT operations.computer_client_independent_evidence(
                        observation.tenant_id, observation.observation_id) AS client_id
                ) source_client ON TRUE
                JOIN operations.clients client
                  ON client.tenant_id = observation.tenant_id AND client.id = source_client.client_id
                 AND client.deleted_at IS NULL
                WHERE observation.tenant_id = p_tenant AND observation.device_id = p_device
                  AND observation.active AND observation.entity_type <> 'org'
                  AND client.id <> v_client
                  AND NOT EXISTS (
                      SELECT 1 FROM jsonb_array_elements(coalesce(v_choice -> 'evidence', '[]'::jsonb)) saved
                       WHERE saved ->> 'observation_id' = observation.observation_id::text
                         AND saved ->> 'client_id' = client.id::text)
                  AND NOT operations.is_companion_stream(observation.tenant_id,
                          observation.source_instance_id, observation.external_namespace)
                  AND NOT EXISTS (
                      SELECT 1 FROM operations.identity_roaming_records roaming
                       WHERE roaming.tenant_id = observation.tenant_id
                         AND roaming.source_instance_id = observation.source_instance_id
                         AND roaming.external_id = observation.external_id)
            ) INTO v_contradiction;
            v_state := 'decision_protected';
            IF v_contradiction THEN
                v_reason := 'new_evidence_contradicts_decision';
            ELSIF v_record_count = 0 OR v_unknown_count > 0 THEN
                v_reason := 'decision_evidence_unknown';
            END IF;
        END IF;
    ELSE
        -- A legacy accepted record is a scoped human action, but its key does
        -- not contain a selected client or a snapshot of the record's client.
        SELECT EXISTS (
            SELECT 1 FROM operations.device_operator_decisions decision
            CROSS JOIN LATERAL jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(decision.value) = 'array' THEN decision.value ELSE '[]'::jsonb END
            ) accepted(key)
            JOIN operations.entity_observation_current observation
              ON observation.tenant_id = decision.tenant_id
             AND observation.device_id = decision.device_id AND observation.active
             AND accepted.key = 'record:' || observation.platform || '|' || observation.entity_key
            WHERE decision.tenant_id = p_tenant AND decision.device_id = p_device
              AND decision.dimension = 'client_conflict_accepted'
        ) OR EXISTS (
            -- The source-group move also called this operator procedure, so
            -- history proves an action occurred but not a Computer choice.
            SELECT 1 FROM operations.devices_change_history history
            JOIN operations.change_actions action ON action.id = history.action_id
             WHERE history.tenant_id = p_tenant AND history.computer_id = p_device
               AND action.action = 'computer.move_client' AND action.actor_kind = 'operator'
        ) INTO v_legacy_decision;
        IF v_legacy_decision AND (v_state <> 'resolved' OR v_client IS DISTINCT FROM d.client_id) THEN
            v_state := 'review'; v_client := NULL; v_reason := 'legacy_decision_needs_review';
        END IF;
    END IF;

    IF v_client IS NOT NULL THEN
        SELECT coalesce(array_agg(DISTINCT relationship.source_entity_id), '{}'::uuid[])
          INTO v_os_entities FROM operations.entity_relationships relationship
         WHERE relationship.tenant_id = p_tenant
           AND relationship.relationship_type_id = 'os_installation_runs_on_computer'
           AND relationship.status = 'active' AND relationship.target_entity_id = d.entity_id;
        IF EXISTS (
            SELECT 1 FROM operations.entity_relationships relationship
             WHERE relationship.tenant_id = p_tenant
               AND relationship.relationship_type_id = 'os_installation_runs_on_computer'
               AND relationship.status = 'active'
               AND relationship.source_entity_id = ANY(v_os_entities)
               AND relationship.target_entity_id <> d.entity_id
        ) THEN
            v_state := 'review'; v_client := NULL; v_contradiction := false;
            v_reason := 'shared_os_installation';
        ELSE
            SELECT d.client_id IS DISTINCT FROM v_client
                OR EXISTS (SELECT 1 FROM operations.entities
                            WHERE tenant_id = p_tenant AND (id = d.entity_id OR id = ANY(v_os_entities))
                              AND client_id IS DISTINCT FROM v_client)
                OR EXISTS (SELECT 1 FROM operations.operating_system_installations
                            WHERE tenant_id = p_tenant AND entity_id = ANY(v_os_entities)
                              AND client_id IS DISTINCT FROM v_client)
                OR EXISTS (SELECT 1 FROM operations.findings WHERE tenant_id = p_tenant
                            AND subject_type = 'device' AND subject_id = d.id
                            AND client_id IS DISTINCT FROM v_client)
                OR EXISTS (SELECT 1 FROM operations.software_installations_current
                            WHERE tenant_id = p_tenant AND device_id = d.id
                              AND client_id IS DISTINCT FROM v_client)
                OR EXISTS (SELECT 1 FROM operations.software_decisions
                            WHERE tenant_id = p_tenant AND device_id = d.id
                              AND client_id = d.client_id AND client_id IS DISTINCT FROM v_client)
                OR EXISTS (SELECT 1 FROM operations.device_windows_servicing_current
                            WHERE tenant_id = p_tenant AND device_id = d.id
                              AND client_id IS DISTINCT FROM v_client)
                OR EXISTS (SELECT 1 FROM operations.computer_name_collisions
                            WHERE tenant_id = p_tenant AND device_id = d.id
                              AND client_id IS DISTINCT FROM v_client)
              INTO v_needs_update;
          IF v_needs_update THEN
            PERFORM operations.begin_change(
                'computer.project_client', 'Reconcile Computer client from current ownership evidence.',
                jsonb_build_object('device_id', d.id, 'from_client_id', d.client_id,
                                   'to_client_id', v_client, 'ownership_state', v_state),
                'process', NULL, 'ingest.identity.computer_client_ownership', '', p_tenant, true);
            UPDATE operations.devices SET client_id = v_client
             WHERE tenant_id = p_tenant AND id = d.id AND client_id IS DISTINCT FROM v_client;
            UPDATE operations.entities SET client_id = v_client
             WHERE tenant_id = p_tenant AND id = d.entity_id AND client_id IS DISTINCT FROM v_client;
            UPDATE operations.entities SET client_id = v_client
             WHERE tenant_id = p_tenant AND id = ANY(v_os_entities) AND client_id IS DISTINCT FROM v_client;
            UPDATE operations.operating_system_installations SET client_id = v_client
             WHERE tenant_id = p_tenant AND entity_id = ANY(v_os_entities)
               AND client_id IS DISTINCT FROM v_client;
            UPDATE operations.findings SET client_id = v_client
             WHERE tenant_id = p_tenant AND subject_type = 'device' AND subject_id = d.id
               AND client_id IS DISTINCT FROM v_client;
            UPDATE operations.software_installations_current SET client_id = v_client
             WHERE tenant_id = p_tenant AND device_id = d.id AND client_id IS DISTINCT FROM v_client;
            -- Preserve decisions whose client was intentionally broad or has
            -- another explicit scope; do not convert a NULL to a client.
            UPDATE operations.software_decisions SET client_id = v_client
             WHERE tenant_id = p_tenant AND device_id = d.id AND client_id = d.client_id
               AND client_id IS DISTINCT FROM v_client;
            UPDATE operations.device_windows_servicing_current SET client_id = v_client
             WHERE tenant_id = p_tenant AND device_id = d.id AND client_id IS DISTINCT FROM v_client;
            UPDATE operations.computer_name_collisions SET client_id = v_client
             WHERE tenant_id = p_tenant AND device_id = d.id AND client_id IS DISTINCT FROM v_client;
            PERFORM set_config('operations.change_action_id', coalesce(v_action, ''), true);
          END IF;
        END IF;
    END IF;

    UPDATE operations.computer_client_ownership
       SET state = v_state, effective_client_id = v_client,
           projected_revision = evidence_revision, contradiction = v_contradiction,
           reason = v_reason, updated_at = now()
     WHERE tenant_id = p_tenant AND device_id = p_device;
    IF (v_previous_state, v_previous_client) IS DISTINCT FROM (v_state, v_client) THEN
        PERFORM operations.queue_computer_client_reassessment(p_tenant, p_device);
    END IF;
    RETURN v_state;
END
$fn$;

REVOKE ALL ON FUNCTION operations.project_computer_client(bigint, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.project_computer_client(bigint, uuid) TO ninja_ingest;
"""

REVERSE_SQL = r"""
DO $reverse$
BEGIN
    IF EXISTS (SELECT 1 FROM operations.device_operator_decisions
                WHERE dimension = 'client_ownership_choice') THEN
        RAISE EXCEPTION 'Cannot reverse Computer ownership while explicit choices exist';
    END IF;
END
$reverse$;
DROP FUNCTION operations.project_computer_client(bigint, uuid);
DROP FUNCTION operations.lock_source_instance_client(bigint, uuid, uuid);
DROP FUNCTION operations.computer_client_independent_evidence(bigint, uuid);
DROP FUNCTION operations.computer_client_group_name_proved(bigint, uuid);
DROP FUNCTION operations.computer_client_conflict_decisions(bigint);
DELETE FROM operations.operator_decision_dimensions WHERE name = 'client_ownership_choice';
ALTER TABLE operations.client_source_mapping_decisions
    ALTER COLUMN decided_at SET DEFAULT now();
"""


def _mapping_decision_function(*, wall_clock: bool) -> str:
    sql = importlib.import_module(
        "apps.core.migrations.0201_client_source_mapping_decisions"
    ).FORWARD_SQL
    start = sql.index("CREATE FUNCTION operations.decide_client_source_mapping_v1(")
    end = sql.index("$$;", start) + len("$$;")
    definition = sql[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    if wall_clock:
        old = "SET superseded_at = now()"
        if definition.count(old) != 1:
            raise RuntimeError("Client mapping decision timestamp contract changed")
        definition = definition.replace(old, "SET superseded_at = clock_timestamp()", 1)
    return definition


FORWARD_SQL = _mapping_decision_function(wall_clock=True) + "\n" + FORWARD_SQL
REVERSE_SQL = _mapping_decision_function(wall_clock=False) + "\n" + REVERSE_SQL


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0401_computer_client_ownership_state"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
