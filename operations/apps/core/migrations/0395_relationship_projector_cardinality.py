"""Let the relationship projector settle one-target sources instead of failing.

``os_installation_runs_on_computer`` allows one active Computer per OS
installation, and the tuple trigger raises when a second edge would become
active. The projector (0111) upserted a batch in one statement, so when an
installation's evidence moved to another Computer the new edge could be written
before the old one was demoted, and the whole batch failed. From 2026-10-21
every batch failed this way and the queue stopped draining.

For a source-cardinality-one type the projector now decides all tuples of a
source together: its other queued tuples and its current active, conflicting or
superseded edges join the batch. Demotions are written before activations. When
several targets still want to be active:

* a higher operator or source authority wins; the others are ``superseded``;
* at equal authority the current active edge stays active and the others are
  ``conflict`` (``targets_disagree``); with no current edge all are ``conflict``.

Only ``active`` edges are read by the Computer views, so a disagreement never
moves an installation on its own and never shows it on two Computers; the
conflicting rows stay visible in the relationship admin view.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations, models

_contracts = importlib.import_module(
    "apps.core.migrations.0111_relationship_candidate_event_contracts"
)


def _previous_function() -> str:
    sql = _contracts.PROJECTOR_SQL
    start = sql.index("CREATE OR REPLACE FUNCTION operations.sync_entity_relationships(")
    end = sql.index("$function$;", start) + len("$function$;")
    return sql[start:end] + "\n"


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.sync_entity_relationships(batch_size integer DEFAULT 500)
RETURNS TABLE(processed integer, relationship_writes integer, support_writes integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    projected_at timestamptz := clock_timestamp();
    joined integer;
    activated integer;
BEGIN
    IF batch_size < 1 OR batch_size > 10000 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 10000';
    END IF;
    CREATE TEMP TABLE relationship_projection_batch ON COMMIT DROP AS
    SELECT dirty.*
      FROM entity_relationship_dirty dirty
     ORDER BY dirty.queued_at, dirty.id
     LIMIT batch_size
     FOR UPDATE SKIP LOCKED;
    GET DIAGNOSTICS processed = ROW_COUNT;
    IF processed = 0 THEN
        relationship_writes := 0;
        support_writes := 0;
        RETURN NEXT;
        RETURN;
    END IF;

    -- A source of a one-target type is decided as a whole: its other queued
    -- tuples join the batch.
    INSERT INTO relationship_projection_batch
    SELECT dirty.*
      FROM entity_relationship_dirty dirty
     WHERE NOT EXISTS (SELECT 1 FROM relationship_projection_batch batch WHERE batch.id = dirty.id)
       AND EXISTS (
           SELECT 1 FROM relationship_projection_batch batch
             JOIN relationship_types contract ON contract.key = batch.relationship_type_id
            WHERE contract.source_cardinality = 'one'
              AND batch.tenant_id = dirty.tenant_id
              AND batch.relationship_type_id = dirty.relationship_type_id
              AND batch.source_entity_id = dirty.source_entity_id)
       FOR UPDATE OF dirty SKIP LOCKED;
    GET DIAGNOSTICS joined = ROW_COUNT;
    processed := processed + joined;

    -- ... and so do its current edges that hold or contest the one active slot.
    CREATE TEMP TABLE relationship_projection_tuples ON COMMIT DROP AS
    SELECT batch.tenant_id, batch.relationship_type_id,
           batch.source_entity_id, batch.target_entity_id
      FROM relationship_projection_batch batch
    UNION
    SELECT edge.tenant_id, edge.relationship_type_id,
           edge.source_entity_id, edge.target_entity_id
      FROM entity_relationships edge
      JOIN relationship_types contract
        ON contract.key = edge.relationship_type_id AND contract.source_cardinality = 'one'
     WHERE edge.status IN ('active', 'conflict', 'superseded')
       AND EXISTS (
           SELECT 1 FROM relationship_projection_batch batch
            WHERE batch.tenant_id = edge.tenant_id
              AND batch.relationship_type_id = edge.relationship_type_id
              AND batch.source_entity_id = edge.source_entity_id);

    CREATE TEMP TABLE desired_relationships ON COMMIT DROP AS
    WITH inputs AS (
        SELECT batch.tenant_id, batch.relationship_type_id,
               batch.source_entity_id, batch.target_entity_id,
               decision.id AS decision_id, decision.operation,
               evidence.authority_tier, evidence.authority_priority,
               evidence.evidence_ids
          FROM relationship_projection_tuples batch
          LEFT JOIN entity_relationship_decision_current decision
            ON decision.tenant_id = batch.tenant_id
           AND decision.relationship_type_id = batch.relationship_type_id
           AND decision.source_entity_id = batch.source_entity_id
           AND decision.target_entity_id = batch.target_entity_id
           AND decision.active
          LEFT JOIN LATERAL (
              WITH ranked AS (
                  SELECT item.*,
                         dense_rank() OVER (
                             ORDER BY item.authority_tier DESC,
                                      item.authority_priority DESC
                         ) AS authority_rank
                    FROM entity_relationship_evidence_current item
                   WHERE item.tenant_id = batch.tenant_id
                     AND item.relationship_type_id = batch.relationship_type_id
                     AND item.source_entity_id = batch.source_entity_id
                     AND item.target_entity_id = batch.target_entity_id
                     AND item.active AND item.authority_eligible
                     AND item.resolution_status = 'resolved'
              )
              SELECT MAX(authority_tier) AS authority_tier,
                     MAX(authority_priority) AS authority_priority,
                     string_agg(id::text, ',' ORDER BY id) AS evidence_ids
                FROM ranked WHERE authority_rank = 1
          ) evidence ON TRUE
    ), evaluated AS (
        SELECT inputs.*,
               CASE WHEN operation = 'include' THEN 'active'
                    WHEN operation = 'exclude' THEN 'suppressed'
                    WHEN evidence_ids IS NOT NULL THEN 'active'
                    ELSE 'no_evidence' END AS wanted_status,
               CASE WHEN operation = 'include' THEN 'operator_include'
                    WHEN operation = 'exclude' THEN 'operator_exclude'
                    WHEN evidence_ids IS NOT NULL THEN 'source_authority'
                    ELSE 'no_eligible_evidence' END AS wanted_reason,
               pg_catalog.sha256(convert_to(concat_ws('|',
                   COALESCE(decision_id::text, ''), COALESCE(operation, ''),
                   COALESCE(authority_tier::text, ''),
                   COALESCE(authority_priority::text, ''),
                   COALESCE(evidence_ids, '')
               ), 'UTF8')) AS input_hash
          FROM inputs
    ), contested AS (
        SELECT evaluated.*,
               contract.source_cardinality = 'one'
                   AND evaluated.wanted_status = 'active' AS single_slot,
               edge.status AS current_status
          FROM evaluated
          JOIN relationship_types contract ON contract.key = evaluated.relationship_type_id
          LEFT JOIN entity_relationships edge
            ON edge.tenant_id = evaluated.tenant_id
           AND edge.relationship_type_id = evaluated.relationship_type_id
           AND edge.source_entity_id = evaluated.source_entity_id
           AND edge.target_entity_id = evaluated.target_entity_id
    ), ranked AS (
        SELECT contested.*,
               rank() OVER (
                   PARTITION BY tenant_id, relationship_type_id, source_entity_id, single_slot
                   ORDER BY (operation IS NOT DISTINCT FROM 'include') DESC,
                            COALESCE(authority_tier, -1) DESC,
                            COALESCE(authority_priority, -1) DESC
               ) AS slot_rank
          FROM contested
    ), tallied AS (
        SELECT ranked.*,
               count(*) FILTER (WHERE slot_rank = 1) OVER slot AS leaders,
               count(*) FILTER (WHERE slot_rank = 1 AND current_status = 'active') OVER slot
                   AS active_leaders
          FROM ranked
        WINDOW slot AS (PARTITION BY tenant_id, relationship_type_id, source_entity_id, single_slot)
    )
    SELECT tenant_id, relationship_type_id, source_entity_id, target_entity_id,
           decision_id, operation, authority_tier, authority_priority, evidence_ids,
           input_hash,
           CASE WHEN NOT single_slot THEN wanted_status
                WHEN slot_rank > 1 THEN 'superseded'
                WHEN leaders = 1 THEN 'active'
                WHEN active_leaders = 1 AND current_status = 'active' THEN 'active'
                ELSE 'conflict' END AS status,
           CASE WHEN NOT single_slot THEN wanted_reason
                WHEN slot_rank > 1 THEN 'outranked_by_other_target'
                WHEN leaders = 1 THEN wanted_reason
                WHEN active_leaders = 1 AND current_status = 'active' THEN wanted_reason
                ELSE 'targets_disagree' END AS selection_reason
      FROM tallied;

    -- Demote first: the tuple trigger rejects a second active edge of a source.
    INSERT INTO entity_relationships (
        id, tenant_id, version, relationship_type_id, source_entity_id,
        target_entity_id, status, selection_reason, selected_authority_tier,
        selected_authority_priority, input_hash, projected_at
    )
    SELECT gen_random_uuid(), desired.tenant_id, 1,
           desired.relationship_type_id, desired.source_entity_id,
           desired.target_entity_id, desired.status, desired.selection_reason,
           CASE WHEN desired.selection_reason = 'source_authority'
                THEN desired.authority_tier END,
           CASE WHEN desired.selection_reason = 'source_authority'
                THEN desired.authority_priority END,
           desired.input_hash, projected_at
      FROM desired_relationships desired
     WHERE desired.status <> 'active'
    ON CONFLICT (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
    DO UPDATE SET status = EXCLUDED.status,
                  selection_reason = EXCLUDED.selection_reason,
                  selected_authority_tier = EXCLUDED.selected_authority_tier,
                  selected_authority_priority = EXCLUDED.selected_authority_priority,
                  input_hash = EXCLUDED.input_hash,
                  projected_at = EXCLUDED.projected_at,
                  version = entity_relationships.version + 1
      WHERE entity_relationships.input_hash IS DISTINCT FROM EXCLUDED.input_hash
         OR entity_relationships.status IS DISTINCT FROM EXCLUDED.status
         OR entity_relationships.selection_reason IS DISTINCT FROM EXCLUDED.selection_reason;
    GET DIAGNOSTICS relationship_writes = ROW_COUNT;

    INSERT INTO entity_relationships (
        id, tenant_id, version, relationship_type_id, source_entity_id,
        target_entity_id, status, selection_reason, selected_authority_tier,
        selected_authority_priority, input_hash, projected_at
    )
    SELECT gen_random_uuid(), desired.tenant_id, 1,
           desired.relationship_type_id, desired.source_entity_id,
           desired.target_entity_id, desired.status, desired.selection_reason,
           CASE WHEN desired.selection_reason = 'source_authority'
                THEN desired.authority_tier END,
           CASE WHEN desired.selection_reason = 'source_authority'
                THEN desired.authority_priority END,
           desired.input_hash, projected_at
      FROM desired_relationships desired
     WHERE desired.status = 'active'
    ON CONFLICT (tenant_id, relationship_type_id, source_entity_id, target_entity_id)
    DO UPDATE SET status = EXCLUDED.status,
                  selection_reason = EXCLUDED.selection_reason,
                  selected_authority_tier = EXCLUDED.selected_authority_tier,
                  selected_authority_priority = EXCLUDED.selected_authority_priority,
                  input_hash = EXCLUDED.input_hash,
                  projected_at = EXCLUDED.projected_at,
                  version = entity_relationships.version + 1
      WHERE entity_relationships.input_hash IS DISTINCT FROM EXCLUDED.input_hash
         OR entity_relationships.status IS DISTINCT FROM EXCLUDED.status
         OR entity_relationships.selection_reason IS DISTINCT FROM EXCLUDED.selection_reason;
    GET DIAGNOSTICS activated = ROW_COUNT;
    relationship_writes := relationship_writes + activated;

    DELETE FROM entity_relationship_evidence_support support
    USING entity_relationships edge, relationship_projection_tuples batch
    WHERE support.tenant_id = edge.tenant_id
      AND support.relationship_id = edge.id
      AND edge.tenant_id = batch.tenant_id
      AND edge.relationship_type_id = batch.relationship_type_id
      AND edge.source_entity_id = batch.source_entity_id
      AND edge.target_entity_id = batch.target_entity_id;

    INSERT INTO entity_relationship_evidence_support (
        id, tenant_id, relationship_id, evidence_id
    )
    SELECT gen_random_uuid(), edge.tenant_id, edge.id, evidence.id
      FROM desired_relationships desired
      JOIN entity_relationships edge
        ON edge.tenant_id = desired.tenant_id
       AND edge.relationship_type_id = desired.relationship_type_id
       AND edge.source_entity_id = desired.source_entity_id
       AND edge.target_entity_id = desired.target_entity_id
      JOIN entity_relationship_evidence_current evidence
        ON evidence.tenant_id = desired.tenant_id
       AND evidence.relationship_type_id = desired.relationship_type_id
       AND evidence.source_entity_id = desired.source_entity_id
       AND evidence.target_entity_id = desired.target_entity_id
       AND evidence.active AND evidence.authority_eligible
       AND evidence.resolution_status = 'resolved'
       AND evidence.authority_tier = desired.authority_tier
       AND evidence.authority_priority = desired.authority_priority
     WHERE desired.selection_reason = 'source_authority';
    GET DIAGNOSTICS support_writes = ROW_COUNT;

    DELETE FROM entity_relationship_dirty dirty
    USING relationship_projection_batch batch
    WHERE dirty.id = batch.id;
    RETURN NEXT;
END;
$function$;
"""

_STATUS_CHOICES = [
    ("active", "Active"),
    ("suppressed", "Suppressed"),
    ("no_evidence", "No eligible evidence"),
    ("conflict", "Targets disagree"),
    ("superseded", "Outranked by another target"),
]


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0394_reconcile_participants_without_finding_lock"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, _previous_function()),
        migrations.AlterField(
            model_name="entityrelationshipcurrent",
            name="status",
            field=models.CharField(choices=_STATUS_CHOICES, max_length=16),
        ),
    ]
