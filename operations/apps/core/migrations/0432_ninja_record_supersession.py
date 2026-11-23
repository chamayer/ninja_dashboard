"""Keep a superseded Ninja record out of current Computer associations."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE TABLE operations.ninja_record_supersessions (
    tenant_id bigint NOT NULL,
    source_record_id uuid NOT NULL,
    successor_record_id uuid NOT NULL,
    computer_id uuid NOT NULL,
    action_id uuid NOT NULL REFERENCES operations.change_actions(id),
    superseded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, source_record_id),
    FOREIGN KEY (tenant_id, source_record_id) REFERENCES operations.source_record_subjects(tenant_id, id),
    FOREIGN KEY (tenant_id, successor_record_id) REFERENCES operations.source_record_subjects(tenant_id, id),
    FOREIGN KEY (tenant_id, computer_id) REFERENCES operations.devices(tenant_id, id),
    CHECK (source_record_id <> successor_record_id)
);
ALTER TABLE operations.ninja_record_supersessions OWNER TO operations_migrate;
ALTER TABLE operations.ninja_record_supersessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.ninja_record_supersessions FORCE ROW LEVEL SECURITY;
CREATE POLICY ninja_record_supersessions_tenant ON operations.ninja_record_supersessions
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
REVOKE ALL ON operations.ninja_record_supersessions
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;

INSERT INTO operations.change_history_registry
    (table_name, classification, reason, recorded_columns, secret_columns, key_columns,
     computer_column, computer_condition_column, computer_condition_value, client_column,
     is_global, capture)
VALUES
    ('ninja_record_supersessions', 'history_store',
     'Records the action that made a Ninja association historical only',
     '{}', '{}', ARRAY['tenant_id', 'source_record_id'], 'computer_id', NULL, NULL, NULL,
     false, NULL);

CREATE FUNCTION operations.ninja_record_is_superseded(
    p_tenant bigint, p_source_instance uuid, p_namespace text,
    p_parent_namespace text, p_parent_id text, p_external_id text
) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT EXISTS (
        SELECT 1
          FROM operations.source_record_subjects subject
          JOIN operations.ninja_record_supersessions history
            ON history.tenant_id = subject.tenant_id AND history.source_record_id = subject.id
         WHERE p_tenant = nullif(current_setting('operations.tenant_id', true), '')::bigint
           AND subject.tenant_id = p_tenant AND subject.source_instance_id = p_source_instance
           AND subject.subject_kind = 'record'
           AND subject.external_namespace = p_namespace AND subject.external_id = p_external_id
           AND subject.parent_external_namespace = p_parent_namespace
           AND subject.parent_external_id = p_parent_id
    )
$fn$;
ALTER FUNCTION operations.ninja_record_is_superseded(bigint, uuid, text, text, text, text)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.ninja_record_is_superseded(bigint, uuid, text, text, text, text)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.ninja_record_is_superseded(bigint, uuid, text, text, text, text)
    TO ninja_ingest;

CREATE FUNCTION operations.ninja_computer_slot_occupied(
    p_tenant bigint, p_computer uuid, p_source_instance uuid, p_namespace text,
    p_parent_namespace text, p_parent_id text, p_external_id text
) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT NOT operations.is_companion_stream(p_tenant, p_source_instance, p_namespace)
       AND EXISTS (
        SELECT 1 FROM operations.devices device
        JOIN operations.entity_source_links link
          ON link.tenant_id = device.tenant_id AND link.entity_id = device.entity_id
         AND link.entity_class_id = 'device'
        JOIN operations.source_instances instance
          ON instance.tenant_id = link.tenant_id AND instance.id = link.source_instance_id
        JOIN operations.sources source ON source.id = instance.source_id AND source.name = 'Ninja'
        WHERE p_tenant = nullif(current_setting('operations.tenant_id', true), '')::bigint
          AND device.tenant_id = p_tenant AND device.id = p_computer
          AND NOT operations.is_companion_stream(link.tenant_id, link.source_instance_id, link.external_namespace)
          AND (link.source_instance_id, link.external_namespace, link.parent_external_namespace,
               link.parent_external_id, link.external_id)
              IS DISTINCT FROM (p_source_instance, p_namespace, p_parent_namespace, p_parent_id, p_external_id)
    )
$fn$;
ALTER FUNCTION operations.ninja_computer_slot_occupied(bigint, uuid, uuid, text, text, text, text)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.ninja_computer_slot_occupied(bigint, uuid, uuid, text, text, text, text)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.ninja_computer_slot_occupied(bigint, uuid, uuid, text, text, text, text)
    TO ninja_ingest;

CREATE FUNCTION operations.ninja_record_excluded_from_computer(p_tenant bigint, p_computer uuid, p_key text)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
    SELECT EXISTS (
        SELECT 1 FROM operations.device_operator_decisions decision
        WHERE p_tenant = nullif(current_setting('operations.tenant_id', true), '')::bigint
          AND decision.tenant_id = p_tenant AND decision.device_id = p_computer
          AND decision.dimension = 'identity_excluded_records'
          AND decision.value ? ('Ninja|' || p_key)
    )
$fn$;
ALTER FUNCTION operations.ninja_record_excluded_from_computer(bigint, uuid, text)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.ninja_record_excluded_from_computer(bigint, uuid, text)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.ninja_record_excluded_from_computer(bigint, uuid, text)
    TO ninja_ingest;

CREATE FUNCTION operations.reject_superseded_ninja_link() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_computer uuid;
BEGIN
    IF NEW.entity_class_id <> 'device' THEN
        RETURN NEW;
    END IF;
    IF operations.ninja_record_is_superseded(
        NEW.tenant_id, NEW.source_instance_id, NEW.external_namespace,
        NEW.parent_external_namespace, NEW.parent_external_id, NEW.external_id
    ) THEN
        RAISE EXCEPTION 'A superseded Ninja record cannot be a current Computer association';
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.entity_id, NEW.entity_class_id) = (OLD.entity_id, OLD.entity_class_id) THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        SELECT 1 FROM operations.source_instances instance
        JOIN operations.sources source ON source.id = instance.source_id AND source.name = 'Ninja'
        WHERE instance.tenant_id = NEW.tenant_id AND instance.id = NEW.source_instance_id
    ) THEN
        IF NEW.tenant_id IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
            RAISE EXCEPTION 'Invalid Ninja link tenant';
        END IF;
        -- Serialize contenders for the same Computer, including an old node
        -- that Ninja withdrew but whose current association was never closed.
        SELECT id INTO v_computer FROM operations.devices
         WHERE tenant_id = NEW.tenant_id AND entity_id = NEW.entity_id FOR UPDATE;
        IF operations.ninja_computer_slot_occupied(
            NEW.tenant_id, v_computer, NEW.source_instance_id, NEW.external_namespace,
            NEW.parent_external_namespace, NEW.parent_external_id, NEW.external_id
        ) THEN
            RAISE EXCEPTION 'The Computer already has a current Ninja association'
                USING ERRCODE = 'unique_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$fn$;
ALTER FUNCTION operations.reject_superseded_ninja_link() OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.reject_superseded_ninja_link()
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
CREATE TRIGGER reject_superseded_ninja_link
    BEFORE INSERT OR UPDATE OF entity_id, entity_class_id ON operations.entity_source_links
    FOR EACH ROW EXECUTE FUNCTION operations.reject_superseded_ninja_link();

CREATE FUNCTION operations.supersede_ninja_computer_record(
    p_tenant bigint, p_computer uuid, p_old uuid, p_new uuid, p_action uuid,
    p_old_input bigint, p_new_input bigint, p_old_association bigint, p_new_association bigint,
    p_estimated uuid DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_old_contact timestamptz;
    v_new_contact timestamptz;
    v_old_computer uuid;
    v_new_computer uuid;
    v_reason text;
    v_version bigint;
BEGIN
    IF p_tenant IS NULL
       OR p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint
       OR p_old IS NULL OR p_new IS NULL OR p_old = p_new
       OR p_action IS NULL
       OR p_action IS DISTINCT FROM nullif(current_setting('operations.change_action_id', true), '')::uuid THEN
        RAISE EXCEPTION 'Invalid Ninja supersession context';
    END IF;
    PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');
    SELECT reason INTO STRICT v_reason FROM operations.change_actions
     WHERE tenant_id = p_tenant AND id = p_action AND explicit
       AND action = 'computer.ninja_record.supersede' AND btrim(reason) <> ''
       AND evidence ->> 'machine_outcome' = 'same'
       AND evidence ->> 'computer_id' = p_computer::text
       AND (evidence ->> 'estimated_id') IS NOT DISTINCT FROM p_estimated::text
       AND evidence ->> 'previous_subject_id' = p_old::text
       AND evidence ->> 'selected_subject_id' = p_new::text;

    IF p_estimated IS NOT NULL THEN
        PERFORM estimated.id
          FROM operations.devices estimated
          JOIN operations.devices verified
            ON verified.tenant_id = estimated.tenant_id AND verified.id = p_computer
           AND verified.client_id = estimated.client_id AND verified.deleted_at IS NULL
          JOIN operations.computer_client_ownership verified_owner
            ON verified_owner.tenant_id = verified.tenant_id AND verified_owner.device_id = verified.id
           AND verified_owner.effective_client_id = verified.client_id
           AND verified_owner.state IN ('resolved', 'decision_protected')
          JOIN operations.computer_client_ownership estimated_owner
            ON estimated_owner.tenant_id = estimated.tenant_id AND estimated_owner.device_id = estimated.id
           AND estimated_owner.effective_client_id = estimated.client_id
           AND estimated_owner.state = 'resolved'
         WHERE estimated.tenant_id = p_tenant AND estimated.id = p_estimated
           AND estimated.deleted_at IS NULL AND estimated.created_reason = 'identity_estimated'
           AND verified.created_reason IS DISTINCT FROM 'identity_estimated'
           AND NOT EXISTS (
               SELECT 1 FROM operations.device_operator_decisions decision
                WHERE decision.tenant_id = estimated.tenant_id AND decision.device_id = estimated.id
           )
         FOR UPDATE OF estimated, verified, verified_owner, estimated_owner;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'The estimated Computer cannot be consolidated under the current records and client';
        END IF;
    END IF;

    -- The reviewed caller uses the shared identity assessment before issuing
    -- the audit action. These row locks and input versions pin its evidence.
    PERFORM id FROM operations.source_record_subjects
     WHERE tenant_id = p_tenant AND id IN (p_old, p_new)
     ORDER BY id FOR UPDATE;
    SELECT (eo.canonical_data ->> 'last_contact_at')::timestamptz, eo.device_id
      INTO STRICT v_old_contact, v_old_computer
      FROM operations.source_record_subjects s
      JOIN operations.entity_observation_current eo
        ON eo.tenant_id = s.tenant_id AND eo.observation_id = s.observation_id
     WHERE s.tenant_id = p_tenant AND s.id = p_old AND s.subject_kind = 'record'
       AND s.input_version = p_old_input AND s.association_version = p_old_association
       AND eo.device_id IN (p_computer, p_estimated) AND eo.platform = 'Ninja'
       AND (NOT eo.active OR coalesce(eo.canonical_data ->> 'is_online',
           CASE eo.canonical_data ->> 'offline' WHEN 'true' THEN 'false' WHEN 'false' THEN 'true' END) = 'false');
    SELECT (eo.canonical_data ->> 'last_contact_at')::timestamptz, eo.device_id
      INTO STRICT v_new_contact, v_new_computer
      FROM operations.source_record_subjects s
      JOIN operations.entity_observation_current eo
        ON eo.tenant_id = s.tenant_id AND eo.observation_id = s.observation_id
     WHERE s.tenant_id = p_tenant AND s.id = p_new AND s.subject_kind = 'record'
       AND s.input_version = p_new_input AND s.association_version = p_new_association
       AND (eo.device_id IN (p_computer, p_estimated)
            OR (p_estimated IS NULL AND eo.device_id IS NULL))
       AND eo.platform = 'Ninja' AND eo.active
       AND NOT EXISTS (
           SELECT 1 FROM operations.ninja_record_supersessions prior
            WHERE prior.tenant_id = p_tenant AND prior.source_record_id = p_new
       );
    IF (v_new_contact > v_old_contact) IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'Ninja agent contact does not establish a successor';
    END IF;
    IF p_estimated IS NOT NULL AND v_old_computer = v_new_computer THEN
        RAISE EXCEPTION 'The estimated Computer and verified Computer must each hold one Ninja record';
    END IF;

    v_version := operations.set_source_association(
        p_old, NULL, 'device', 'ninja_superseded', 1, v_reason, p_old_association,
        'system', NULL, 'operations.ninja_record_supersession',
        jsonb_build_object('successor_record_id', p_new, 'action_id', p_action)
    );
    IF v_version IS DISTINCT FROM p_old_association + 1 THEN
        RAISE EXCEPTION 'The historical Ninja association did not close';
    END IF;
    INSERT INTO operations.ninja_record_supersessions
        (tenant_id, source_record_id, successor_record_id, computer_id, action_id)
    VALUES (p_tenant, p_old, p_new, p_computer, p_action);
END
$fn$;
ALTER FUNCTION operations.supersede_ninja_computer_record(bigint, uuid, uuid, uuid, uuid, bigint, bigint, bigint, bigint, uuid)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.supersede_ninja_computer_record(bigint, uuid, uuid, uuid, uuid, bigint, bigint, bigint, bigint, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.supersede_ninja_computer_record(bigint, uuid, uuid, uuid, uuid, bigint, bigint, bigint, bigint, uuid)
    TO ninja_ingest;

CREATE FUNCTION operations.close_cross_client_ninja_predecessor(
    p_tenant bigint, p_survivor uuid, p_absorbed uuid, p_action uuid
) RETURNS jsonb
LANGUAGE plpgsql
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_action operations.change_actions%ROWTYPE;
    v_slots integer;
    v_anchors integer;
    v_cutoff timestamptz;
    v_version bigint;
    chosen record;
BEGIN
    -- Called by the migration-owned repair writer after the complete reviewed
    -- membership and both client scopes have been locked and rechecked.
    PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');
    SELECT * INTO STRICT v_action FROM operations.change_actions
     WHERE tenant_id = p_tenant AND id = p_action
       AND explicit AND action = 'computer.merge.cross_client'
       AND id = nullif(current_setting('operations.change_action_id', true), '')::uuid
       AND evidence ->> 'machine_outcome' = 'same'
       AND evidence ->> 'survivor_id' = p_survivor::text
       AND evidence ->> 'absorbed_id' = p_absorbed::text;

    SELECT count(*), count(DISTINCT device.id) INTO v_slots, v_anchors
      FROM operations.devices device
      JOIN operations.entity_source_links link
        ON link.tenant_id = device.tenant_id AND link.entity_id = device.entity_id
       AND link.entity_class_id = 'device'
      JOIN operations.source_instances instance
        ON instance.tenant_id = link.tenant_id AND instance.id = link.source_instance_id
      JOIN operations.sources source ON source.id = instance.source_id AND source.name = 'Ninja'
     WHERE device.tenant_id = p_tenant AND device.id IN (p_survivor, p_absorbed)
       AND NOT operations.is_companion_stream(link.tenant_id, link.source_instance_id, link.external_namespace);
    IF v_slots <= 1 THEN
        RETURN NULL;
    END IF;
    IF v_slots <> 2 OR v_anchors <> 2 THEN
        RAISE EXCEPTION 'Review the existing duplicate Ninja associations before merging these Computers';
    END IF;

    SELECT now() - make_interval(days => least(36500, coalesce(nullif(client.offline_after_days, 0),
                    CASE WHEN pg_input_is_valid(config.config ->> 'active_device_days', 'integer')
                         THEN greatest(1, (config.config ->> 'active_device_days')::integer)
                    END, 7)))
      INTO STRICT v_cutoff
      FROM operations.devices device
      LEFT JOIN operations.clients client ON client.tenant_id = device.tenant_id AND client.id = device.client_id
      LEFT JOIN operations.evaluator_config config
        ON config.tenant_id = device.tenant_id AND config.evaluator_name = 'device_status'
     WHERE device.tenant_id = p_tenant AND device.id = p_survivor;

    WITH reports AS MATERIALIZED (
        SELECT subject.id, subject.association_version, observation.device_id, observation.active,
               operation.offline, operation.serial, operation.macs,
               CASE WHEN operation.contact ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
                         AND pg_input_is_valid(operation.contact, 'timestamp with time zone')
                    THEN operation.contact::timestamptz END AS contact
          FROM operations.source_record_subjects subject
          JOIN operations.entity_observation_current observation
            ON observation.tenant_id = subject.tenant_id AND observation.observation_id = subject.observation_id
          JOIN operations.entity_source_links link
            ON link.tenant_id = subject.tenant_id AND link.source_subject_id = subject.id
           AND link.entity_class_id = 'device'
          JOIN operations.devices device
            ON device.tenant_id = link.tenant_id AND device.entity_id = link.entity_id
           AND device.id = observation.device_id
          JOIN operations.source_instances instance
            ON instance.tenant_id = link.tenant_id AND instance.id = link.source_instance_id
          JOIN operations.sources source ON source.id = instance.source_id AND source.name = 'Ninja'
          CROSS JOIN LATERAL (
              SELECT (NOT observation.active OR observation.canonical_data -> 'is_online' = 'false'::jsonb
                      OR observation.canonical_data -> 'offline' = 'true'::jsonb) AS offline,
                     lower(btrim(observation.canonical_data ->> 'serial_number')) AS serial,
                     observation.canonical_data -> 'macs' AS macs,
                     observation.canonical_data ->> 'last_contact_at' AS contact
          ) operation
         WHERE subject.tenant_id = p_tenant AND subject.subject_kind = 'record'
           AND observation.device_id IN (p_survivor, p_absorbed) AND observation.platform = 'Ninja'
           AND NOT operations.is_companion_stream(subject.tenant_id, subject.source_instance_id,
                                                   subject.external_namespace)
           AND NOT operations.ninja_record_excluded_from_computer(p_tenant, p_survivor, observation.entity_key)
           AND NOT EXISTS (
               SELECT 1 FROM operations.identity_roaming_records roaming
                WHERE roaming.tenant_id = subject.tenant_id AND roaming.source_instance_id = subject.source_instance_id
                  AND roaming.external_id = subject.external_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM operations.entity_source_link_history history
                WHERE history.tenant_id = subject.tenant_id AND history.source_instance_id = subject.source_instance_id
                  AND history.external_namespace = subject.external_namespace
                  AND history.parent_external_namespace = subject.parent_external_namespace
                  AND history.parent_external_id = subject.parent_external_id
                  AND history.external_id = subject.external_id AND history.effective_to IS NULL
                  AND history.actor_kind IN ('operator', 'user')
           )
    ), hardware AS (
        SELECT reports.id, lower(translate(address.value, ':- ', '')) AS mac
          FROM reports
          CROSS JOIN LATERAL jsonb_array_elements_text(
              CASE WHEN jsonb_typeof(reports.macs) = 'array' THEN reports.macs ELSE '[]'::jsonb END
          ) AS address(value)
         WHERE btrim(address.value) ~* '^([0-9a-f]{12}|[0-9a-f]{2}([:-][0-9a-f]{2}){5})$'
    )
    SELECT older.id AS old_id, older.device_id AS old_device,
           older.association_version AS old_version, successor.id AS new_id
      INTO chosen
      FROM reports older
      JOIN reports successor ON successor.device_id <> older.device_id
       AND successor.serial = older.serial AND successor.contact > older.contact
     WHERE older.offline AND successor.active
       AND (successor.offline IS NOT TRUE OR NOT older.active OR older.contact < v_cutoff)
       AND extract(year FROM older.contact) > 1
       AND successor.contact >= v_cutoff
       AND length(older.serial) >= 4 AND older.serial <> repeat(left(older.serial, 1), length(older.serial))
       AND NOT EXISTS (
           SELECT 1 FROM operations.identity_value_rejections rejection
            WHERE rejection.enabled AND rejection.value_kind = 'serial' AND rejection.normalized_value = older.serial
       )
       AND EXISTS (
           SELECT 1 FROM hardware previous
           JOIN hardware new_mac ON new_mac.mac = previous.mac AND new_mac.id = successor.id
            WHERE previous.id = older.id AND previous.mac NOT IN ('000000000000', 'ffffffffffff', '02004c4f4f50')
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Current Ninja contact and hardware evidence do not establish a successor';
    END IF;

    v_version := operations.set_source_association(
        chosen.old_id, NULL, 'device', 'ninja_superseded', 1, v_action.reason,
        chosen.old_version, 'system', v_action.actor_id, 'operations.cross_client_repair',
        jsonb_build_object('successor_record_id', chosen.new_id, 'action_id', p_action)
    );
    IF v_version IS DISTINCT FROM chosen.old_version + 1 THEN
        RAISE EXCEPTION 'The historical Ninja association did not close';
    END IF;
    INSERT INTO operations.ninja_record_supersessions
        (tenant_id, source_record_id, successor_record_id, computer_id, action_id)
    VALUES (p_tenant, chosen.old_id, chosen.new_id, p_survivor, p_action);
    RETURN jsonb_build_object('subject_id', chosen.old_id, 'association_version', v_version,
                              'closed_from', chosen.old_device, 'successor_id', chosen.new_id);
END
$fn$;
ALTER FUNCTION operations.close_cross_client_ninja_predecessor(bigint, uuid, uuid, uuid)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.close_cross_client_ninja_predecessor(bigint, uuid, uuid, uuid)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
"""

REVERSE_SQL = """
LOCK TABLE operations.ninja_record_supersessions IN ACCESS EXCLUSIVE MODE;
ALTER TABLE operations.ninja_record_supersessions NO FORCE ROW LEVEL SECURITY;
SET LOCAL row_security = off;
DO $fn$
BEGIN
    IF EXISTS (SELECT 1 FROM operations.ninja_record_supersessions) THEN
        RAISE EXCEPTION 'Ninja supersession history must be preserved before rollback';
    END IF;
END
$fn$;
DROP FUNCTION operations.supersede_ninja_computer_record(bigint, uuid, uuid, uuid, uuid, bigint, bigint, bigint, bigint, uuid);
DROP FUNCTION operations.close_cross_client_ninja_predecessor(bigint, uuid, uuid, uuid);
DROP TRIGGER reject_superseded_ninja_link ON operations.entity_source_links;
DROP FUNCTION operations.reject_superseded_ninja_link();
DROP FUNCTION operations.ninja_computer_slot_occupied(bigint, uuid, uuid, text, text, text, text);
DROP FUNCTION operations.ninja_record_excluded_from_computer(bigint, uuid, text);
DROP FUNCTION operations.ninja_record_is_superseded(bigint, uuid, text, text, text, text);
DROP TABLE operations.ninja_record_supersessions;
DELETE FROM operations.change_history_registry WHERE table_name = 'ninja_record_supersessions';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0431_preserve_repair_finding_scope"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
