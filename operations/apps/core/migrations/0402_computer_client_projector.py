"""Project Computer ownership under the PLAN-045 invalidation lock.

The reader transition, operator decision writer and full-cycle integration
must accompany this unfinished migration before deployment.
"""

from typing import ClassVar

from django.db import migrations


FORWARD_SQL = r"""
INSERT INTO operations.operator_decision_dimensions
    (name, entity_type, value_type, allowed_values, description, enabled)
VALUES ('client_ownership_choice', 'device', 'json', NULL,
        'Explicit Computer client choice, including the selected client and decision evidence.', true)
ON CONFLICT (name) DO NOTHING;

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
    PERFORM 1 FROM operations.computer_client_ownership
     WHERE tenant_id = p_tenant AND device_id = p_device FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project_computer_client: unknown or deleted Computer';
    END IF;
    SELECT * INTO d FROM operations.devices
     WHERE tenant_id = p_tenant AND id = p_device AND deleted_at IS NULL FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project_computer_client: unknown or deleted Computer';
    END IF;

    SELECT count(*), count(DISTINCT client.id),
           count(*) FILTER (WHERE client.id IS NULL),
           (array_agg(DISTINCT client.id) FILTER (WHERE client.id IS NOT NULL))[1]
      INTO v_record_count, v_client_count, v_unknown_count, v_client
      FROM operations.entity_observation_current observation
      LEFT JOIN operations.clients client
        ON client.tenant_id = observation.tenant_id AND client.id = observation.client_id
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
                JOIN operations.clients client
                  ON client.tenant_id = observation.tenant_id AND client.id = observation.client_id
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
DELETE FROM operations.operator_decision_dimensions WHERE name = 'client_ownership_choice';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0401_computer_client_ownership_state"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
