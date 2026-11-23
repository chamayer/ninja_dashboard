"""Allow the resolver to reverse a provably incorrect legacy serial merge."""

from typing import ClassVar

from django.db import migrations

SQL = r"""
CREATE VIEW operations.v_reversible_serial_merges AS
WITH records AS (
    SELECT merge.tenant_id, merge.id AS merge_id, merge.survivor_id, merge.absorbed_id,
           merge.merged_at, observation.observation_id = ANY(merge.moved_observation_ids) AS moved,
           merge.moved_observation_ids, merge.moved_link_ids, survivor.entity_id AS survivor_entity,
           subject.id, subject.input_version, subject.association_version,
           observation.canonical_data AS facts,
           lower(btrim(observation.raw_data -> 'system' ->> 'manufacturer')) AS manufacturer,
           lower(btrim(observation.raw_data -> 'system' ->> 'model')) AS model,
           merge.evidence ->> 'serial' AS merge_serial,
           absorbed.entity_id AS absorbed_entity,
           subject.source_instance_id, subject.external_namespace, subject.external_id,
           subject.parent_external_namespace, subject.parent_external_id,
           count(*) OVER (PARTITION BY merge.tenant_id, merge.id) AS primary_records
      FROM operations.computer_merges merge
      JOIN operations.change_actions action
        ON action.tenant_id = merge.tenant_id AND action.id = merge.action_id
       AND action.action = 'computer.merge.automatic'
      JOIN operations.devices survivor
        ON survivor.tenant_id = merge.tenant_id AND survivor.id = merge.survivor_id
      JOIN operations.devices absorbed
        ON absorbed.tenant_id = merge.tenant_id AND absorbed.id = merge.absorbed_id
      JOIN operations.entity_source_links link
        ON link.tenant_id = survivor.tenant_id AND link.entity_id = survivor.entity_id
       AND link.entity_class_id = 'device'
      JOIN operations.source_record_subjects subject
        ON subject.tenant_id = link.tenant_id AND subject.id = link.source_subject_id
      JOIN operations.entity_observation_current observation
        ON observation.tenant_id = subject.tenant_id AND observation.observation_id = subject.observation_id
       AND observation.device_id = survivor.id
     WHERE merge.tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint
       AND merge.split_at IS NULL AND merge.evidence ? 'serial'
       AND cardinality(merge.moved_observation_ids) > 0
       AND survivor.deleted_at IS NULL AND survivor.lifecycle_status <> 'retired'
       AND absorbed.deleted_at IS NOT NULL AND absorbed.deleted_reason = 'merged'
       AND survivor.client_id = merge.client_id AND absorbed.client_id = merge.client_id
       AND observation.platform = 'Ninja' AND subject.subject_kind = 'record'
       AND NOT operations.is_companion_stream(link.tenant_id, link.source_instance_id, link.external_namespace)
       AND operations.computer_client_independent_evidence(subject.tenant_id, observation.observation_id)
           = merge.client_id
       AND NOT EXISTS (
           SELECT 1 FROM operations.entity_source_links other
            WHERE other.tenant_id = absorbed.tenant_id AND other.entity_id = absorbed.entity_id
       )
       AND NOT EXISTS (
           SELECT 1 FROM operations.device_operator_decisions decision
            WHERE decision.tenant_id = merge.tenant_id
              AND decision.device_id IN (merge.survivor_id, merge.absorbed_id)
              AND decision.set_at >= merge.merged_at
       )
       AND NOT EXISTS (
           SELECT 1 FROM operations.computer_merges newer
            WHERE newer.tenant_id = merge.tenant_id AND newer.id <> merge.id
              AND newer.merged_at >= merge.merged_at
              AND (newer.absorbed_id IN (merge.survivor_id, merge.absorbed_id)
                   OR newer.survivor_id IN (merge.survivor_id, merge.absorbed_id))
       )
       AND NOT EXISTS (
           SELECT 1 FROM operations.entity_source_link_history history
            WHERE history.tenant_id = subject.tenant_id
              AND history.source_instance_id = subject.source_instance_id
              AND history.external_namespace = subject.external_namespace
              AND history.external_id = subject.external_id
              AND history.parent_external_namespace = subject.parent_external_namespace
              AND history.parent_external_id = subject.parent_external_id
              AND history.effective_from >= merge.merged_at
              AND history.actor_kind IN ('operator', 'user')
       )
       AND observation.active
)
SELECT old.tenant_id, old.merge_id, old.survivor_id, old.absorbed_id, old.merged_at,
       old.id AS old_id, old.input_version AS old_input, old.association_version AS old_association,
       kept.id AS kept_id, kept.input_version AS kept_input, kept.association_version AS kept_association,
       recovery.membership
  FROM records old
  JOIN records kept ON old.tenant_id = kept.tenant_id AND old.merge_id = kept.merge_id AND NOT kept.moved
 CROSS JOIN LATERAL (
     SELECT jsonb_agg(jsonb_build_object(
                'observation_id', observation.observation_id, 'subject_id', subject.id, 'link_id', link.id,
                'input_version', subject.input_version, 'association_version', subject.association_version
            ) ORDER BY observation.observation_id) AS membership
       FROM unnest(old.moved_observation_ids) audit(observation_id)
       JOIN operations.entity_observation_current observation
         ON observation.tenant_id = old.tenant_id AND observation.observation_id = audit.observation_id
       LEFT JOIN operations.source_record_subjects subject
         ON subject.tenant_id = observation.tenant_id AND subject.observation_id = observation.observation_id
        AND subject.subject_kind = 'record'
       LEFT JOIN operations.entity_source_links link
         ON link.tenant_id = observation.tenant_id AND link.source_instance_id = observation.source_instance_id
        AND link.external_namespace = observation.external_namespace AND link.external_id = observation.external_id
        AND link.parent_external_namespace = observation.parent_external_namespace
        AND link.parent_external_id = observation.parent_external_id
      WHERE ((link.entity_id = old.survivor_entity AND link.entity_class_id = 'device'
              AND link.source_subject_id = subject.id AND observation.device_id = old.survivor_id)
             OR (link.id IS NULL AND observation.device_id IS NULL))
        AND EXISTS (
            SELECT 1 FROM operations.entity_source_link_history history
             WHERE history.tenant_id = observation.tenant_id AND history.entity_id = old.absorbed_entity
               AND history.source_instance_id = observation.source_instance_id
               AND history.external_namespace = observation.external_namespace AND history.external_id = observation.external_id
               AND history.parent_external_namespace = observation.parent_external_namespace
               AND history.parent_external_id = observation.parent_external_id
               AND history.effective_from <= old.merged_at AND history.effective_to IS NOT NULL
        )
        AND NOT EXISTS (
            SELECT 1 FROM operations.entity_source_link_history history
             WHERE history.tenant_id = observation.tenant_id
               AND history.source_instance_id = observation.source_instance_id
               AND history.external_namespace = observation.external_namespace AND history.external_id = observation.external_id
               AND history.parent_external_namespace = observation.parent_external_namespace
               AND history.parent_external_id = observation.parent_external_id
               AND history.effective_from > old.merged_at
               AND (history.actor_kind IN ('operator', 'user')
                    OR history.entity_id NOT IN (old.absorbed_entity, old.survivor_entity))
        )
      HAVING count(DISTINCT observation.observation_id) = cardinality(old.moved_observation_ids)
         AND count(*) = cardinality(old.moved_observation_ids)
         AND count(*) FILTER (
             WHERE link.id IS NOT NULL AND observation.platform = 'Ninja'
               AND NOT operations.is_companion_stream(
                   link.tenant_id, link.source_instance_id, link.external_namespace)
         ) = 1
 ) recovery
 WHERE old.moved AND old.primary_records = 2
   AND NOT EXISTS (
       SELECT 1 FROM operations.entity_source_links audited_link
        WHERE audited_link.tenant_id = old.tenant_id AND audited_link.id = ANY(old.moved_link_ids)
          AND NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(recovery.membership) member
               WHERE member->>'link_id' = audited_link.id::text
          )
   )
   AND old.manufacturer <> '' AND old.manufacturer = kept.manufacturer
   AND old.model <> '' AND kept.model <> '' AND old.model <> kept.model
   AND old.facts ->> 'is_vm' = 'false' AND kept.facts ->> 'is_vm' = 'false'
   AND lower(btrim(old.facts ->> 'serial_number')) = lower(btrim(old.merge_serial))
   AND lower(btrim(kept.facts ->> 'serial_number')) = lower(btrim(old.merge_serial))
   AND old.facts ->> 'offline' = 'false' AND kept.facts ->> 'offline' = 'false'
   AND old.facts ->> 'last_contact_at' IS NOT NULL AND kept.facts ->> 'last_contact_at' IS NOT NULL
   AND EXISTS (
       SELECT 1
         FROM operations.entity_observation_history old_report
         JOIN operations.entity_observation_history kept_report
           ON kept_report.tenant_id = old_report.tenant_id
          AND kept_report.source_instance_id = kept.source_instance_id
          AND kept_report.external_namespace = kept.external_namespace
          AND kept_report.external_id = kept.external_id
          AND kept_report.parent_external_namespace = kept.parent_external_namespace
          AND kept_report.parent_external_id = kept.parent_external_id
          AND kept_report.active AND kept_report.material_data ->> 'offline' = 'false'
          AND tstzrange(kept_report.effective_from, kept_report.effective_to)
              && tstzrange(old_report.effective_from, old_report.effective_to)
        WHERE old_report.tenant_id = old.tenant_id
          AND old_report.source_instance_id = old.source_instance_id
          AND old_report.external_namespace = old.external_namespace
          AND old_report.external_id = old.external_id
          AND old_report.parent_external_namespace = old.parent_external_namespace
          AND old_report.parent_external_id = old.parent_external_id
          AND old_report.active AND old_report.material_data ->> 'offline' = 'false'
          AND old_report.effective_from >= old.merged_at
          AND kept_report.effective_from >= old.merged_at
          AND old_report.effective_to IS NOT NULL AND kept_report.effective_to IS NOT NULL
   )
   AND EXISTS (
       SELECT 1 FROM operations.entity_source_link_history history
        WHERE history.tenant_id = old.tenant_id AND history.entity_id = old.absorbed_entity
          AND history.source_instance_id = old.source_instance_id
          AND history.external_namespace = old.external_namespace
          AND history.external_id = old.external_id
          AND history.parent_external_namespace = old.parent_external_namespace
          AND history.parent_external_id = old.parent_external_id
          AND history.effective_from <= old.merged_at AND history.effective_to IS NOT NULL
   )
   AND EXISTS (
       SELECT 1 FROM jsonb_array_elements_text(
           CASE WHEN jsonb_typeof(old.facts -> 'macs') = 'array' THEN old.facts -> 'macs' ELSE '[]' END
       ) mac(value) WHERE regexp_replace(lower(mac.value), '[^0-9a-f]', '', 'g')
                           ~ '^[0-9a-f][048c][0-9a-f]{10}$'
   )
   AND EXISTS (
       SELECT 1 FROM jsonb_array_elements_text(
           CASE WHEN jsonb_typeof(kept.facts -> 'macs') = 'array' THEN kept.facts -> 'macs' ELSE '[]' END
       ) mac(value) WHERE regexp_replace(lower(mac.value), '[^0-9a-f]', '', 'g')
                           ~ '^[0-9a-f][048c][0-9a-f]{10}$'
   )
   AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements_text(
           CASE WHEN jsonb_typeof(old.facts -> 'macs') = 'array' THEN old.facts -> 'macs' ELSE '[]' END
       ) old_mac(value)
       JOIN jsonb_array_elements_text(
           CASE WHEN jsonb_typeof(kept.facts -> 'macs') = 'array' THEN kept.facts -> 'macs' ELSE '[]' END
       ) kept_mac(value) ON regexp_replace(lower(old_mac.value), '[^0-9a-f]', '', 'g')
                           = regexp_replace(lower(kept_mac.value), '[^0-9a-f]', '', 'g')
   );
ALTER VIEW operations.v_reversible_serial_merges OWNER TO operations_migrate;
REVOKE ALL ON operations.v_reversible_serial_merges
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT SELECT ON operations.v_reversible_serial_merges TO ninja_ingest;

CREATE FUNCTION operations.reverse_legacy_serial_merge(
    p_tenant bigint, p_merge uuid, p_old uuid, p_old_input bigint, p_old_association bigint,
    p_kept uuid, p_kept_input bigint, p_kept_association bigint, p_membership jsonb
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_absorbed_entity uuid;
    v_survivor_entity uuid;
    v_link_entity uuid;
    v_link_subject uuid;
    v_version bigint;
    member record;
BEGIN
    PERFORM operations.assert_tenant_guard(p_tenant, 'exclusive');
    IF p_tenant IS DISTINCT FROM nullif(current_setting('operations.tenant_id', true), '')::bigint THEN
        RETURN false;
    END IF;
    PERFORM id FROM operations.source_record_subjects
     WHERE tenant_id = p_tenant AND (
         id IN (p_old, p_kept)
         OR id IN (SELECT subject_id FROM jsonb_to_recordset(p_membership) AS m(subject_id uuid))
     )
     ORDER BY id FOR UPDATE;
    IF NOT EXISTS (
        SELECT 1 FROM operations.v_reversible_serial_merges candidate
         WHERE candidate.tenant_id = p_tenant AND candidate.merge_id = p_merge
           AND (candidate.old_id, candidate.old_input, candidate.old_association)
               = (p_old, p_old_input, p_old_association)
           AND (candidate.kept_id, candidate.kept_input, candidate.kept_association)
               = (p_kept, p_kept_input, p_kept_association)
           AND candidate.membership = p_membership
    ) THEN
        RETURN false;
    END IF;
    PERFORM operations.split_computer_merge(
        p_merge, 'Legacy serial merge reversed after two current Ninja records proved distinct hardware',
        'process', NULL, 'ingest.identity.resolver');
    SELECT absorbed.entity_id, survivor.entity_id INTO STRICT v_absorbed_entity, v_survivor_entity
      FROM operations.computer_merges audit
      JOIN operations.devices absorbed ON absorbed.tenant_id = audit.tenant_id AND absorbed.id = audit.absorbed_id
      JOIN operations.devices survivor ON survivor.tenant_id = audit.tenant_id AND survivor.id = audit.survivor_id
     WHERE audit.tenant_id = p_tenant AND audit.id = p_merge AND audit.split_at IS NOT NULL;
    FOR member IN
        SELECT * FROM jsonb_to_recordset(p_membership) AS item(
            subject_id uuid, link_id uuid, association_version bigint)
         WHERE link_id IS NOT NULL
         ORDER BY subject_id
    LOOP
        SELECT link.entity_id, link.source_subject_id INTO STRICT v_link_entity, v_link_subject
          FROM operations.entity_source_links link
         WHERE link.tenant_id = p_tenant AND link.id = member.link_id AND link.entity_class_id = 'device';
        IF v_link_subject IS DISTINCT FROM member.subject_id THEN
            RAISE EXCEPTION 'The source association changed while reversing the legacy merge';
        END IF;
        IF v_link_entity = v_absorbed_entity THEN
            CONTINUE;
        END IF;
        IF v_link_entity IS DISTINCT FROM v_survivor_entity THEN
            RAISE EXCEPTION 'The source association no longer belongs to the legacy merge';
        END IF;
        v_version := operations.set_source_association(
            member.subject_id, v_absorbed_entity, 'device', 'split', 1,
            'Restore audited membership from before the legacy serial merge', member.association_version,
            'process', NULL, 'ingest.identity.resolver', jsonb_build_object('merge_id', p_merge));
        IF v_version IS DISTINCT FROM member.association_version + 1 THEN
            RAISE EXCEPTION 'Automatic reversal did not restore the audited membership';
        END IF;
    END LOOP;
    IF NOT EXISTS (
        SELECT 1 FROM operations.computer_merges audit
        JOIN operations.devices device
          ON device.tenant_id = audit.tenant_id AND device.id = audit.absorbed_id
        JOIN operations.entity_source_links link
          ON link.tenant_id = device.tenant_id AND link.entity_id = device.entity_id
         AND link.source_subject_id = p_old
        WHERE audit.tenant_id = p_tenant AND audit.id = p_merge
          AND audit.split_at IS NOT NULL AND device.deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Automatic reversal did not restore the recorded source association';
    END IF;
    RETURN true;
END
$fn$;
ALTER FUNCTION operations.reverse_legacy_serial_merge(bigint, uuid, uuid, bigint, bigint, uuid, bigint, bigint, jsonb)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.reverse_legacy_serial_merge(bigint, uuid, uuid, bigint, bigint, uuid, bigint, bigint, jsonb)
    FROM PUBLIC, operations_app, operations_readonly, ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.reverse_legacy_serial_merge(bigint, uuid, uuid, bigint, bigint, uuid, bigint, bigint, jsonb)
    TO ninja_ingest;
"""

REVERSE_SQL = """
DROP FUNCTION operations.reverse_legacy_serial_merge(bigint, uuid, uuid, bigint, bigint, uuid, bigint, bigint, jsonb);
DROP VIEW operations.v_reversible_serial_merges;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0433_source_installation_identity"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(SQL, REVERSE_SQL)]
