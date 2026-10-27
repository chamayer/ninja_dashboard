from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
CREATE FUNCTION operations.sync_entity_candidates_v2(batch_size integer DEFAULT 500)
RETURNS TABLE(created integer, reopened integer, attached integer, withdrawn integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    withdrawn_batch integer;
BEGIN
    IF batch_size < 1 OR batch_size > 10000 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 10000';
    END IF;
    created := 0; reopened := 0; attached := 0; withdrawn := 0;

    WITH eligible AS (
        SELECT observation.*, entity_type.entity_class_id,
               CASE WHEN COALESCE(bool_or(
                    policy.enabled AND policy.may_establish_identity
               ), FALSE) THEN 'pending' ELSE 'observed_only' END AS desired_status
          FROM entity_observation_current observation
          JOIN entity_types entity_type ON entity_type.name = observation.entity_type
          LEFT JOIN identity_authority_policies policy
            ON policy.tenant_id = observation.tenant_id
           AND policy.source_instance_id = observation.source_instance_id
           AND policy.native_record_type = observation.entity_type
           AND policy.resulting_entity_type_id = entity_type.name
         WHERE observation.active
           AND NOT EXISTS (
               SELECT 1 FROM entity_source_links link
                WHERE link.tenant_id = observation.tenant_id
                  AND link.source_instance_id = observation.source_instance_id
                  AND link.external_namespace = observation.external_namespace
                  AND link.parent_external_namespace = observation.parent_external_namespace
                  AND link.parent_external_id = observation.parent_external_id
                  AND link.external_id = observation.external_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM entity_candidates candidate
                WHERE candidate.tenant_id = observation.tenant_id
                  AND candidate.source_instance_id = observation.source_instance_id
                  AND candidate.external_namespace = observation.external_namespace
                  AND candidate.parent_external_namespace = observation.parent_external_namespace
                  AND candidate.parent_external_id = observation.parent_external_id
                  AND candidate.external_id = observation.external_id
                  AND candidate.proposed_entity_class_id = entity_type.entity_class_id
           )
         GROUP BY observation.observation_id, entity_type.entity_class_id
         ORDER BY observation.last_seen_at, observation.observation_id
         LIMIT batch_size
    ), inserted AS (
        INSERT INTO entity_candidates (
            id, tenant_id, version, source_instance_id, proposed_entity_class_id,
            client_id, external_namespace, parent_external_namespace,
            parent_external_id, external_id, status, material_hash,
            latest_decision, latest_decision_reason,
            first_observed_at, last_observed_at
        )
        SELECT gen_random_uuid(), eligible.tenant_id, 1, eligible.source_instance_id,
               eligible.entity_class_id, eligible.client_id,
               eligible.external_namespace, eligible.parent_external_namespace,
               eligible.parent_external_id, eligible.external_id,
               eligible.desired_status, eligible.material_hash, '', '',
               eligible.observed_at, eligible.last_seen_at
          FROM eligible
        ON CONFLICT (tenant_id, source_instance_id, external_namespace,
                     parent_external_namespace, parent_external_id, external_id,
                     proposed_entity_class_id) DO NOTHING
        RETURNING *
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), inserted.tenant_id, 1, inserted.id,
               'create', 'system', 'generic_candidate_projector',
               'unattached source identity', NULL,
               jsonb_build_object('status', inserted.status), clock_timestamp()
          FROM inserted RETURNING 1
    ) SELECT count(*)::integer INTO created FROM events;

    -- An authoritative source link of another class supersedes this proposal.
    WITH changed AS (
        SELECT candidate.id, candidate.tenant_id, candidate.status AS old_status
          FROM entity_candidates candidate
          JOIN entity_source_links link
            ON link.tenant_id = candidate.tenant_id
           AND link.source_instance_id = candidate.source_instance_id
           AND link.external_namespace = candidate.external_namespace
           AND link.parent_external_namespace = candidate.parent_external_namespace
           AND link.parent_external_id = candidate.parent_external_id
           AND link.external_id = candidate.external_id
         WHERE candidate.status IN ('observed_only', 'pending')
           AND link.entity_class_id <> candidate.proposed_entity_class_id
         ORDER BY candidate.id LIMIT batch_size
    ), updated AS (
        UPDATE entity_candidates candidate
           SET status = 'withdrawn', version = candidate.version + 1
          FROM changed WHERE candidate.id = changed.id AND candidate.status = changed.old_status
        RETURNING candidate.*, changed.old_status
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), updated.tenant_id, 1, updated.id,
               'withdraw', 'system', 'generic_candidate_projector',
               'stable source identity is linked to a different entity class',
               jsonb_build_object('status', updated.old_status),
               jsonb_build_object('status', updated.status), clock_timestamp()
          FROM updated RETURNING 1
    ) SELECT count(*)::integer INTO withdrawn_batch FROM events;
    withdrawn := withdrawn + withdrawn_batch;

    -- An explicitly inactive, unlinked observation withdraws only its queue proposal.
    WITH changed AS (
        SELECT DISTINCT candidate.id, candidate.tenant_id, candidate.status AS old_status
          FROM entity_candidates candidate
          JOIN entity_types entity_type
            ON entity_type.entity_class_id = candidate.proposed_entity_class_id
          JOIN entity_observation_current observation
            ON observation.tenant_id = candidate.tenant_id
           AND observation.source_instance_id = candidate.source_instance_id
           AND observation.external_namespace = candidate.external_namespace
           AND observation.parent_external_namespace = candidate.parent_external_namespace
           AND observation.parent_external_id = candidate.parent_external_id
           AND observation.external_id = candidate.external_id
           AND observation.entity_type = entity_type.name
           AND NOT observation.active
         WHERE candidate.status IN ('observed_only', 'pending')
           AND NOT EXISTS (
               SELECT 1 FROM entity_source_links link
                WHERE link.tenant_id = candidate.tenant_id
                  AND link.source_instance_id = candidate.source_instance_id
                  AND link.external_namespace = candidate.external_namespace
                  AND link.parent_external_namespace = candidate.parent_external_namespace
                  AND link.parent_external_id = candidate.parent_external_id
                  AND link.external_id = candidate.external_id
           )
         ORDER BY candidate.id LIMIT batch_size
    ), updated AS (
        UPDATE entity_candidates candidate
           SET status = 'withdrawn', version = candidate.version + 1
          FROM changed WHERE candidate.id = changed.id AND candidate.status = changed.old_status
        RETURNING candidate.*, changed.old_status
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), updated.tenant_id, 1, updated.id,
               'withdraw', 'system', 'generic_candidate_projector',
               'source observation is inactive and no source link exists',
               jsonb_build_object('status', updated.old_status),
               jsonb_build_object('status', updated.status), clock_timestamp()
          FROM updated RETURNING 1
    ) SELECT count(*)::integer INTO withdrawn_batch FROM events;
    withdrawn := withdrawn + withdrawn_batch;

    WITH changed AS (
        SELECT candidate.id, candidate.tenant_id, candidate.status AS old_status,
               observation.material_hash, observation.last_seen_at,
               CASE WHEN COALESCE(bool_or(
                    policy.enabled AND policy.may_establish_identity
               ), FALSE) THEN 'pending' ELSE 'observed_only' END AS desired_status
          FROM entity_candidates candidate
          JOIN entity_observation_current observation
            ON observation.tenant_id = candidate.tenant_id
           AND observation.source_instance_id = candidate.source_instance_id
           AND observation.external_namespace = candidate.external_namespace
           AND observation.parent_external_namespace = candidate.parent_external_namespace
           AND observation.parent_external_id = candidate.parent_external_id
           AND observation.external_id = candidate.external_id
          JOIN entity_types entity_type
            ON entity_type.name = observation.entity_type
           AND entity_type.entity_class_id = candidate.proposed_entity_class_id
          LEFT JOIN identity_authority_policies policy
            ON policy.tenant_id = observation.tenant_id
           AND policy.source_instance_id = observation.source_instance_id
           AND policy.native_record_type = observation.entity_type
           AND policy.resulting_entity_type_id = entity_type.name
         WHERE observation.active
           AND candidate.status IN ('observed_only', 'pending', 'withdrawn')
           AND NOT EXISTS (
               SELECT 1 FROM entity_source_links link
                WHERE link.tenant_id = candidate.tenant_id
                  AND link.source_instance_id = candidate.source_instance_id
                  AND link.external_namespace = candidate.external_namespace
                  AND link.parent_external_namespace = candidate.parent_external_namespace
                  AND link.parent_external_id = candidate.parent_external_id
                  AND link.external_id = candidate.external_id
           )
           AND (candidate.status = 'withdrawn'
                OR candidate.material_hash IS DISTINCT FROM observation.material_hash)
         GROUP BY candidate.id, candidate.tenant_id, candidate.status,
                  observation.material_hash, observation.last_seen_at
         ORDER BY observation.last_seen_at, candidate.id LIMIT batch_size
    ), updated AS (
        UPDATE entity_candidates candidate
           SET status = changed.desired_status,
               material_hash = changed.material_hash,
               last_observed_at = changed.last_seen_at,
               version = candidate.version + 1
          FROM changed WHERE candidate.id = changed.id AND candidate.status = changed.old_status
        RETURNING candidate.*, changed.old_status
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), updated.tenant_id, 1, updated.id,
               'reopen', 'system', 'generic_candidate_projector',
               CASE WHEN updated.old_status = 'withdrawn'
                    THEN 'source observation became active'
                    ELSE 'material source evidence changed' END,
               jsonb_build_object('status', updated.old_status),
               jsonb_build_object('status', updated.status), clock_timestamp()
          FROM updated RETURNING 1
    ) SELECT count(*)::integer INTO reopened FROM events;

    WITH linked AS (
        SELECT candidate.id, candidate.tenant_id, candidate.status AS old_status,
               link.entity_id
          FROM entity_candidates candidate
          JOIN entity_source_links link
            ON link.tenant_id = candidate.tenant_id
           AND link.source_instance_id = candidate.source_instance_id
           AND link.external_namespace = candidate.external_namespace
           AND link.parent_external_namespace = candidate.parent_external_namespace
           AND link.parent_external_id = candidate.parent_external_id
           AND link.external_id = candidate.external_id
           AND link.entity_class_id = candidate.proposed_entity_class_id
         WHERE candidate.status IN ('observed_only', 'pending', 'withdrawn')
         ORDER BY candidate.id LIMIT batch_size
    ), updated AS (
        UPDATE entity_candidates candidate
           SET status = 'attached', resolved_entity_id = linked.entity_id,
               latest_decision = 'attached',
               latest_decision_reason = 'authoritative source link exists',
               latest_decided_at = clock_timestamp(),
               version = candidate.version + 1
          FROM linked WHERE candidate.id = linked.id AND candidate.status = linked.old_status
        RETURNING candidate.*, linked.old_status
    ), events AS (
        INSERT INTO entity_candidate_events (
            id, tenant_id, version, candidate_id, action, actor_kind,
            actor_process, reason, before_state, after_state, occurred_at
        )
        SELECT gen_random_uuid(), updated.tenant_id, 1, updated.id,
               'attach', 'system', 'generic_candidate_projector',
               'authoritative source link exists with matching entity class',
               jsonb_build_object('status', updated.old_status),
               jsonb_build_object('status', 'attached'), clock_timestamp()
          FROM updated RETURNING 1
    ) SELECT count(*)::integer INTO attached FROM events;
    RETURN NEXT;
END;
$function$;
REVOKE ALL ON FUNCTION operations.sync_entity_candidates_v2(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.sync_entity_candidates_v2(integer)
    TO ninja_ingest, operations_app;
ALTER FUNCTION operations.sync_entity_candidates_v2(integer) OWNER TO operations_migrate;

-- Keep the three-column entry point safe for an older ingest process during
-- service startup and rollback. Fold withdrawal work into its progress count.
CREATE OR REPLACE FUNCTION operations.sync_entity_candidates(batch_size integer DEFAULT 500)
RETURNS TABLE(created integer, reopened integer, attached integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    projection_result record;
    projection_rounds integer := 0;
BEGIN
    created := 0; reopened := 0; attached := 0;
    LOOP
        SELECT * INTO projection_result
          FROM operations.sync_entity_candidates_v2(batch_size);
        created := created + projection_result.created;
        reopened := reopened + projection_result.reopened;
        attached := attached + projection_result.attached;
        projection_rounds := projection_rounds + 1;
        EXIT WHEN projection_result.created + projection_result.reopened
                  + projection_result.attached + projection_result.withdrawn = 0
                  OR projection_rounds >= 100;
    END LOOP;
    RETURN NEXT;
END;
$function$;
REVOKE ALL ON FUNCTION operations.sync_entity_candidates(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.sync_entity_candidates(integer)
    TO ninja_ingest, operations_app;
ALTER FUNCTION operations.sync_entity_candidates(integer) OWNER TO operations_migrate;
"""

REVERSE_SQL = r"""
-- Retain both compatible projector entry points: withdrawn rows may already
-- exist, and the three-column wrapper protects older ingest during rollback.
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0354_software_installation_display_name"),
    ]

    operations: ClassVar[list] = [
        migrations.AlterField(
            model_name="entitycandidate",
            name="status",
            field=models.CharField(
                choices=[
                    ("observed_only", "Observed only"),
                    ("pending", "Pending"),
                    ("attached", "Attached"),
                    ("rejected", "Rejected"),
                    ("withdrawn", "Withdrawn"),
                ],
                default="observed_only",
                max_length=24,
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
