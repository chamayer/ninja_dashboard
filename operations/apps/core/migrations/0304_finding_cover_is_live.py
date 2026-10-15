"""Cover is a live relation between two open findings, not a fact frozen in an assessment.

Until now a finding was "covered" only if its last assessment named an open covering finding. So a
parent that opened later could not cover its children until they were reassessed, and when a parent
closed the children's frozen "suppressed" assessments kept them Pending until they were reassessed.

``compute_finding_state`` now decides cover itself, from the open findings on the same computer
whose type is in the child's ``finding_types.covered_by`` chain (root-most parents stored in
``covered_by``). The existing triggers already refresh a finding's dependents when it opens or
closes, so both directions are immediate. Assessments stop carrying cover; the policy is unchanged
(its now-redundant ``parent_open`` rule goes at the next policy version).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION operations.compute_finding_state(p_ids uuid[])
RETURNS TABLE (
    finding_id uuid, tenant_id bigint, finding_type_id smallint,
    attention text, reason text, covered_by uuid[], policy_version text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
BEGIN
    IF p_ids IS NULL OR cardinality(p_ids) = 0 THEN
        RETURN;
    END IF;
    RETURN QUERY
    WITH pol AS (
        SELECT v.version, (v.policy->>'freshness_hours')::integer AS fresh_hours
          FROM operations.condition_policy_versions v
         WHERE v.active ORDER BY v.version DESC LIMIT 1
    ), target AS (
        SELECT f.id, f.tenant_id, f.finding_type_id, f.status, f.subject_type, f.subject_id
          FROM operations.findings f
         WHERE f.id = ANY(p_ids)
    ), expected AS (
        SELECT t.id,
               COALESCE(array_agg(DISTINCT cp.participant_kind || ':' || cp.participant_id::text
                                           || ':' || cp.participant_role
                         ORDER BY cp.participant_kind || ':' || cp.participant_id::text
                                           || ':' || cp.participant_role)
                        FILTER (WHERE cp.participant_role <> 'context'), ARRAY[]::text[]) AS participants
          FROM target t
     LEFT JOIN operations.condition_participants cp
            ON cp.tenant_id = t.tenant_id AND cp.row_kind = 'entity' AND cp.finding_id = t.id
         GROUP BY t.id
    ), assessed AS (
        SELECT a.finding_id,
               bool_or(a.participant_kind = 'condition'
                       AND (a.response->>'may_execute')::boolean IS TRUE) AS condition_execute,
               COALESCE(array_agg(DISTINCT a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role
                         ORDER BY a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role)
                        FILTER (WHERE a.participant_kind <> 'condition'), ARRAY[]::text[]) AS participants,
               COALESCE(array_agg(DISTINCT a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role
                         ORDER BY a.participant_kind || ':' || a.participant_id::text
                                           || ':' || a.participant_role)
                        FILTER (WHERE a.participant_kind <> 'condition'
                                  AND (a.response->>'may_execute')::boolean IS TRUE),
                        ARRAY[]::text[]) AS executable_participants,
               bool_or(a.response->>'disposition' = 'blocked') AS blocked
          FROM operations.condition_assessments a
          JOIN target t ON t.id = a.finding_id AND t.tenant_id = a.tenant_id
          JOIN pol ON pol.version = a.policy_version
         WHERE a.row_kind = 'entity'
           AND a.participant_role <> 'context'
           AND a.assessed_at >= now() - pol.fresh_hours * interval '1 hour'
         GROUP BY a.finding_id
    ), cover_chain AS (
        -- Every type that covers a type, directly or through a chain (finding_types.covered_by).
        WITH RECURSIVE chain(child, ancestor) AS (
            SELECT ft.name, p.v
              FROM operations.finding_types ft
             CROSS JOIN LATERAL jsonb_array_elements_text(ft.covered_by) p(v)
            UNION
            SELECT chain.child, p2.v
              FROM chain
              JOIN operations.finding_types ft2 ON ft2.name = chain.ancestor
             CROSS JOIN LATERAL jsonb_array_elements_text(ft2.covered_by) p2(v)
        )
        SELECT child, ancestor FROM chain
    ), open_parents AS (
        -- The open findings on the same computer whose type covers the target's type.
        SELECT t.id AS child_id, p.id AS parent_id, pt.name AS parent_type
          FROM target t
          JOIN operations.finding_types ct ON ct.id = t.finding_type_id
          JOIN cover_chain cc ON cc.child = ct.name
          JOIN operations.finding_types pt ON pt.name = cc.ancestor
          JOIN operations.findings p
            ON p.finding_type_id = pt.id AND p.tenant_id = t.tenant_id
           AND p.subject_type = t.subject_type AND p.subject_id = t.subject_id
           AND p.status IN ('open', 'acknowledged', 'investigating') AND p.id <> t.id
         WHERE t.subject_type = 'device'
           AND t.status IN ('open', 'acknowledged', 'investigating')
    ), covering AS (
        -- Root-most only: a parent that is itself covered by another open parent of the same
        -- finding is not named, so the reference always points at a visible finding.
        SELECT op.child_id AS finding_id,
               array_agg(DISTINCT op.parent_id ORDER BY op.parent_id) AS parents,
               min(op.parent_type) AS parent_type
          FROM open_parents op
         WHERE NOT EXISTS (
               SELECT 1 FROM open_parents other
                 JOIN cover_chain cc2 ON cc2.child = op.parent_type AND cc2.ancestor = other.parent_type
                WHERE other.child_id = op.child_id)
         GROUP BY op.child_id
    )
    SELECT t.id, t.tenant_id, t.finding_type_id,
           CASE
               WHEN t.status NOT IN ('open', 'acknowledged', 'investigating') THEN NULL
               WHEN cv.finding_id IS NOT NULL THEN 'covered'
               WHEN a.finding_id IS NULL THEN 'pending'
               WHEN (e.participants = ARRAY[]::text[] AND COALESCE(a.condition_execute, false))
                 OR (e.participants <> ARRAY[]::text[]
                     AND a.participants = e.participants
                     AND a.executable_participants = e.participants) THEN 'needs_action'
               WHEN COALESCE(a.blocked, false) THEN 'blocked'
               ELSE 'pending'
           END,
           CASE
               WHEN t.status NOT IN ('open', 'acknowledged', 'investigating') THEN 'closed'
               WHEN cv.finding_id IS NOT NULL THEN 'covered_by:' || cv.parent_type
               WHEN a.finding_id IS NULL THEN 'no_current_assessment'
               WHEN (e.participants = ARRAY[]::text[] AND COALESCE(a.condition_execute, false))
                 OR (e.participants <> ARRAY[]::text[]
                     AND a.participants = e.participants
                     AND a.executable_participants = e.participants) THEN 'ready'
               WHEN COALESCE(a.blocked, false) THEN 'blocked_by_evidence'
               ELSE 'incomplete_assessment'
           END,
           COALESCE(cv.parents, ARRAY[]::uuid[]),
           (SELECT pol.version FROM pol)
      FROM target t
      JOIN expected e ON e.id = t.id
 LEFT JOIN assessed a ON a.finding_id = t.id
 LEFT JOIN covering cv ON cv.finding_id = t.id;
END
$function$;
"""

REVERSE_SQL = migrations.RunSQL.noop


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0303_drop_attention_view_and_columns"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
